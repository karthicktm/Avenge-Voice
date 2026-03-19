"""Category Trees API — admin CRUD, structured upload, AI discovery, and categorize endpoint."""

import asyncio
import csv
import io
import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedUser
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.category_tree import CategoryResult, CategoryTree

logger = structlog.get_logger()

router = APIRouter(prefix="/category-trees", tags=["category-trees"])

MAX_NODES = 500
MAX_DEPTH = 5
MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB
MAX_RAW_FILE_BYTES = 10 * 1024 * 1024  # 10 MB for AI discovery
FTS_THRESHOLD = 0.05  # ts_rank scores below this go to LLM layer


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class TreeMeta(BaseModel):
    """Summary info for a category tree (one row per tree_name per workspace)."""

    tree_name: str
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    source_type: str
    status: str
    node_count: int
    created_at: str


class NodeResponse(BaseModel):
    id: uuid.UUID
    tree_name: str
    workspace_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    status: str
    code: str | None = None
    label: str
    parent_id: uuid.UUID | None = None
    depth: int
    position: int

    model_config = {"from_attributes": True}


class CreateTreeRequest(BaseModel):
    tree_name: str = Field(..., min_length=1, max_length=120)
    agent_id: uuid.UUID | None = None
    workspace_id: uuid.UUID


class NodeAddRequest(BaseModel):
    label: str = Field(..., min_length=1, max_length=300)
    parent_id: uuid.UUID | None = None
    code: str | None = Field(None, max_length=80)
    position: int = 0


class NodeUpdateRequest(BaseModel):
    label: str | None = Field(None, min_length=1, max_length=300)
    code: str | None = Field(None, max_length=80)
    parent_id: uuid.UUID | None = None
    position: int | None = None


class DiscoverHints(BaseModel):
    label: str | None = None
    max_depth: int = Field(3, ge=2, le=10)
    approx_top_level: str = "ai_decides"  # 5-10 | 10-20 | 20+ | ai_decides


class CategorizeRequest(BaseModel):
    text: str = Field(..., min_length=1)
    tree_name: str = Field(..., min_length=1, max_length=120)
    call_id: uuid.UUID | None = None
    top_k: int = Field(1, ge=1, le=5)
    workspace_id: uuid.UUID  # caller must provide — workspace resolved from context too


class CategorizeResponse(BaseModel):
    matched: bool
    code: str | None = None
    label: str | None = None
    path: list[str]
    depth: int
    confidence: float | None = None
    result_id: uuid.UUID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _require_tree_access(
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    db: AsyncSession,
) -> None:
    """Raise 404 if no nodes for (workspace, tree_name) belong to this user."""
    result = await db.execute(
        select(func.count(CategoryTree.id)).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
        )
    )
    count = result.scalar() or 0
    if count == 0:
        raise HTTPException(status_code=404, detail="Category tree not found")


async def _get_node_or_404(
    node_id: uuid.UUID,
    user_id: int,
    db: AsyncSession,
) -> CategoryTree:
    result = await db.execute(
        select(CategoryTree).where(
            CategoryTree.id == node_id,
            CategoryTree.user_id == user_id,
        )
    )
    node = result.scalar_one_or_none()
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


def _build_path(node: CategoryTree, all_nodes: dict[uuid.UUID, CategoryTree]) -> list[str]:
    """Walk parent_id chain to build label path from root to node."""
    path: list[str] = []
    current: CategoryTree | None = node
    while current is not None:
        path.insert(0, current.label)
        if current.parent_id is None:
            break
        current = all_nodes.get(current.parent_id)
    return path


def _nodes_to_response(nodes: list[CategoryTree]) -> list[NodeResponse]:
    return [
        NodeResponse(
            id=n.id,
            tree_name=n.tree_name,
            workspace_id=n.workspace_id,
            agent_id=n.agent_id,
            status=n.status,
            code=n.code,
            label=n.label,
            parent_id=n.parent_id,
            depth=n.depth,
            position=n.position,
        )
        for n in nodes
    ]


# ---------------------------------------------------------------------------
# List / describe trees
# ---------------------------------------------------------------------------


@router.get("", response_model=list[TreeMeta])
@limiter.limit("60/minute")
async def list_trees(
    request: Request,
    user: VerifiedUser,
    workspace_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
) -> list[TreeMeta]:
    """List distinct category trees for a workspace."""
    stmt = (
        select(
            CategoryTree.tree_name,
            CategoryTree.workspace_id,
            CategoryTree.agent_id,
            CategoryTree.source_type,
            CategoryTree.status,
            func.count(CategoryTree.id).label("node_count"),
            func.min(CategoryTree.created_at).label("created_at"),
        )
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.user_id == user.id,
        )
        .group_by(
            CategoryTree.tree_name,
            CategoryTree.workspace_id,
            CategoryTree.agent_id,
            CategoryTree.source_type,
            CategoryTree.status,
        )
        .order_by(func.min(CategoryTree.created_at).desc())
    )
    result = await db.execute(stmt)
    rows = result.fetchall()
    return [
        TreeMeta(
            tree_name=row.tree_name,
            workspace_id=row.workspace_id,
            agent_id=row.agent_id,
            source_type=row.source_type,
            status=row.status,
            node_count=row.node_count,
            created_at=row.created_at.isoformat() if row.created_at else "",
        )
        for row in rows
    ]


@router.get("/{workspace_id}/{tree_name}/nodes", response_model=list[NodeResponse])
@limiter.limit("60/minute")
async def get_tree_nodes(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    flat: bool = Query(False, description="Return flat list instead of tree"),
    db: AsyncSession = Depends(get_db),
) -> list[NodeResponse]:
    """Return all nodes for a tree, ordered by depth then position."""
    result = await db.execute(
        select(CategoryTree)
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
        )
        .order_by(CategoryTree.depth, CategoryTree.position)
    )
    nodes = list(result.scalars().all())
    return _nodes_to_response(nodes)


# ---------------------------------------------------------------------------
# Create tree metadata
# ---------------------------------------------------------------------------


@router.post("", response_model=dict[str, str], status_code=201)
@limiter.limit("20/minute")
async def create_tree(
    request: Request,
    body: CreateTreeRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Create a new tree entry (no nodes yet — use import or discover next)."""
    # Check name not already taken in workspace
    result = await db.execute(
        select(func.count(CategoryTree.id)).where(
            CategoryTree.workspace_id == body.workspace_id,
            CategoryTree.tree_name == body.tree_name,
            CategoryTree.user_id == user.id,
        )
    )
    if (result.scalar() or 0) > 0:
        raise HTTPException(
            status_code=409, detail="A tree with this name already exists in this workspace"
        )
    return {"tree_name": body.tree_name, "status": "created"}


# ---------------------------------------------------------------------------
# Structured upload — Option A
# ---------------------------------------------------------------------------


@router.get("/templates/{fmt}")
@limiter.limit("30/minute")
async def download_template(
    request: Request,
    fmt: str,
    user: VerifiedUser,
) -> StreamingResponse:
    """Download a blank import template (.csv, .json, or .xlsx placeholder)."""
    if fmt not in {"csv", "json", "xlsx"}:
        raise HTTPException(status_code=400, detail="Format must be csv, json, or xlsx")

    example_rows = [
        {"code": "W001", "level_1": "Water/leakage", "level_2": "Bathroom", "level_3": "Tap"},
        {"code": "W002", "level_1": "Water/leakage", "level_2": "Kitchen", "level_3": "Sink"},
        {"code": "H001", "level_1": "Heat/ventilation", "level_2": "Radiator", "level_3": ""},
    ]

    if fmt == "json":
        payload = [
            {
                "code": r["code"],
                "path": [v for v in [r["level_1"], r["level_2"], r["level_3"]] if v],
            }
            for r in example_rows
        ]
        content = json.dumps(payload, indent=2)
        media = "application/json"
        filename = "category_template.json"

        def gen() -> Any:
            yield content

    elif fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf, fieldnames=["code", "level_1", "level_2", "level_3", "level_4"]
        )
        writer.writeheader()
        for row in example_rows:
            writer.writerow({**row, "level_4": ""})
        content_str = buf.getvalue()
        media = "text/csv"
        filename = "category_template.csv"

        def gen() -> Any:
            yield content_str

    else:  # xlsx hint
        content = "Excel template: columns code, level_1, level_2, level_3, level_4"
        media = "text/plain"
        filename = "category_template_readme.txt"

        def gen() -> Any:
            yield content

    return StreamingResponse(
        gen(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _parse_structured_file(content: bytes, filename: str) -> list[dict[str, str]]:  # noqa: PLR0912
    """Parse .csv, .json, or .xlsx upload into a list of flat row dicts."""
    fn = filename.lower()

    if fn.endswith(".json"):
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="JSON must be an array of objects")
        rows = []
        for i, item in enumerate(parsed):
            if not isinstance(item, dict):
                raise HTTPException(status_code=400, detail=f"Row {i}: expected object")
            path = item.get("path", [])
            rows.append(
                {
                    "code": str(item.get("code", "") or ""),
                    **{f"level_{j + 1}": str(path[j]) if j < len(path) else "" for j in range(4)},
                }
            )
        return rows

    if fn.endswith(".csv"):
        try:
            text = content.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            return [dict(r) for r in reader]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc

    if fn.endswith(".xlsx"):
        try:
            import openpyxl  # type: ignore[import-untyped]

            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            if ws is None:
                raise HTTPException(status_code=400, detail="Empty Excel file")  # noqa: TRY301
            headers: list[str] = []
            rows = []
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i == 0:
                    headers = [str(c) if c is not None else f"col{j}" for j, c in enumerate(row)]
                else:
                    rows.append(
                        dict(
                            zip(
                                headers,
                                (str(v) if v is not None else "" for v in row),
                                strict=False,
                            )
                        )
                    )
            return rows
        except ImportError as exc:
            raise HTTPException(
                status_code=500, detail="openpyxl not installed — cannot process Excel files"
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}") from exc

    raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv, .xlsx, or .json")


def _validate_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Validate structured rows and return normalised node dicts. Raises on error."""
    if len(rows) > MAX_NODES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows ({len(rows)}). Maximum is {MAX_NODES}.",
        )

    errors: list[str] = []
    codes_seen: set[str] = set()
    nodes: list[dict[str, Any]] = []

    for i, row in enumerate(rows, start=2):  # row 1 is header
        levels = [str(row.get(f"level_{j}", "") or "").strip() for j in range(1, 5)]
        # level_1 and level_2 are required
        if not levels[0]:
            errors.append(f"Row {i}: level_1 is required")
            continue
        if not levels[1]:
            errors.append(f"Row {i}: level_2 is required")
            continue

        code = str(row.get("code", "") or "").strip() or None
        if code:
            if code in codes_seen:
                errors.append(f"Row {i}: duplicate code '{code}'")
                continue
            codes_seen.add(code)

        path = [lv for lv in levels if lv]
        if len(path) > MAX_DEPTH:
            errors.append(f"Row {i}: depth {len(path)} exceeds maximum {MAX_DEPTH}")
            continue

        nodes.append({"code": code, "path": path})

    if errors:
        raise HTTPException(status_code=422, detail={"errors": errors})

    return nodes


@router.post("/{workspace_id}/{tree_name}/import/structured", status_code=200)
@limiter.limit("10/minute")
async def import_structured_validate(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Validate a structured upload file and return a preview (no DB writes yet)."""
    content = await file.read()
    if len(content) > MAX_FILE_BYTES:
        raise HTTPException(status_code=400, detail="File exceeds 5 MB limit")

    rows = _parse_structured_file(content, file.filename or "upload.csv")
    nodes = _validate_rows(rows)

    # Build a condensed tree preview (top 3 levels, first 50 nodes)
    preview = nodes[:50]
    return {
        "valid": True,
        "node_count": len(nodes),
        "preview": preview,
        # Encode nodes in session — but since we have no session store, return them for confirm
        "import_data": nodes,
    }


class ConfirmImportRequest(BaseModel):
    import_data: list[dict[str, Any]]
    agent_id: uuid.UUID | None = None


@router.post("/{workspace_id}/{tree_name}/import/confirm", status_code=201)
@limiter.limit("10/minute")
async def import_structured_confirm(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    body: ConfirmImportRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Persist confirmed structured import. Overwrites any existing active/draft tree."""
    if len(body.import_data) > MAX_NODES:
        raise HTTPException(status_code=400, detail="Too many nodes")

    # Delete existing nodes for this tree (archive old data)
    await db.execute(
        delete(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
        )
    )

    # Build nodes with parent tracking
    # Key: tuple of path segments → node id
    path_to_id: dict[tuple[str, ...], uuid.UUID] = {}

    nodes_to_add: list[CategoryTree] = []

    for item in body.import_data:
        path: list[str] = item.get("path", [])
        code: str | None = item.get("code")
        if not path:
            continue

        # Ensure all ancestors exist
        for depth in range(len(path)):
            seg = tuple(path[: depth + 1])
            if seg in path_to_id:
                continue
            is_leaf = depth == len(path) - 1
            parent_id = path_to_id.get(tuple(path[:depth])) if depth > 0 else None

            node = CategoryTree(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                agent_id=body.agent_id,
                user_id=user.id,
                tree_name=tree_name,
                source_type="structured_upload",
                status="active",
                code=code if is_leaf else None,
                label=path[depth],
                parent_id=parent_id,
                depth=depth,
                position=len([k for k in path_to_id if len(k) == depth + 1]),
            )
            path_to_id[seg] = node.id
            nodes_to_add.append(node)

    for node in nodes_to_add:
        db.add(node)

    await db.commit()
    logger.info(
        "category_tree_imported",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
        node_count=len(nodes_to_add),
    )
    return {"imported": len(nodes_to_add), "tree_name": tree_name, "status": "active"}


# ---------------------------------------------------------------------------
# AI discovery — Option B
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/{tree_name}/discover", status_code=202)
@limiter.limit("5/minute")
async def start_ai_discovery(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    # hints come as query params — cleanly separates from optional file body
    label: str | None = Query(None),
    max_depth: int = Query(3, ge=2, le=10),
    approx_top_level: str = Query("ai_decides"),
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Start AI discovery background job to build a draft category tree.

    Hints are passed as query params; optional file upload is multipart body.
    """
    from app.db.redis import get_redis
    from app.services.category_discovery_worker import start_discovery_job

    hints = DiscoverHints(
        label=label,
        max_depth=max(2, min(max_depth, 10)),
        approx_top_level=approx_top_level,
    )

    content: bytes = b""
    if file is not None:
        content = await file.read()
        if len(content) > MAX_RAW_FILE_BYTES:
            raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

    job_id = str(uuid.uuid4())
    redis = await get_redis()
    await redis.set(
        f"category_discovery:job:{job_id}",
        json.dumps({"status": "pending", "job_id": job_id}),
        ex=3600,
    )

    # Fire off background task
    asyncio.create_task(  # noqa: RUF006
        start_discovery_job(
            job_id=job_id,
            workspace_id=workspace_id,
            tree_name=tree_name,
            user_id=user.id,
            hints=hints.model_dump(),
            raw_content=content,
        )
    )

    return {"job_id": job_id, "status": "pending"}


@router.get("/jobs/{job_id}")
@limiter.limit("120/minute")
async def poll_job(
    request: Request,
    job_id: str,
    user: VerifiedUser,
) -> dict[str, Any]:
    """Poll AI discovery job status."""
    from app.db.redis import get_redis

    redis = await get_redis()
    raw = await redis.get(f"category_discovery:job:{job_id}")
    if raw is None:
        raise HTTPException(status_code=404, detail="Job not found or expired")
    return json.loads(raw)  # type: ignore[no-any-return]


@router.post("/{workspace_id}/{tree_name}/approve", status_code=200)
@limiter.limit("20/minute")
async def approve_draft(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Approve a draft tree: set all its nodes to status='active'."""
    await _require_tree_access(workspace_id, tree_name, user, db)

    result = await db.execute(
        select(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
            CategoryTree.status == "draft",
        )
    )
    nodes = list(result.scalars().all())
    if not nodes:
        raise HTTPException(status_code=404, detail="No draft nodes found for this tree")

    for node in nodes:
        node.status = "active"

    await db.commit()
    return {"activated": len(nodes), "tree_name": tree_name}


@router.delete("/{workspace_id}/{tree_name}/draft", status_code=204)
@limiter.limit("20/minute")
async def discard_draft(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete all draft nodes for this tree (cannot be undone)."""
    await db.execute(
        delete(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
            CategoryTree.status == "draft",
        )
    )
    await db.commit()


# ---------------------------------------------------------------------------
# Node CRUD
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/{tree_name}/nodes", response_model=NodeResponse, status_code=201)
@limiter.limit("60/minute")
async def add_node(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    body: NodeAddRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> NodeResponse:
    """Add a node to an existing tree (draft or active)."""
    depth = 0
    if body.parent_id is not None:
        parent = await _get_node_or_404(body.parent_id, user.id, db)
        depth = parent.depth + 1

    # Get current status of tree
    result = await db.execute(
        select(CategoryTree.status)
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
        )
        .limit(1)
    )
    existing_status = result.scalar_one_or_none() or "active"

    node = CategoryTree(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        user_id=user.id,
        tree_name=tree_name,
        source_type="structured_upload",
        status=existing_status,
        code=body.code,
        label=body.label,
        parent_id=body.parent_id,
        depth=depth,
        position=body.position,
    )
    db.add(node)
    await db.commit()
    await db.refresh(node)
    return NodeResponse(
        id=node.id,
        tree_name=node.tree_name,
        workspace_id=node.workspace_id,
        agent_id=node.agent_id,
        status=node.status,
        code=node.code,
        label=node.label,
        parent_id=node.parent_id,
        depth=node.depth,
        position=node.position,
    )


@router.put("/{workspace_id}/{tree_name}/nodes/{node_id}", response_model=NodeResponse)
@limiter.limit("60/minute")
async def update_node(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    node_id: uuid.UUID,
    body: NodeUpdateRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> NodeResponse:
    """Rename, reparent, or reorder a node."""
    node = await _get_node_or_404(node_id, user.id, db)

    if body.label is not None:
        node.label = body.label
    if body.code is not None:
        node.code = body.code
    if body.position is not None:
        node.position = body.position
    if body.parent_id is not None:
        parent = await _get_node_or_404(body.parent_id, user.id, db)
        node.parent_id = parent.id
        node.depth = parent.depth + 1

    await db.commit()
    await db.refresh(node)
    return NodeResponse(
        id=node.id,
        tree_name=node.tree_name,
        workspace_id=node.workspace_id,
        agent_id=node.agent_id,
        status=node.status,
        code=node.code,
        label=node.label,
        parent_id=node.parent_id,
        depth=node.depth,
        position=node.position,
    )


@router.delete("/{workspace_id}/{tree_name}/nodes/{node_id}", status_code=204)
@limiter.limit("60/minute")
async def delete_node(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    node_id: uuid.UUID,
    user: VerifiedUser,
    cascade: bool = Query(False),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a node. cascade=true required if node has children."""
    node = await _get_node_or_404(node_id, user.id, db)

    # Check for children
    child_result = await db.execute(
        select(func.count(CategoryTree.id)).where(CategoryTree.parent_id == node_id)
    )
    child_count = child_result.scalar() or 0
    if child_count > 0 and not cascade:
        raise HTTPException(
            status_code=400,
            detail=f"Node has {child_count} children. Pass cascade=true to delete them too.",
        )

    await db.delete(node)
    await db.commit()


# ---------------------------------------------------------------------------
# Archive tree
# ---------------------------------------------------------------------------


@router.delete("/{workspace_id}/{tree_name}", status_code=204)
@limiter.limit("10/minute")
async def archive_tree(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Archive (soft-delete) a tree by setting all nodes to status='archived'."""
    await _require_tree_access(workspace_id, tree_name, user, db)

    result = await db.execute(
        select(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
        )
    )
    nodes = list(result.scalars().all())
    for node in nodes:
        node.status = "archived"
    await db.commit()


# ---------------------------------------------------------------------------
# Categorize endpoint — used by the agent tool and by direct API consumers
# ---------------------------------------------------------------------------


@router.post("/categorize", response_model=CategorizeResponse)
@limiter.limit("600/minute")
async def categorize(
    request: Request,
    body: CategorizeRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CategorizeResponse:
    """Classify input text against an active category tree.

    Layer 1: Postgres FTS (ts_rank). If score >= threshold → return immediately.
    Layer 2: LLM selects best from top-5 FTS candidates.
    """
    from app.services.category_matcher import match_category

    matched_node, confidence, layer = await match_category(
        db=db,
        workspace_id=body.workspace_id,
        tree_name=body.tree_name,
        text=body.text,
        user_id=user.id,
        top_k=body.top_k,
    )

    matched = matched_node is not None

    # Build path for matched node
    path: list[str] = []
    depth = 0
    code = None
    label = None

    if matched_node:
        depth = matched_node.depth
        code = matched_node.code
        label = matched_node.label
        # Load all nodes to build path
        all_result = await db.execute(
            select(CategoryTree).where(
                CategoryTree.workspace_id == body.workspace_id,
                CategoryTree.tree_name == body.tree_name,
                CategoryTree.status == "active",
            )
        )
        all_nodes = {n.id: n for n in all_result.scalars().all()}
        path = _build_path(matched_node, all_nodes)

    # Write audit record
    result_row = CategoryResult(
        id=uuid.uuid4(),
        call_id=body.call_id,
        workspace_id=body.workspace_id,
        agent_id=None,  # not known at this endpoint level
        tree_name=body.tree_name,
        matched_node_id=matched_node.id if matched_node else None,
        matched_code=code,
        matched_path=path,
        input_text=body.text,
        confidence=confidence,
        resolution_layer=layer,
    )
    db.add(result_row)
    await db.commit()

    return CategorizeResponse(
        matched=matched,
        code=code,
        label=label,
        path=path,
        depth=depth,
        confidence=confidence,
        result_id=result_row.id,
    )

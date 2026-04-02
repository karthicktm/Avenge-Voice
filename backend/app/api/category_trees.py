"""Category Trees API — admin CRUD, structured upload, AI discovery, and categorize endpoint."""

import asyncio
import contextlib
import csv
import io
import json
import re
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
    metadata: dict[str, Any] | None = None

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
    metadata: dict[str, Any] | None = None


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
            metadata=n.node_metadata,
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

    else:  # xlsx — real workbook with all metadata columns
        try:
            import openpyxl  # type: ignore[import-untyped]
            from openpyxl.styles import Font, PatternFill  # type: ignore[import-untyped]
        except ImportError as exc:
            raise HTTPException(
                status_code=500, detail="openpyxl not installed — cannot generate Excel template"
            ) from exc

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Category Template"

        header_cols = [
            "code",
            "level_1",
            "level_2",
            "level_3",
            "level_4",
            "example_query",
            "urgency_level",
            "self_resolution",
            "requires_property_info",
            "can_report_fault",
            "requires_manual_support",
            "info_to_collect",
        ]
        ws.append(header_cols)

        # Style header row
        header_fill = PatternFill(start_color="1E3A5F", end_color="1E3A5F", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF")
        for cell in ws[1]:
            cell.fill = header_fill
            cell.font = header_font

        # Example rows with realistic data
        example_data: list[list[str]] = [
            [
                "W001",
                "Water/leakage",
                "Bathroom",
                "Tap",
                "",
                "The tap in my bathroom is dripping constantly",
                "Prio 3",
                "JA",
                "NEJ",
                "JA",
                "NEJ",
                "Ask how long it has been dripping and whether it is getting worse.",
            ],
            [
                "W002",
                "Water/leakage",
                "Bathroom",
                "Ceiling",
                "",
                "There is water dripping from my bathroom ceiling",
                "Prio 1",
                "NEJ",
                "JA",
                "JA",
                "JA",
                "Ask which floor they are on and whether the apartment above is aware.",
            ],
            [
                "H001",
                "Heat/ventilation",
                "Radiator",
                "",
                "",
                "The radiator in my living room is not working",
                "Prio 2",
                "JA",
                "NEJ",
                "JA",
                "NEJ",
                "Ask if all radiators are affected or just this one.",
            ],
        ]
        for example_row in example_data:
            ws.append(example_row)

        # Auto-fit column widths
        for col in ws.columns:
            max_len = max(len(str(cell.value or "")) for cell in col)
            ws.column_dimensions[col[0].column_letter].width = min(max_len + 4, 55)

        xlsx_buf = io.BytesIO()
        wb.save(xlsx_buf)
        xlsx_buf.seek(0)
        xlsx_bytes = xlsx_buf.read()
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        filename = "category_template.xlsx"

        def gen() -> Any:
            yield xlsx_bytes

    return StreamingResponse(
        gen(),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Export — download live tree data in importable format
# ---------------------------------------------------------------------------

_METADATA_EXPORT_FIELDS = [
    "example_query",
    "urgency_level",
    "self_resolution",
    "requires_property_info",
    "can_report_fault",
    "requires_manual_support",
    "info_to_collect",
]


@router.get("/{workspace_id}/{tree_name}/export/{fmt}")
@limiter.limit("30/minute")
async def export_tree(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    fmt: str,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all active nodes of a tree as a CSV or JSON file in the same format as the import template."""
    if fmt not in {"csv", "json"}:
        raise HTTPException(status_code=400, detail="Format must be csv or json")

    await _require_tree_access(workspace_id, tree_name, user, db)

    result = await db.execute(
        select(CategoryTree)
        .where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user.id,
            CategoryTree.status != "archived",
        )
        .order_by(CategoryTree.depth, CategoryTree.position)
    )
    nodes = list(result.scalars().all())

    node_map: dict[uuid.UUID, CategoryTree] = {n.id: n for n in nodes}

    # Export every node (all depths) so enriched metadata at intermediate levels is included.
    # Rows are already ordered by depth (shallow first), which ensures round-trip import works.
    export_nodes = nodes

    def build_path(node: CategoryTree) -> list[str]:
        path: list[str] = []
        cur: CategoryTree | None = node
        while cur is not None:
            path.insert(0, cur.label)
            cur = node_map.get(cur.parent_id) if cur.parent_id else None
        return path

    safe_name = re.sub(r"[^\w\-]", "_", tree_name)

    if fmt == "json":
        payload = []
        for node in export_nodes:
            path = build_path(node)
            item: dict[str, Any] = {"code": node.code, "path": path}
            if node.node_metadata:
                item["metadata"] = node.node_metadata
            payload.append(item)
        content = json.dumps(payload, indent=2)
        media = "application/json"
        filename = f"{safe_name}_export.json"

        def gen_json() -> Any:
            yield content

        return StreamingResponse(
            gen_json(),
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # CSV
    max_depth = max((len(build_path(n)) for n in export_nodes), default=1)
    level_cols = [f"level_{i + 1}" for i in range(max_depth)]
    # Collect all metadata keys present across nodes
    extra_meta_keys: list[str] = list(_METADATA_EXPORT_FIELDS)
    for node in export_nodes:
        if node.node_metadata:
            for k in node.node_metadata:
                if k not in extra_meta_keys:
                    extra_meta_keys.append(k)

    fieldnames = ["code", *level_cols, *extra_meta_keys]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for node in export_nodes:
        path = build_path(node)
        row: dict[str, Any] = {"code": node.code or ""}
        for i, label in enumerate(path):
            row[f"level_{i + 1}"] = label
        if node.node_metadata:
            for k in extra_meta_keys:
                row[k] = node.node_metadata.get(k, "")
        writer.writerow(row)

    csv_content = buf.getvalue()
    filename = f"{safe_name}_export.csv"

    def gen_csv() -> Any:
        yield csv_content

    return StreamingResponse(
        gen_csv(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Metadata column handling — well-known header aliases + boolean normalization
# ---------------------------------------------------------------------------

# Maps raw column headers (lower-cased, parentheticals stripped) → canonical key names.
# Covers both English and Swedish variants (including K2A-specific column names).
_WELL_KNOWN_HEADER_ALIASES: dict[str, str] = {
    # English
    "example_query": "example_query",
    "example query": "example_query",
    "urgency_level": "urgency_level",
    "urgency level": "urgency_level",
    "priority": "urgency_level",
    "self_resolution": "self_resolution",
    "self resolution": "self_resolution",
    "requires_property_info": "requires_property_info",
    "requires property info": "requires_property_info",
    "can_report_fault": "can_report_fault",
    "can report fault": "can_report_fault",
    "requires_manual_support": "requires_manual_support",
    "requires manual support": "requires_manual_support",
    "info_to_collect": "info_to_collect",
    "info to collect": "info_to_collect",
    "information to collect": "info_to_collect",
    "questions to ask": "info_to_collect",
    # Swedish (K2A column headers, lower-cased, parentheticals handled separately)
    "exempel på användarfråga": "example_query",
    "typisk urgency level": "urgency_level",
    "self resolution möjlig": "self_resolution",
    "kräver fastighetsspecifik information": "requires_property_info",
    "kan felanmälas": "can_report_fault",
    "kan kräva manuell support": "requires_manual_support",
    "ytterligare information som behöver samlas in": "info_to_collect",
}

# Aliases for structural columns so files using Swedish/custom header names
# import directly without any pre-processing.
# Keys are lower-cased; parentheticals already stripped by _canonical_header logic.
_STRUCTURAL_HEADER_ALIASES: dict[str, str] = {
    # code column
    "kategorikod": "code",
    "category code": "code",
    "kategori kod": "code",
    "cat code": "code",
    # level columns — Swedish "Nivå" and common English variants
    "nivå 1": "level_1",
    "niva 1": "level_1",
    "level1": "level_1",
    "l1": "level_1",
    "nivå 2": "level_2",
    "niva 2": "level_2",
    "level2": "level_2",
    "l2": "level_2",
    "nivå 3": "level_3",
    "niva 3": "level_3",
    "level3": "level_3",
    "l3": "level_3",
    "nivå 4": "level_4",
    "niva 4": "level_4",
    "level4": "level_4",
    "l4": "level_4",
    "nivå 5": "level_5",
    "niva 5": "level_5",
    "level5": "level_5",
    "l5": "level_5",
}

# Columns consumed as structural fields — never treated as metadata.
_STRUCTURAL_COLUMNS = {"code", "level_1", "level_2", "level_3", "level_4", "level_5"}

# Metadata keys whose raw JA/NEJ values should be coerced to booleans.
_BOOLEAN_KEYS = {
    "self_resolution",
    "requires_property_info",
    "can_report_fault",
    "requires_manual_support",
}

_TRUTHY = {"ja", "yes", "true", "1", "j", "y"}
_FALSY = {"nej", "no", "false", "0", "n"}


def _canonical_header(raw: str) -> str | None:
    """Return canonical metadata key for a column header, or None if structural.

    Strips trailing parenthetical suffixes like "(JA / NEJ)" before lookup.
    Also tries prefix matching for long Swedish/multilingual headers that start
    with a known alias key (e.g. "ytterligare information som behöver samlas in
    för att vi ska skapa en felanmälan..." → info_to_collect).
    Unknown non-structural headers are kept as-is (arbitrary metadata support).
    """
    key = re.sub(r"\s*\([^)]*\)\s*$", "", raw.strip().lower()).strip()
    if key in _STRUCTURAL_COLUMNS:
        return None
    if key in _WELL_KNOWN_HEADER_ALIASES:
        return _WELL_KNOWN_HEADER_ALIASES[key]
    # Prefix match for long headers (only check aliases ≥ 10 chars to avoid false hits)
    for alias_key, canon in _WELL_KNOWN_HEADER_ALIASES.items():
        if len(alias_key) >= 10 and key.startswith(alias_key):  # noqa: PLR2004
            return canon
    return key  # unknown — store as-is


def _normalize_bool(value: str) -> bool | str:
    """Normalize JA/NEJ/yes/no/1/0 → bool. Unknown values kept as raw string."""
    s = value.strip().lower()
    if s in _TRUTHY:
        return True
    if s in _FALSY:
        return False
    return value  # keep raw for unrecognized strings


def _normalize_row_headers(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rename headers to canonical names so files in any language import directly.

    Strategy:
    1. Known alias matching (Swedish/English hardcoded aliases).
    2. Positional/data fallback for structural columns if level_1 not yet found.
    3. Data-pattern detection for metadata columns not matched by alias — assigns
       canonical keys (example_query, urgency_level, self_resolution, etc.) based
       on the shape of the values, not the column name language.
       This makes import fully language-agnostic.
    """
    if not rows:
        return rows

    original_keys = list(rows[0].keys())

    # Step 1: alias matching for known structural headers
    rename: dict[str, str] = {}
    for raw in original_keys:
        normalized = re.sub(r"\s*\([^)]*\)\s*$", "", raw.strip().lower()).strip()
        if normalized in _STRUCTURAL_HEADER_ALIASES:
            rename[raw] = _STRUCTURAL_HEADER_ALIASES[normalized]

    renamed_keys = {rename.get(k, k) for k in original_keys}

    # Step 2: positional fallback if level_1 not yet identified
    if "level_1" not in renamed_keys:
        rename.update(_detect_structural_columns_by_position(rows, original_keys))

    # Step 3: alias matching for known metadata headers; for any remaining
    # unrecognized metadata headers, infer canonical key by data pattern.
    for raw in original_keys:
        if raw in rename:
            continue  # already mapped as structural
        normalized = re.sub(r"\s*\([^)]*\)\s*$", "", raw.strip().lower()).strip()
        if normalized in _WELL_KNOWN_HEADER_ALIASES:
            rename[raw] = _WELL_KNOWN_HEADER_ALIASES[normalized]

    # Collect remaining unrecognized metadata headers (not structural, not aliased)
    canonical_structural = set(_STRUCTURAL_COLUMNS)
    already_mapped_to = set(rename.values())
    unrecognized_meta = [
        raw
        for raw in original_keys
        if raw not in rename and rename.get(raw, raw) not in canonical_structural
    ]
    if unrecognized_meta:
        rename.update(
            _detect_metadata_columns_by_pattern(rows, unrecognized_meta, already_mapped_to)
        )

    if not rename:
        return rows

    return [{rename.get(k, k): v for k, v in row.items()} for row in rows]


def _detect_metadata_columns_by_pattern(
    rows: list[dict[str, str]],
    headers: list[str],
    already_assigned: set[str],
) -> dict[str, str]:
    """Assign canonical metadata keys to unrecognized columns by data shape.

    Patterns (language-agnostic, applied in column order):
    - Boolean values (YES/NO/JA/NEJ/true/false): assigned left-to-right as
      self_resolution → requires_property_info → can_report_fault →
      requires_manual_support (the four standard flag fields).
    - Short enum (≤ 5 distinct short values, not boolean): urgency_level.
    - Prose columns (high unique ratio + medium-to-long text): the FIRST such
      column is example_query (typical example question), the LAST is
      info_to_collect (instructions for the agent).
    - Anything else: stored as-is under the normalized header name.
    """
    if not rows:
        return {}

    sample = rows[: min(30, len(rows))]

    def col_values(col: str) -> list[str]:
        return [row.get(col, "") for row in sample if row.get(col, "")]

    def avg_len(col: str) -> float:
        vals = col_values(col)
        return sum(len(v) for v in vals) / max(len(vals), 1)

    def unique_ratio(col: str) -> float:
        vals = col_values(col)
        return len(set(vals)) / max(len(vals), 1) if vals else 1.0

    def is_boolean_col(col: str) -> bool:
        vals = {v.strip().lower() for v in col_values(col)}
        return bool(vals) and vals <= (_TRUTHY | _FALSY)

    def is_short_enum(col: str) -> bool:
        vals = {v.strip().lower() for v in col_values(col)}
        return 2 <= len(vals) <= 6 and not (vals <= (_TRUTHY | _FALSY)) and avg_len(col) <= 30  # noqa: PLR2004

    bool_slots = [
        k
        for k in (
            "self_resolution",
            "requires_property_info",
            "can_report_fault",
            "requires_manual_support",
        )
        if k not in already_assigned
    ]
    bool_idx = 0

    rename: dict[str, str] = {}
    prose_cols: list[str] = []

    for header in headers:
        al = avg_len(header)
        ur = unique_ratio(header)

        if is_boolean_col(header):
            if bool_idx < len(bool_slots):
                rename[header] = bool_slots[bool_idx]
                bool_idx += 1
        elif is_short_enum(header) and "urgency_level" not in already_assigned | set(
            rename.values()
        ):
            rename[header] = "urgency_level"
        elif ur >= 0.6 and al > 15:  # noqa: PLR2004
            prose_cols.append(header)
        # else: store as-is (arbitrary metadata, left unaliased)

    # Assign prose columns to canonical keys:
    # - If example_query not yet taken: first prose = example_query, last (if >1) = info_to_collect
    # - If example_query already aliased: any remaining prose column = info_to_collect
    if prose_cols:
        if "example_query" not in already_assigned:
            rename[prose_cols[0]] = "example_query"
            if len(prose_cols) > 1 and "info_to_collect" not in already_assigned:
                rename[prose_cols[-1]] = "info_to_collect"
        elif "info_to_collect" not in already_assigned:
            rename[prose_cols[-1]] = "info_to_collect"

    return rename


def _detect_structural_columns_by_position(
    rows: list[dict[str, str]],
    headers: list[str],
) -> dict[str, str]:
    """Detect structural columns (code, level_1…N) by data pattern alone.

    Heuristics (entirely data-driven, no language knowledge required):

    Code column:
      - Short values (avg ≤ 20 chars) with high uniqueness (≥ 0.7) — typically
        dotted codes like "1.1.1" or alphanumeric like "W001".

    Level columns:
      - Values are short-to-medium category labels.
      - Parent levels repeat across rows (unique ratio < 0.5).
      - Leaf levels may be unique (unique ratio ≈ 1.0) but labels stay short
        (avg ≤ 25 chars — distinguishes "Vatten läcker från tak" from a full
        sentence like "Det droppar från taket i badrummet…").

    Metadata boundary — stop assigning levels when:
      - Boolean column (values match ja/nej/yes/no): clearly a flag field.
      - High unique ratio (≥ 0.6) AND avg length > 25 chars: this is a prose
        column (example queries, instructions) not a category label.
      - Avg length > 80 chars: long free-text, definitely metadata.
    """
    if not rows:
        return {}

    sample = rows[: min(30, len(rows))]

    def avg_len(col: str) -> float:
        vals = [row.get(col, "") for row in sample if row.get(col, "")]
        return sum(len(v) for v in vals) / max(len(vals), 1)

    def unique_ratio(col: str) -> float:
        vals = [row.get(col, "") for row in sample if row.get(col, "")]
        return len(set(vals)) / max(len(vals), 1) if vals else 1.0

    def looks_like_boolean(col: str) -> bool:
        vals = {row.get(col, "").strip().lower() for row in sample if row.get(col, "")}
        return bool(vals & (_TRUTHY | _FALSY))

    # Detection thresholds
    code_max_len = 20
    code_min_unique = 0.7
    level_max_len = 80
    prose_min_len = 25  # avg_len above this + high unique = prose sentence, not a label
    prose_min_unique = 0.6

    rename: dict[str, str] = {}
    level_idx = 0

    for header in headers:
        if header in rename:
            continue

        al = avg_len(header)
        ur = unique_ratio(header)

        # Boolean column → metadata, stop
        if looks_like_boolean(header):
            break

        # Prose column (unique long text per row) → metadata, stop
        if ur >= prose_min_unique and al > prose_min_len:
            break

        # Very long column → metadata, stop
        if al > level_max_len:
            break

        if level_idx == 0 and al <= code_max_len and ur >= code_min_unique:
            rename[header] = "code"
        else:
            level_idx += 1
            rename[header] = f"level_{level_idx}"

    return rename


def _parse_structured_file(content: bytes, filename: str) -> list[dict[str, str]]:  # noqa: PLR0912,PLR0915
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
            flat: dict[str, str] = {
                    "code": str(item.get("code", "") or ""),
                    **{f"level_{j + 1}": str(path[j]) if j < len(path) else "" for j in range(4)},
                }
            # Flatten metadata fields so _validate_rows can pick them up via header mapping.
            meta = item.get("metadata") or {}
            if isinstance(meta, dict):
                for k, v in meta.items():
                    flat[k] = str(v) if v is not None else ""
            rows.append(flat)
        return rows

    if fn.endswith(".csv"):
        try:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("latin-1")
            reader = csv.DictReader(io.StringIO(text))
            return [dict(r) for r in reader]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc

    if fn.endswith(".xlsx"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            if ws is None:
                raise HTTPException(status_code=400, detail="Empty Excel file")  # noqa: TRY301
            headers: list[str] = []
            xlsx_rows: list[dict[str, str]] = []
            header_found = False
            for row in ws.iter_rows(values_only=True):
                # Skip entirely blank rows — handles K2A-style files where
                # rows 1-3 are empty and the actual header is on row 4.
                cells = [c for c in row if c is not None and str(c).strip()]
                if not cells:
                    continue
                if not header_found:
                    headers = [
                        str(c).strip() if c is not None else f"col{j}" for j, c in enumerate(row)
                    ]
                    header_found = True
                else:
                    xlsx_rows.append(
                        dict(
                            zip(
                                headers,
                                (str(v).strip() if v is not None else "" for v in row),
                                strict=False,
                            )
                        )
                    )
            return xlsx_rows
        except ImportError as exc:
            raise HTTPException(
                status_code=500, detail="openpyxl not installed — cannot process Excel files"
            ) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}") from exc

    raise HTTPException(status_code=400, detail="Unsupported file type. Use .csv, .xlsx, or .json")


def _validate_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:  # noqa: PLR0912
    """Validate structured rows and return normalised node dicts. Raises on error.

    Each returned dict has the shape:
        {"code": str|None, "path": list[str], "metadata": dict|None}

    Metadata is extracted from any column that is not a structural field (code,
    level_1..5). Well-known headers are mapped to canonical key names; unknown
    headers are stored as-is. Boolean fields (JA/NEJ) are coerced to Python bools.
    """
    if len(rows) > MAX_NODES:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows ({len(rows)}). Maximum is {MAX_NODES}.",
        )

    # Discover all metadata columns once from the first row's keys.
    all_headers = list(rows[0].keys()) if rows else []
    metadata_headers: list[tuple[str, str]] = []  # (raw_header, canonical_key)
    for raw in all_headers:
        canonical = _canonical_header(raw)
        if canonical is not None:
            metadata_headers.append((raw, canonical))

    errors: list[str] = []
    codes_seen: set[str] = set()
    nodes: list[dict[str, Any]] = []

    for i, row in enumerate(rows, start=2):  # row 1 is header
        levels = [str(row.get(f"level_{j}", "") or "").strip() for j in range(1, 6)]
        # level_1 is required; level_2+ are optional (single-level root nodes are valid on export/re-import)
        if not levels[0]:
            errors.append(f"Row {i}: level_1 is required")
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

        # Extract metadata from all non-structural columns
        meta: dict[str, Any] = {}
        for raw_header, canonical_key in metadata_headers:
            raw_value = str(row.get(raw_header, "") or "").strip()
            if not raw_value:
                continue  # skip blank cells
            if canonical_key in _BOOLEAN_KEYS:
                meta[canonical_key] = _normalize_bool(raw_value)
            else:
                meta[canonical_key] = raw_value

        nodes.append({"code": code, "path": path, "metadata": meta or None})

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

    rows = _normalize_row_headers(_parse_structured_file(content, file.filename or "upload.csv"))
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
        item_metadata: dict[str, Any] | None = item.get("metadata")
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
                # Apply metadata to whatever node this row defines (leaf of this row's path).
                # Intermediate ancestors that appear as prefixes of other rows are skipped via
                # path_to_id, so their own row (processed first, depth-ordered) owns their metadata.
                node_metadata=item_metadata if is_leaf else None,
            )
            path_to_id[seg] = node.id
            nodes_to_add.append(node)

    for node in nodes_to_add:
        db.add(node)

    await db.commit()
    await _invalidate_tree_cache(workspace_id)
    logger.info(
        "category_tree_imported",
        workspace_id=str(workspace_id),
        tree_name=tree_name,
        node_count=len(nodes_to_add),
    )

    # Auto-enrich example_query in the background so FTS + LLM matching
    # benefit from representative caller terms without blocking the response.
    asyncio.create_task(  # noqa: RUF006
        _run_enrichment(workspace_id, tree_name, user.id)
    )

    return {"imported": len(nodes_to_add), "tree_name": tree_name, "status": "active"}


async def _invalidate_tree_cache(workspace_id: uuid.UUID) -> None:
    """Delete the prewarmed category tree Redis cache for a workspace.

    Called after any operation that changes the category tree so that the next
    session gets fresh node data (example_query, metadata, etc.) from the DB.
    """
    with contextlib.suppress(Exception):
        from app.db.redis import get_redis

        redis = await get_redis()
        await redis.delete(f"category_nodes:{workspace_id}")


async def _run_enrichment(
    workspace_id: uuid.UUID, tree_name: str, user_id: int, overwrite: bool = False
) -> None:
    """Fetch the OpenAI key and run example_query enrichment as a background task."""
    from app.services.category_discovery_worker import _get_openai_key
    from app.services.category_enrichment import enrich_example_queries

    openai_api_key = await _get_openai_key(user_id, workspace_id)
    if not openai_api_key:
        logger.warning(
            "enrich_skipped_no_openai_key",
            workspace_id=str(workspace_id),
            tree_name=tree_name,
        )
        return
    await enrich_example_queries(
        workspace_id=workspace_id,
        tree_name=tree_name,
        user_id=user_id,
        openai_api_key=openai_api_key,
        overwrite=overwrite,
    )


# ---------------------------------------------------------------------------
# Example query enrichment — enrich existing trees on demand
# ---------------------------------------------------------------------------


@router.post("/{workspace_id}/{tree_name}/enrich-examples", status_code=202)
@limiter.limit("10/minute")
async def enrich_examples(
    request: Request,
    workspace_id: uuid.UUID,
    tree_name: str,
    user: VerifiedUser,
    overwrite: bool = Query(
        False, description="Re-generate even for nodes that already have example_query"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Generate example_query for every node in the tree that is missing one.

    Runs as a background task — returns immediately.  Use overwrite=true to
    regenerate all nodes (e.g. after renaming labels or changing the tree language).
    """
    await _require_tree_access(workspace_id, tree_name, user, db)
    asyncio.create_task(  # noqa: RUF006
        _run_enrichment(workspace_id, tree_name, user.id, overwrite=overwrite)
    )
    return {"status": "enriching", "tree_name": tree_name}


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
    await _invalidate_tree_cache(workspace_id)
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
    await _invalidate_tree_cache(workspace_id)


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
        metadata=node.node_metadata,
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
    if body.metadata is not None:
        # Merge with existing metadata so unedited keys are preserved
        existing = node.node_metadata or {}
        node.node_metadata = {**existing, **body.metadata}
    if body.parent_id is not None:
        parent = await _get_node_or_404(body.parent_id, user.id, db)
        node.parent_id = parent.id
        node.depth = parent.depth + 1

    await db.commit()
    await _invalidate_tree_cache(workspace_id)
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
        metadata=node.node_metadata,
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
    await _invalidate_tree_cache(workspace_id)


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
        path = _build_path(matched_node, all_nodes)  # type: ignore[arg-type]

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

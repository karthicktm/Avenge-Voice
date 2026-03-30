"""Lookup API — collection and record CRUD, import/export, stats."""

import csv
import io
import json
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedUser
from app.core.limiter import limiter
from app.db.session import get_db
from app.models.lookup import LookupCollection, LookupRecord

router = APIRouter(prefix="/lookup", tags=["lookup"])

MAX_RECORDS_LIMIT = 500
MAX_IMPORT_ROWS = 10_000

DOMAIN_CHOICES = {"property", "faq", "product", "staff"}


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------


class CollectionCreate(BaseModel):
    name: str
    domain: str = "custom"
    use_case_tag: str | None = None
    source_type: str = "manual"
    field_schema: dict[str, Any] | None = None
    workspace_id: uuid.UUID | None = None


class CollectionUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    use_case_tag: str | None = None
    source_type: str | None = None
    field_schema: dict[str, Any] | None = None
    is_active: bool | None = None


class CollectionResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    user_id: int
    name: str
    domain: str
    use_case_tag: str | None
    source_type: str
    field_schema: dict[str, Any] | None
    is_active: bool
    record_count: int = 0

    model_config = {"from_attributes": True}


class RecordCreate(BaseModel):
    title: str
    data: dict[str, Any] = {}
    tags: list[str] | None = None


class RecordUpdate(BaseModel):
    title: str | None = None
    data: dict[str, Any] | None = None
    tags: list[str] | None = None


class RecordResponse(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    workspace_id: uuid.UUID | None
    user_id: int
    title: str
    data: dict[str, Any]
    tags: list[str] | None

    model_config = {"from_attributes": True}


class PaginatedRecords(BaseModel):
    records: list[RecordResponse]
    total: int
    limit: int
    skip: int


class StatsResponse(BaseModel):
    total_collections: int
    total_records: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scope(stmt: Any, user: Any, workspace_id: uuid.UUID | None) -> Any:
    """Scope a query to workspace or user."""
    if workspace_id:
        return stmt.where(LookupCollection.workspace_id == workspace_id)
    return stmt.where(LookupCollection.user_id == user.id)


async def _get_collection_or_404(
    collection_id: uuid.UUID,
    user: Any,
    db: AsyncSession,
) -> LookupCollection:
    result = await db.execute(select(LookupCollection).where(LookupCollection.id == collection_id))
    col = result.scalar_one_or_none()
    if col is None:
        raise HTTPException(status_code=404, detail="Collection not found")
    # Ownership check
    if col.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return col


# ---------------------------------------------------------------------------
# Collections
# ---------------------------------------------------------------------------


@router.get("/collections", response_model=list[CollectionResponse])
@limiter.limit("60/minute")
async def list_collections(
    request: Request,
    user: VerifiedUser,
    workspace_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[CollectionResponse]:
    """List all collections scoped to workspace or user."""
    stmt = select(LookupCollection)
    if workspace_id:
        # Include both workspace-scoped and user-scoped collections (same as tool execution)
        stmt = stmt.where(
            or_(
                LookupCollection.workspace_id == workspace_id,
                LookupCollection.user_id == user.id,
            )
        )
    else:
        stmt = stmt.where(LookupCollection.user_id == user.id)
    stmt = stmt.order_by(LookupCollection.created_at.desc())

    result = await db.execute(stmt)
    collections = result.scalars().all()

    # Fetch record counts in one query
    ids = [c.id for c in collections]
    counts: dict[uuid.UUID, int] = {}
    if ids:
        count_result = await db.execute(
            select(LookupRecord.collection_id, func.count(LookupRecord.id).label("n"))
            .where(LookupRecord.collection_id.in_(ids))
            .group_by(LookupRecord.collection_id)
        )
        for row in count_result.fetchall():
            counts[row.collection_id] = row.n

    return [
        CollectionResponse(
            id=c.id,
            workspace_id=c.workspace_id,
            user_id=c.user_id,
            name=c.name,
            domain=c.domain,
            use_case_tag=c.use_case_tag,
            source_type=c.source_type,
            field_schema=c.field_schema,
            is_active=c.is_active,
            record_count=counts.get(c.id, 0),
        )
        for c in collections
    ]


@router.post("/collections", response_model=CollectionResponse, status_code=201)
@limiter.limit("30/minute")
async def create_collection(
    request: Request,
    body: CollectionCreate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Create a new lookup collection."""
    col = LookupCollection(
        user_id=user.id,
        workspace_id=body.workspace_id,
        name=body.name,
        domain=body.domain,
        use_case_tag=body.use_case_tag,
        source_type=body.source_type,
        field_schema=body.field_schema,
    )
    db.add(col)
    await db.commit()
    await db.refresh(col)
    return CollectionResponse(
        id=col.id,
        workspace_id=col.workspace_id,
        user_id=col.user_id,
        name=col.name,
        domain=col.domain,
        use_case_tag=col.use_case_tag,
        source_type=col.source_type,
        field_schema=col.field_schema,
        is_active=col.is_active,
        record_count=0,
    )


@router.get("/collections/{collection_id}", response_model=CollectionResponse)
@limiter.limit("60/minute")
async def get_collection(
    request: Request,
    collection_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Get a single collection."""
    col = await _get_collection_or_404(collection_id, user, db)
    count_result = await db.execute(
        select(func.count(LookupRecord.id)).where(LookupRecord.collection_id == collection_id)
    )
    record_count = count_result.scalar() or 0
    return CollectionResponse(
        id=col.id,
        workspace_id=col.workspace_id,
        user_id=col.user_id,
        name=col.name,
        domain=col.domain,
        use_case_tag=col.use_case_tag,
        source_type=col.source_type,
        field_schema=col.field_schema,
        is_active=col.is_active,
        record_count=record_count,
    )


@router.put("/collections/{collection_id}", response_model=CollectionResponse)
@limiter.limit("30/minute")
async def update_collection(
    request: Request,
    collection_id: uuid.UUID,
    body: CollectionUpdate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> CollectionResponse:
    """Update a collection."""
    col = await _get_collection_or_404(collection_id, user, db)
    if body.name is not None:
        col.name = body.name
    if body.domain is not None:
        col.domain = body.domain
    if body.use_case_tag is not None:
        col.use_case_tag = body.use_case_tag
    if body.source_type is not None:
        col.source_type = body.source_type
    if body.field_schema is not None:
        col.field_schema = body.field_schema
    if body.is_active is not None:
        col.is_active = body.is_active
    await db.commit()
    await db.refresh(col)
    count_result = await db.execute(
        select(func.count(LookupRecord.id)).where(LookupRecord.collection_id == collection_id)
    )
    record_count = count_result.scalar() or 0
    return CollectionResponse(
        id=col.id,
        workspace_id=col.workspace_id,
        user_id=col.user_id,
        name=col.name,
        domain=col.domain,
        use_case_tag=col.use_case_tag,
        source_type=col.source_type,
        field_schema=col.field_schema,
        is_active=col.is_active,
        record_count=record_count,
    )


@router.delete("/collections/{collection_id}", status_code=204)
@limiter.limit("30/minute")
async def delete_collection(
    request: Request,
    collection_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a collection (cascades to records)."""
    col = await _get_collection_or_404(collection_id, user, db)
    await db.delete(col)
    await db.commit()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@router.get("/collections/{collection_id}/records", response_model=PaginatedRecords)
@limiter.limit("60/minute")
async def list_records(
    request: Request,
    collection_id: uuid.UUID,
    user: VerifiedUser,
    search: str | None = Query(None),
    limit: int = Query(50, ge=1, le=MAX_RECORDS_LIMIT),
    skip: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> PaginatedRecords:
    """List records for a collection, with optional keyword search."""
    await _get_collection_or_404(collection_id, user, db)

    base = select(LookupRecord).where(LookupRecord.collection_id == collection_id)
    count_base = select(func.count(LookupRecord.id)).where(
        LookupRecord.collection_id == collection_id
    )

    if search:
        base = base.where(LookupRecord.title.ilike(f"%{search}%"))
        count_base = count_base.where(LookupRecord.title.ilike(f"%{search}%"))

    total_result = await db.execute(count_base)
    total = total_result.scalar() or 0

    result = await db.execute(base.order_by(LookupRecord.title).offset(skip).limit(limit))
    records = result.scalars().all()

    return PaginatedRecords(
        records=[
            RecordResponse(
                id=r.id,
                collection_id=r.collection_id,
                workspace_id=r.workspace_id,
                user_id=r.user_id,
                title=r.title,
                data=r.data or {},
                tags=r.tags,
            )
            for r in records
        ],
        total=total,
        limit=limit,
        skip=skip,
    )


@router.post("/collections/{collection_id}/records", response_model=RecordResponse, status_code=201)
@limiter.limit("60/minute")
async def create_record(
    request: Request,
    collection_id: uuid.UUID,
    body: RecordCreate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> RecordResponse:
    """Create a single record in a collection."""
    col = await _get_collection_or_404(collection_id, user, db)
    rec = LookupRecord(
        collection_id=collection_id,
        workspace_id=col.workspace_id,
        user_id=user.id,
        title=body.title,
        data=body.data,
        tags=body.tags,
    )
    db.add(rec)
    await db.commit()
    await db.refresh(rec)
    return RecordResponse(
        id=rec.id,
        collection_id=rec.collection_id,
        workspace_id=rec.workspace_id,
        user_id=rec.user_id,
        title=rec.title,
        data=rec.data or {},
        tags=rec.tags,
    )


@router.put("/records/{record_id}", response_model=RecordResponse)
@limiter.limit("60/minute")
async def update_record(
    request: Request,
    record_id: uuid.UUID,
    body: RecordUpdate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> RecordResponse:
    """Update a record."""
    result = await db.execute(select(LookupRecord).where(LookupRecord.id == record_id))
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Record not found")
    if rec.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")

    if body.title is not None:
        rec.title = body.title
    if body.data is not None:
        rec.data = body.data
    if body.tags is not None:
        rec.tags = body.tags
    await db.commit()
    await db.refresh(rec)
    return RecordResponse(
        id=rec.id,
        collection_id=rec.collection_id,
        workspace_id=rec.workspace_id,
        user_id=rec.user_id,
        title=rec.title,
        data=rec.data or {},
        tags=rec.tags,
    )


@router.delete("/records/{record_id}", status_code=204)
@limiter.limit("60/minute")
async def delete_record(
    request: Request,
    record_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a record."""
    result = await db.execute(select(LookupRecord).where(LookupRecord.id == record_id))
    rec = result.scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="Record not found")
    if rec.user_id != user.id:
        raise HTTPException(status_code=403, detail="Access denied")
    await db.delete(rec)
    await db.commit()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@router.post("/collections/{collection_id}/import", status_code=200)
@limiter.limit("10/minute")
async def import_records(  # noqa: PLR0912, PLR0915
    request: Request,
    collection_id: uuid.UUID,
    user: VerifiedUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import records from CSV, Excel, or JSON file."""
    col = await _get_collection_or_404(collection_id, user, db)

    filename = (file.filename or "").lower()
    content = await file.read()

    rows: list[dict[str, Any]] = []

    if filename.endswith(".json"):
        try:
            parsed = json.loads(content.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
        if not isinstance(parsed, list):
            raise HTTPException(status_code=400, detail="JSON must be a list of objects")
        rows = parsed

    elif filename.endswith(".csv"):
        try:
            try:
                text_content = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text_content = content.decode("latin-1")
            reader = csv.DictReader(io.StringIO(text_content))
            rows = [dict(r) for r in reader]
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid CSV: {exc}") from exc

    elif filename.endswith(".xls") and not filename.endswith(".xlsx"):
        raise HTTPException(
            status_code=400,
            detail="Legacy .xls format is not supported. Please save as .xlsx (Excel 2007+) and re-upload.",
        )

    elif filename.endswith(".xlsx"):
        try:
            import openpyxl

            wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
            ws = wb.active
            if ws is None:
                raise HTTPException(status_code=400, detail="Empty Excel file")  # noqa: TRY301
            headers: list[str] = []
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
        except ImportError as exc:
            raise HTTPException(
                status_code=500,
                detail="openpyxl is not installed — cannot process Excel files",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid Excel file: {exc}") from exc
    else:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Use .csv, .xlsx, or .json.",
        )

    if len(rows) > MAX_IMPORT_ROWS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many rows ({len(rows)}). Maximum is {MAX_IMPORT_ROWS}.",
        )

    # Determine title field (first key, or 'title' if present)
    imported = 0
    skipped = 0
    for row in rows:
        if not row:
            skipped += 1
            continue
        # Use 'title' key if present, otherwise first key
        title_key = "title" if "title" in row else (next(iter(row), None))
        if title_key is None:
            skipped += 1
            continue
        title = str(row.get(title_key, "")).strip() or "Untitled"
        rec = LookupRecord(
            collection_id=collection_id,
            workspace_id=col.workspace_id,
            user_id=user.id,
            title=title,
            data=row,
        )
        db.add(rec)
        imported += 1

    if imported:
        await db.commit()

    return {"imported": imported, "skipped": skipped, "total": len(rows)}


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@router.get("/collections/{collection_id}/export")
@limiter.limit("20/minute")
async def export_records(
    request: Request,
    collection_id: uuid.UUID,
    user: VerifiedUser,
    fmt: str = Query("csv", alias="format", pattern="^(csv|json)$"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """Export all records as CSV or JSON."""
    col = await _get_collection_or_404(collection_id, user, db)

    result = await db.execute(
        select(LookupRecord)
        .where(LookupRecord.collection_id == collection_id)
        .order_by(LookupRecord.title)
    )
    records = result.scalars().all()

    safe_name = col.name.replace(" ", "_").replace("/", "-")

    if fmt == "json":
        payload = [{"title": r.title, **(r.data or {})} for r in records]

        def json_gen() -> Any:
            yield json.dumps(payload, ensure_ascii=False, indent=2)

        return StreamingResponse(
            json_gen(),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}.json"'},
        )

    # CSV
    if not records:
        headers_list: list[str] = ["title"]
    else:
        all_keys: set[str] = set()
        for r in records:
            all_keys.update((r.data or {}).keys())
        headers_list = ["title", *sorted(k for k in all_keys if k != "title")]

    def csv_gen() -> Any:
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=headers_list, extrasaction="ignore")
        writer.writeheader()
        for r in records:
            row_data = {"title": r.title, **(r.data or {})}
            writer.writerow(row_data)
        yield buf.getvalue()

    return StreamingResponse(
        csv_gen(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}.csv"'},
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=StatsResponse)
@limiter.limit("60/minute")
async def get_stats(
    request: Request,
    user: VerifiedUser,
    workspace_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> StatsResponse:
    """Collection and record counts for the current workspace."""
    if workspace_id:
        col_stmt = select(func.count(LookupCollection.id)).where(
            LookupCollection.workspace_id == workspace_id
        )
        rec_stmt = (
            select(func.count(LookupRecord.id))
            .join(LookupCollection, LookupRecord.collection_id == LookupCollection.id)
            .where(LookupCollection.workspace_id == workspace_id)
        )
    else:
        col_stmt = select(func.count(LookupCollection.id)).where(
            LookupCollection.user_id == user.id
        )
        rec_stmt = (
            select(func.count(LookupRecord.id))
            .join(LookupCollection, LookupRecord.collection_id == LookupCollection.id)
            .where(LookupCollection.user_id == user.id)
        )

    total_collections = (await db.execute(col_stmt)).scalar() or 0
    total_records = (await db.execute(rec_stmt)).scalar() or 0

    return StatsResponse(
        total_collections=total_collections,
        total_records=total_records,
    )

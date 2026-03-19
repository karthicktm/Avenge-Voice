"""Background worker for AI-powered category tree discovery."""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

import structlog

logger = structlog.get_logger()

MAX_SAMPLE_ITEMS = 500
MAX_RECURSION_DEPTH = 10


async def start_discovery_job(
    job_id: str,
    workspace_id: uuid.UUID,
    tree_name: str,
    user_id: int,
    hints: dict[str, Any],
    raw_content: bytes,
) -> None:
    """Run AI discovery: extract samples → call LLM → write draft nodes.

    Stores job status in Redis under key category_discovery:job:{job_id}.
    """
    from app.db.redis import get_redis
    from app.db.session import AsyncSessionLocal

    redis = await get_redis()
    log = logger.bind(component="category_discovery", job_id=job_id, tree_name=tree_name)

    async def _set_status(status: str, **extra: Any) -> None:
        await redis.set(
            f"category_discovery:job:{job_id}",
            json.dumps({"job_id": job_id, "status": status, **extra}),
            ex=3600,
        )

    await _set_status("running")

    try:
        # ------------------------------------------------------------------
        # 1. Extract sample items from raw content
        # ------------------------------------------------------------------
        samples = _extract_samples(raw_content, hints)
        log.info("samples_extracted", count=len(samples))
        await _set_status("running", step="generating", sample_count=len(samples))

        # ------------------------------------------------------------------
        # 2. Call LLM to build a category tree JSON
        # ------------------------------------------------------------------
        openai_api_key = await _get_openai_key(user_id, workspace_id)
        if not openai_api_key:
            await _set_status("failed", error="No OpenAI API key configured for this workspace")
            return

        tree_json = await _generate_tree(samples, hints, openai_api_key, log)
        if tree_json is None:
            await _set_status("failed", error="LLM failed to produce a valid category tree")
            return

        log.info("tree_generated", node_count=_count_nodes(tree_json))
        await _set_status("running", step="saving")

        # ------------------------------------------------------------------
        # 3. Write draft nodes to DB
        # ------------------------------------------------------------------
        async with AsyncSessionLocal() as db:
            node_count = await _write_draft_nodes(
                db=db,
                workspace_id=workspace_id,
                tree_name=tree_name,
                user_id=user_id,
                tree_json=tree_json,
            )

        await _set_status("completed", node_count=node_count)
        log.info("discovery_completed", node_count=node_count)

    except Exception as exc:
        log.exception("discovery_failed", error=str(exc))
        await _set_status("failed", error=str(exc))


def _extract_samples(raw_content: bytes, hints: dict[str, Any]) -> list[str]:  # noqa: PLR0912
    """Extract up to MAX_SAMPLE_ITEMS text items from raw content."""
    if not raw_content:
        return []

    items: list[str] = []

    # Try JSON
    try:
        parsed = json.loads(raw_content.decode("utf-8"))
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, str):
                    items.append(item)
                elif isinstance(item, dict):
                    items.extend(str(v) for v in item.values() if v)
        elif isinstance(parsed, dict):
            items.extend(str(v) for v in parsed.values() if v)
        if items:
            return items[:MAX_SAMPLE_ITEMS]
    except (json.JSONDecodeError, UnicodeDecodeError):
        pass

    # Try CSV
    try:
        text = raw_content.decode("utf-8-sig")
        reader = csv.reader(io.StringIO(text))
        for row in reader:
            items.extend(cell.strip() for cell in row if cell.strip())
            if len(items) >= MAX_SAMPLE_ITEMS:
                break
        if items:
            return items[:MAX_SAMPLE_ITEMS]
    except Exception:
        logger.debug("csv_parse_failed_trying_xlsx")

    # Try xlsx
    try:
        import openpyxl  # type: ignore[import-untyped]

        wb = openpyxl.load_workbook(io.BytesIO(raw_content), read_only=True, data_only=True)
        ws = wb.active
        if ws:
            for row in ws.iter_rows(values_only=True):
                items.extend(str(v).strip() for v in row if v is not None and str(v).strip())
                if len(items) >= MAX_SAMPLE_ITEMS:
                    break
        if items:
            return items[:MAX_SAMPLE_ITEMS]
    except Exception:
        logger.debug("xlsx_parse_failed_trying_plaintext")

    # Plain text fallback
    try:
        text = raw_content.decode("utf-8", errors="replace")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return lines[:MAX_SAMPLE_ITEMS]
    except Exception:
        return []


async def _get_openai_key(user_id: int, workspace_id: uuid.UUID) -> str | None:
    """Fetch OpenAI API key — workspace-scoped first, then user-level fallback.

    UserSettings.user_id stores a UUID derived from the int user id via user_id_to_uuid().
    """
    try:
        from sqlalchemy import and_, select

        from app.core.auth import user_id_to_uuid
        from app.db.session import AsyncSessionLocal
        from app.models.user_settings import UserSettings

        user_uuid = user_id_to_uuid(user_id)

        async with AsyncSessionLocal() as db:
            # Try workspace-specific key first
            result = await db.execute(
                select(UserSettings).where(
                    and_(
                        UserSettings.user_id == user_uuid,
                        UserSettings.workspace_id == workspace_id,
                    )
                )
            )
            settings = result.scalar_one_or_none()
            if settings and settings.openai_api_key:
                return settings.openai_api_key

            # Fallback to user-level key (workspace_id IS NULL)
            result = await db.execute(
                select(UserSettings).where(
                    and_(
                        UserSettings.user_id == user_uuid,
                        UserSettings.workspace_id.is_(None),
                    )
                )
            )
            settings = result.scalar_one_or_none()
            if settings and settings.openai_api_key:
                return settings.openai_api_key
    except Exception:
        logger.exception("failed_to_fetch_openai_key")
    return None


async def _generate_tree(
    samples: list[str],
    hints: dict[str, Any],
    openai_api_key: str,
    log: Any,
) -> list[dict[str, Any]] | None:
    """Call OpenAI to generate a structured category tree JSON.

    Returns a list of {label, children:[...]} objects, or None on failure.
    Retries once on JSON parse failure.
    """
    try:
        from openai import AsyncOpenAI
    except ImportError:
        log.warning("openai_not_installed")
        return None

    client = AsyncOpenAI(api_key=openai_api_key)

    label_hint = hints.get("label", "")
    max_depth = hints.get("max_depth", 3)
    approx_top = hints.get("approx_top_level", "ai_decides")

    sample_text = "\n".join(f"- {s}" for s in samples[:MAX_SAMPLE_ITEMS])
    top_level_hint = (
        f"Aim for approximately {approx_top} top-level categories."
        if approx_top != "ai_decides"
        else "Choose a natural number of top-level categories."
    )

    system_prompt = (
        "You are a taxonomy expert. Given a sample of items, build a hierarchical category tree. "
        f"Use at most {max_depth} levels of depth. {top_level_hint} "
        "Return ONLY valid JSON — an array of category objects with this recursive shape:\n"
        '{"label": "Category Name", "code": "optional_code", "children": [...]}\n'
        "No markdown, no explanation. Just the JSON array."
    )
    user_message = (
        f"{'Context: ' + label_hint + chr(10) if label_hint else ''}"
        f"Sample items to categorize:\n{sample_text}"
    )

    for attempt in range(2):
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=4096,
                temperature=0.2,
            )
            raw = (response.choices[0].message.content or "").strip()

            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```", 2)[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            parsed = json.loads(raw)
            if isinstance(parsed, list):
                log.info("tree_json_parsed", attempt=attempt, root_count=len(parsed))
                return parsed

            log.warning("unexpected_shape", attempt=attempt)
        except json.JSONDecodeError as exc:
            log.warning("json_parse_failed", attempt=attempt, error=str(exc))
        except Exception as exc:
            log.exception("llm_call_failed", attempt=attempt, error=str(exc))
            raise  # re-raise so the caller captures the real error message

    return None


def _count_nodes(tree_json: list[dict[str, Any]], depth: int = 0) -> int:
    total = 0
    for node in tree_json:
        total += 1
        children = node.get("children", [])
        if children and depth < MAX_RECURSION_DEPTH:
            total += _count_nodes(children, depth + 1)
    return total


async def _write_draft_nodes(
    db: Any,
    workspace_id: uuid.UUID,
    tree_name: str,
    user_id: int,
    tree_json: list[dict[str, Any]],
) -> int:
    """Recursively write draft CategoryTree nodes from the LLM JSON."""
    from sqlalchemy import delete

    from app.models.category_tree import CategoryTree

    # Remove any existing draft for this tree
    await db.execute(
        delete(CategoryTree).where(
            CategoryTree.workspace_id == workspace_id,
            CategoryTree.tree_name == tree_name,
            CategoryTree.user_id == user_id,
            CategoryTree.status == "draft",
        )
    )

    total = 0

    def _recurse(nodes: list[dict[str, Any]], parent_id: uuid.UUID | None, depth: int) -> None:
        nonlocal total
        for pos, node in enumerate(nodes):
            label = str(node.get("label", "")).strip()
            if not label:
                continue
            node_id = uuid.uuid4()
            db_node = CategoryTree(
                id=node_id,
                workspace_id=workspace_id,
                user_id=user_id,
                tree_name=tree_name,
                source_type="ai_generated",
                status="draft",
                code=node.get("code") or None,
                label=label,
                parent_id=parent_id,
                depth=depth,
                position=pos,
            )
            db.add(db_node)
            total += 1
            children = node.get("children", [])
            if children and depth < MAX_RECURSION_DEPTH:
                _recurse(children, node_id, depth + 1)

    _recurse(tree_json, None, 0)
    await db.commit()
    return total

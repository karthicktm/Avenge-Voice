# ruff: noqa: T201, PLR2004
"""Seed script: import an AMEDTEC Excel file as a category tree.

Usage:
    uv run python scripts/seed_amedtec.py \\
        --workspace-id <uuid> \\
        --file path/to/amedtec.xlsx \\
        [--tree-name amedtec_categories] \\
        [--dry-run]

The Excel file must follow the standard upload template (column names are
normalised via _WELL_KNOWN_HEADER_ALIASES).  Flat, single-level trees (depth=0
leaf nodes) are fully supported.

Columns recognised (case-insensitive, spaces → underscores):
  code, category_code           → code
  category_name, level_1        → level_1
  action_type                   → action_type
  transfer_target               → transfer_target
  email_target                  → email_target
  required_information          → required_information
  approved_script               → approved_script
  detection_signals_en          → detection_signals_en
  detection_signals_de          → detection_signals_de
  priority_order                → priority_order
  not_allowed_or_safety_boundary → safety_boundary
  example_query                 → example_query
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
import uuid
from pathlib import Path
from typing import Any

# Ensure the backend package is on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run(
    workspace_id: uuid.UUID,
    file_path: Path,
    tree_name: str,
    dry_run: bool,
) -> None:
    from app.api.category_trees import _parse_structured_file, _validate_rows
    from app.db.session import AsyncSessionLocal
    from app.models.category_tree import CategoryTree

    content = file_path.read_bytes()
    rows = _parse_structured_file(content, file_path.name)
    nodes = _validate_rows(rows)

    print(f"Parsed {len(nodes)} nodes from '{file_path.name}'")
    for n in nodes[:5]:
        print(f"  {n['path']} code={n['code']} meta={n.get('metadata')}")
    if len(nodes) > 5:
        print(f"  ... and {len(nodes) - 5} more")

    if dry_run:
        print("\n[dry-run] No changes written.")
        return

    # Build path → id mapping and persist
    path_to_id: dict[tuple[str, ...], uuid.UUID] = {}
    nodes_to_add: list[CategoryTree] = []

    for item in nodes:
        path: list[str] = item.get("path", [])
        code: str | None = item.get("code")
        item_metadata: dict[str, Any] | None = item.get("metadata")
        if not path:
            continue

        for depth in range(len(path)):
            seg = tuple(path[: depth + 1])
            if seg in path_to_id:
                continue
            is_leaf = depth == len(path) - 1
            parent_id = path_to_id.get(tuple(path[:depth])) if depth > 0 else None

            node_meta: dict[str, Any] | None = None
            if is_leaf and item_metadata:
                node_meta = {
                    k: v
                    for k, v in item_metadata.items()
                    if not re.match(r"^level_\d+_example_query$", k)
                }
                node_meta = node_meta or None

            node = CategoryTree(
                id=uuid.uuid4(),
                workspace_id=workspace_id,
                agent_id=None,
                user_id=None,  # seed script — no user
                tree_name=tree_name,
                source_type="structured_upload",
                status="active",
                code=code if is_leaf else None,
                label=path[depth],
                parent_id=parent_id,
                depth=depth,
                position=len([k for k in path_to_id if len(k) == depth + 1]),
                node_metadata=node_meta,
            )
            path_to_id[seg] = node.id
            nodes_to_add.append(node)

    async with AsyncSessionLocal() as db:
        from sqlalchemy import delete

        await db.execute(
            delete(CategoryTree).where(
                CategoryTree.workspace_id == workspace_id,
                CategoryTree.tree_name == tree_name,
            )
        )
        for node in nodes_to_add:
            db.add(node)
        await db.commit()

    print(
        f"\nImported {len(nodes_to_add)} nodes into tree '{tree_name}' (workspace {workspace_id})"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed AMEDTEC category tree from Excel")
    parser.add_argument("--workspace-id", required=True, help="Target workspace UUID")
    parser.add_argument("--file", required=True, help="Path to Excel/CSV file")
    parser.add_argument("--tree-name", default="amedtec_categories", help="Tree name to create")
    parser.add_argument("--dry-run", action="store_true", help="Parse only, no DB writes")
    args = parser.parse_args()

    workspace_id = uuid.UUID(args.workspace_id)
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"ERROR: file not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    asyncio.run(_run(workspace_id, file_path, args.tree_name, args.dry_run))


if __name__ == "__main__":
    main()

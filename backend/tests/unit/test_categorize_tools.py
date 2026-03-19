"""Unit tests for the categorization module (pure logic, no DB)."""

import uuid

import pytest

from app.api.category_trees import _validate_rows


class TestValidateRows:
    """Tests for structured upload validation logic."""

    def test_valid_two_level(self) -> None:
        rows = [
            {"code": "A1", "level_1": "Water", "level_2": "Bathroom", "level_3": "", "level_4": ""}
        ]
        result = _validate_rows(rows)
        assert len(result) == 1
        assert result[0]["path"] == ["Water", "Bathroom"]
        assert result[0]["code"] == "A1"

    def test_valid_three_level(self) -> None:
        rows = [
            {
                "code": "",
                "level_1": "Heat",
                "level_2": "Radiator",
                "level_3": "Noisy",
                "level_4": "",
            }
        ]
        result = _validate_rows(rows)
        assert result[0]["path"] == ["Heat", "Radiator", "Noisy"]
        assert result[0]["code"] is None

    def test_missing_level_1_raises(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_rows([{"code": "", "level_1": "", "level_2": "Bath", "level_3": ""}])
        assert exc_info.value.status_code == 422

    def test_missing_level_2_raises(self) -> None:
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_rows([{"code": "", "level_1": "Water", "level_2": "", "level_3": ""}])
        assert exc_info.value.status_code == 422

    def test_duplicate_code_raises(self) -> None:
        from fastapi import HTTPException

        rows = [
            {"code": "X1", "level_1": "A", "level_2": "B", "level_3": ""},
            {"code": "X1", "level_1": "C", "level_2": "D", "level_3": ""},
        ]
        with pytest.raises(HTTPException) as exc_info:
            _validate_rows(rows)
        assert exc_info.value.status_code == 422

    def test_too_many_rows_raises(self) -> None:
        from fastapi import HTTPException

        from app.api.category_trees import MAX_NODES

        rows = [
            {"code": str(i), "level_1": "A", "level_2": "B", "level_3": ""}
            for i in range(MAX_NODES + 1)
        ]
        with pytest.raises(HTTPException) as exc_info:
            _validate_rows(rows)
        assert exc_info.value.status_code == 400

    def test_empty_code_becomes_none(self) -> None:
        rows = [{"code": "   ", "level_1": "A", "level_2": "B", "level_3": ""}]
        result = _validate_rows(rows)
        assert result[0]["code"] is None

    def test_multiple_valid_rows(self) -> None:
        rows = [
            {"code": "W1", "level_1": "Water", "level_2": "Bath", "level_3": "Tap"},
            {"code": "H1", "level_1": "Heat", "level_2": "Radiator", "level_3": ""},
        ]
        result = _validate_rows(rows)
        assert len(result) == 2
        assert result[0]["path"] == ["Water", "Bath", "Tap"]
        assert result[1]["path"] == ["Heat", "Radiator"]


class TestBuildPath:
    """Tests for the _build_path helper."""

    def test_single_root_node(self) -> None:
        from app.api.category_trees import _build_path
        from app.models.category_tree import CategoryTree

        root_id = uuid.uuid4()
        root = CategoryTree(id=root_id, label="Water", parent_id=None, depth=0)
        result = _build_path(root, {root_id: root})
        assert result == ["Water"]

    def test_three_level_path(self) -> None:
        from app.api.category_trees import _build_path
        from app.models.category_tree import CategoryTree

        root_id = uuid.uuid4()
        mid_id = uuid.uuid4()
        leaf_id = uuid.uuid4()

        root = CategoryTree(id=root_id, label="Water", parent_id=None, depth=0)
        mid = CategoryTree(id=mid_id, label="Bathroom", parent_id=root_id, depth=1)
        leaf = CategoryTree(id=leaf_id, label="Tap", parent_id=mid_id, depth=2)

        all_nodes = {root_id: root, mid_id: mid, leaf_id: leaf}
        result = _build_path(leaf, all_nodes)
        assert result == ["Water", "Bathroom", "Tap"]


class TestExtractSamples:
    """Tests for the AI discovery sample extractor."""

    def test_json_array_of_strings(self) -> None:
        import json

        from app.services.category_discovery_worker import _extract_samples

        content = json.dumps(["dripping tap", "broken boiler", "cracked tile"]).encode()
        result = _extract_samples(content, {})
        assert result == ["dripping tap", "broken boiler", "cracked tile"]

    def test_csv_rows(self) -> None:
        from app.services.category_discovery_worker import _extract_samples

        content = b"issue\ndripping tap\nbroken boiler\n"
        result = _extract_samples(content, {})
        assert "dripping tap" in result
        assert "broken boiler" in result

    def test_plain_text_fallback(self) -> None:
        from app.services.category_discovery_worker import _extract_samples

        content = b"dripping tap\nbroken boiler\ncracked tile"
        result = _extract_samples(content, {})
        assert len(result) == 3

    def test_empty_content_returns_empty(self) -> None:
        from app.services.category_discovery_worker import _extract_samples

        result = _extract_samples(b"", {})
        assert result == []

    def test_sample_limit_respected(self) -> None:
        import json

        from app.services.category_discovery_worker import MAX_SAMPLE_ITEMS, _extract_samples

        items = [f"item {i}" for i in range(MAX_SAMPLE_ITEMS + 100)]
        content = json.dumps(items).encode()
        result = _extract_samples(content, {})
        assert len(result) == MAX_SAMPLE_ITEMS

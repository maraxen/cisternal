"""AC-M8 / M1.5: XpeririAdapter unit tests."""

from __future__ import annotations

import json

from cisternal.adapters.base import XpeririAdapter


class TestXpeririAdapterShape:
    def test_shape_ok_passthrough_str(self) -> None:
        adapter = XpeririAdapter()
        raw = '{"experts": []}'
        assert adapter.shape_ok("expert_list", raw) == raw

    def test_shape_ok_serializes_dict(self) -> None:
        adapter = XpeririAdapter()
        payload = {"experts": [{"id": "a", "name": "A", "description": ""}]}
        result = adapter.shape_ok("expert_list", payload)
        assert isinstance(result, str)
        assert json.loads(result) == payload

    def test_shape_error_json_string(self) -> None:
        adapter = XpeririAdapter()
        result = adapter.shape_error("expert_resolve", ValueError("not found"))
        parsed = json.loads(result)
        assert parsed["ok"] is False
        assert "not found" in parsed["error"]

    def test_allowed_names(self) -> None:
        adapter = XpeririAdapter()
        assert adapter.ALLOWED_NAMES == frozenset(
            {"mcp.call_start", "mcp.call_end", "mcp.tool_error"}
        )

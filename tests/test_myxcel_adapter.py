"""AC-M9 / M1.5: MyxcelAdapter unit tests."""

from __future__ import annotations

from cisternal.adapters.base import MyxcelAdapter


class TestMyxcelAdapterShape:
    def test_shape_ok_passthrough_dict(self) -> None:
        adapter = MyxcelAdapter()
        payload = {"remote": "hpc", "project": "foo", "mounted": True}
        assert adapter.shape_ok("mount_project", payload) is payload

    def test_shape_ok_passthrough_list(self) -> None:
        adapter = MyxcelAdapter()
        payload = [{"remote": "hpc", "mounted": True}]
        assert adapter.shape_ok("mount_status", payload) is payload

    def test_shape_ok_in_band_error_dict(self) -> None:
        adapter = MyxcelAdapter()
        payload = {"error": "FileNotFoundError", "message": "profile missing"}
        assert adapter.shape_ok("mount_project", payload) == payload

    def test_shape_ok_wraps_scalar(self) -> None:
        adapter = MyxcelAdapter()
        assert adapter.shape_ok("ping", 42) == {"result": 42}

    def test_shape_error_matches_tool_error(self) -> None:
        adapter = MyxcelAdapter()
        result = adapter.shape_error("mount_project", ValueError("profile missing"))
        assert result == {"error": "ValueError", "message": "profile missing"}

    def test_allowed_names(self) -> None:
        adapter = MyxcelAdapter()
        assert adapter.ALLOWED_NAMES == frozenset(
            {"mcp.call_start", "mcp.call_end", "mcp.tool_error"}
        )

from toy_cisternal.registry import tool, clear_registry, snapshot


def setup_function():
    clear_registry()


def test_bare_tool_registers_under_fn_name():
    @tool
    def my_fn(x: int) -> int:
        return x

    assert "my_fn" in snapshot()


def test_name_override_stores_under_given_name():
    @tool(name="widgets")
    def mcp_widgets_tool(x: int) -> int:
        return x

    snap = snapshot()
    assert "widgets" in snap
    assert snap["widgets"].fn is mcp_widgets_tool

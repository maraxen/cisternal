from toy_cisternal.registry import tool, clear_registry
from toy_cisternal.wire import ToyApp, wire


def setup_function():
    clear_registry()


def test_wire_returns_registered_names():
    @tool(name="widgets")
    def mcp_widgets_tool(x: int) -> int:
        return x

    app = ToyApp("test")
    wired = wire(app, expected=["widgets"])
    assert "widgets" in wired


def test_wire_raises_on_missing_expected():
    app = ToyApp("test")
    try:
        wire(app, expected=["nonexistent"])
        assert False, "expected ValueError"
    except ValueError as e:
        assert "nonexistent" in str(e)

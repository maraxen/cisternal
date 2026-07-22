from toy_consumer.app import _WIRED


def test_expected_tools_wired():
    """Checks wire()'s own return value -- NOT what the transport actually exposes."""
    assert "list_widgets" in _WIRED
    assert "get_widget" in _WIRED

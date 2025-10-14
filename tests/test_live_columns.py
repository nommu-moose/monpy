import pytest


pytestmark = [pytest.mark.live]


def test_columns_available(live_env):
    cols = live_env["cols"]
    # Core columns should exist
    assert cols["text"].get("id")
    assert cols["numbers"].get("id")
    assert cols["status"].get("id")
    assert cols["file"].get("id")
    assert cols["doc"].get("id")
    # Optional columns may not be available on all accounts
    if cols.get("connect"):
        assert cols["connect"].get("id")
    if cols.get("location"):
        assert cols["location"].get("id")



import pytest


pytestmark = [pytest.mark.live, pytest.mark.subitems]


def test_subitem_basic(live_env, client_live):
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]

    item = bd1.create_item(group_id=g1["id"], item_name="has-child")
    sub_raw = client_live.create_subitem(item.id, item_name="child")
    si = live_env["sess"].subitem(sub_raw["id"])  # OO wrapper
    si.values.text = "sub hello"
    si.save()
    svals = client_live.get_subitem_values(si.id, include_board=True)
    assert svals.get("board", {}).get("id")



import pytest


pytestmark = [pytest.mark.live, pytest.mark.relations]


def test_connect_boards_relation(live_env):
    cols = live_env["cols"]
    if not (cols.get("connect") and cols["connect"].get("id")):
        pytest.skip("connect_boards unsupported for this token/account")

    bd2 = live_env["bd2"]
    g2 = live_env["g2"]
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]

    target = bd2.create_item(group_id=g2["id"], item_name="target")
    item = bd1.create_item(group_id=g1["id"], item_name="rel-main")
    bd1.refresh()  # ensure col cache
    # Use normalized attribute name (lowercase) derived from title "Related"
    item.set_connected_items(column_attr="related", linked_item_ids=[target.id])
    assert int(target.id) in {int(i) for i in (item.values.related or [])}



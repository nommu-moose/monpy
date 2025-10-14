from datetime import date
import pytest


pytestmark = [pytest.mark.live]


def test_item_crud_and_values(live_env):
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]
    cols = live_env["cols"]

    vals = {
        cols["text"]["id"]: "hello",
        cols["numbers"]["id"]: 42,
        cols["status"]["id"]: {"index": 1},
        cols["date"]["id"]: {"date": date.today().isoformat()},
    }
    item = bd1.create_item(group_id=g1["id"], item_name="basic", values=vals)
    assert item.values.text == "hello"
    assert isinstance(item.values.status, (str, dict))

    with live_env["sess"].transaction():
        item.values.text = "world"
    assert item.values.text == "world"



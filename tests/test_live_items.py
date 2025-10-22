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


def test_assign_real_user_to_person_column(live_env, client_live):
    users = client_live.list_users()
    if not users:
        pytest.skip("No users found in the account to test person assignment.")

    user_to_assign = users[0]
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]
    people_col_id = live_env["cols"]["people"]["id"]

    item = bd1.create_item(group_id=g1["id"], item_name="user-assignment-test")

    with live_env["sess"].transaction():
        # The OO layer should handle the complex dict structure for us
        item.values.assignee = user_to_assign["id"]

    # Verify the value was set correctly by fetching it again
    item.refresh()

    # The raw value from the API for a person column is a list of dicts
    person_value = item.values.assignee
    assert person_value is not None
    assert isinstance(person_value, list)
    assert len(person_value) == 1
    assert person_value[0] == int(user_to_assign["id"])



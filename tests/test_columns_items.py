import json
import types

import pytest

from monpy import MondayClient, MondayAPIError


def _fake_ok(data):
    return types.SimpleNamespace(json=lambda: {"data": data}, status_code=200)


def test_get_columns_augments_settings(monkeypatch):
    c = MondayClient(token="t")
    def post(*args, **kwargs):
        return _fake_ok({
            "boards": [{
                "columns": [
                    {"id": "col1", "title": "Links", "type": "connect_boards", "settings_str": json.dumps({"boardIds": [1, 2]})},
                    {"id": "col2", "title": "Mirror", "type": "mirror", "settings_str": json.dumps({"displayed_linked_columns": {"123": "456"}})},
                ]
            }]
        })
    c._session = types.SimpleNamespace(post=post, headers={})
    cols = c.get_columns("b1")
    assert cols[0]["connected_board_ids"] == ["1", "2"]
    assert cols[1]["linked_column_dict"] == {"123": "456"}


def test_list_items_pagination(monkeypatch):
    c = MondayClient(token="t")
    # first page
    def post1(*a, **k):
        return _fake_ok({
            "boards": [{"items_page": {"cursor": "next", "items": [{"id": "1", "name": "A"}]}}]
        })
    # second (last) page
    def post2(*a, **k):
        return _fake_ok({
            "boards": [{"items_page": {"cursor": None, "items": [{"id": "2", "name": "B"}]}}]
        })
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return post1() if calls["n"] == 1 else post2()
    c._session = types.SimpleNamespace(post=post, headers={})

    items, cur = c.list_items("b1", limit=600)
    assert [i["id"] for i in items] == ["1", "2"]
    assert cur is None


def test_get_item_values_auto_json_decode(monkeypatch):
    c = MondayClient(token="t")
    payload = {"items": [{
        "id": "10",
        "column_values": [
            {"id": "c", "value": json.dumps({"x": 1}), "text": "t", "type": "text"}
        ]
    }]}
    c._session = types.SimpleNamespace(post=lambda *a, **k: _fake_ok(payload), headers={})
    it = c.get_item_values("10")
    assert it["column_values"][0]["value"] == {"x": 1}


def test_update_item_values_coerces_text_and_raises_on_empty(monkeypatch):
    c = MondayClient(token="t")
    monkeypatch.setattr(c, "get_columns", lambda bid, **k: [{"id": "t1", "type": "text"}])
    # furnish cache
    c._get_text_column_ids("b")
    captured = {}
    def mutation(query, vars, **k):
        captured["vars"] = vars
        return {"change_multiple_column_values": {"id": "1"}}
    c.mutation = mutation
    with pytest.raises(ValueError):
        c.update_item_values("b", "i", column_values={})
    c.update_item_values("b", "i", column_values={"t1": 123, "x": 5})
    sent = json.loads(captured["vars"]["vals"])
    assert sent["t1"] == "123" and sent["x"] == 5


def test_safe_update_item_values_filters_known_errors(monkeypatch, caplog):
    c = MondayClient(token="t")
    state = {"calls": 0, "payload": None}

    def update(board_id, item_id, *, column_values):
        if state["calls"] == 0:
            state["calls"] += 1
            raise MondayAPIError("gql", errors=[
                {"message": "Unable to assign person with id ...", "extensions": {"error_data": {"column_id": "p"}}},
                {"message": "", "extensions": {"error_data": {"column_validation_error_code": "linkedItemsLimitExceeded", "column_id": "rel"}}},
            ])
        state["calls"] += 1
        state["payload"] = column_values

    c.update_item_values = update
    c.safe_update_item_values("b", "i", column_values={"p": 1, "rel": [1], "ok": "v"})
    assert state["calls"] == 2
    assert state["payload"] == {"ok": "v"}



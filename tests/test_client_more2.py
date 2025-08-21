import json
import types
import pytest

from importlib.metadata import PackageNotFoundError

from monpy import MondayClient, MondayAPIError


class _Resp:
    def __init__(self, status_code=200, json_payload=None, text=""):
        self.status_code = status_code
        self._json = json_payload
        self.text = text

    def json(self):
        return self._json or {}


def test_request_unrecoverable_failure(monkeypatch):
    c = MondayClient(token="t", max_retries=1, backoff=0)
    # 429 then 429 -> exhaust loop
    c._session = types.SimpleNamespace(post=lambda *a, **k: _Resp(status_code=429), headers={})
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    with pytest.raises(MondayAPIError) as ei:
        c.query("q")
    # Expect terminal HTTP error after final retry
    assert "HTTP 429" in str(ei.value)


def test_user_agent_fallback(monkeypatch):
    c = MondayClient(token="t")
    # Force PackageNotFoundError
    import monpy.client as mc
    monkeypatch.setattr(mc, "pkg_version", lambda *a, **k: (_ for _ in ()).throw(PackageNotFoundError()))
    ua = c._user_agent()
    assert ua.startswith("monpy/")


def test_workspace_helpers(monkeypatch):
    c = MondayClient(token="t")
    # get_workspace not found
    c.query = lambda q, v: {"workspaces": []}
    with pytest.raises(MondayAPIError):
        c.get_workspace("w")
    # create/update/delete path
    c.mutation = lambda q, v: {"create_workspace": {"id": "w", "name": v["name"], "kind": v["kind"], "description": v["desc"]}}
    ws = c.create_workspace(name="N", kind="open", description="D")
    assert ws["name"] == "N"
    c.mutation = lambda q, v: {"update_workspace": {"id": v["id"], "name": v["attrs"]["name"]}}
    out = c.update_workspace("w", name="N2")
    assert out["name"] == "N2"
    deleted = {"id": None}
    c.mutation = lambda q, v: deleted.update(v) or {"delete_workspace": {"id": v["id"]}}
    c.delete_workspace("w")
    assert deleted["id"] == "w"


def test_get_workspace_for_board_failure(monkeypatch):
    c = MondayClient(token="t")
    c.query = lambda q, v: {"boards": []}
    with pytest.raises(MondayAPIError):
        c.get_workspace_for_board("b")


def test_columns_parse_settings_false_and_board_not_found(monkeypatch):
    c = MondayClient(token="t")
    # board not found
    c.query = lambda q, v: {"boards": []}
    with pytest.raises(MondayAPIError):
        c.get_columns("b")
    # parse_settings=False does not add settings
    c.query = lambda q, v: {"boards": [{"columns": [{"id": "c", "title": "T", "type": "text", "settings_str": json.dumps({"x": 1})}]}]}
    cols = c.get_columns("b", parse_settings=False)
    assert "settings" not in cols[0]


def test_get_column_parse_settings_false(monkeypatch):
    c = MondayClient(token="t")
    c.query = lambda q, v: {"boards": [{"columns": [{"id": "c", "title": "T", "type": "text", "settings_str": json.dumps({"x": 1})}]}]}
    col = c.get_column("b", "c", parse_settings=False)
    assert "settings" not in col


def test_get_item_values_not_found_and_no_json_parse(monkeypatch):
    c = MondayClient(token="t")
    c.query = lambda q, v: {"items": []}
    with pytest.raises(MondayAPIError):
        c.get_item_values("i")
    c.query = lambda q, v: {"items": [{"id": "i", "column_values": [{"id": "x", "value": json.dumps({"a": 1}), "text": "t", "type": "text"}]}]}
    it = c.get_item_values("i", parse_json_values=False)
    assert isinstance(it["column_values"][0]["value"], str)


def test_safe_update_item_values_reraises(monkeypatch):
    c = MondayClient(token="t")
    def boom(*a, **k):
        raise MondayAPIError("other problem", errors=[{"message": "random"}])
    c.update_item_values = boom
    with pytest.raises(MondayAPIError):
        c.safe_update_item_values("b", "i", column_values={"x": 1})


def test_set_connected_subitems_and_subitem_helpers(monkeypatch):
    c = MondayClient(token="t")
    c._get_board_id_for_subitem = lambda sid: "B"
    called = {"vals": None}
    def upd(sid, *, column_values, board_id=None):
        called["vals"] = column_values
    c.update_subitem_values = upd
    c.set_connected_subitems("s", column_id="rel", linked_item_ids=[1, 2])
    assert called["vals"]["rel"]["item_ids"] == [1, 2]

    # create_subitem
    c.mutation = lambda q, v: {"create_subitem": {"id": "S"}}
    s = c.create_subitem("p", item_name="N")
    assert s["id"] == "S"

    # update_subitem_single_column with inferred board
    c._get_board_id_for_subitem = lambda sid: "BB"
    captured = {}
    def mut(q, v):
        captured.update(v)
        return {"change_column_value": {"id": "ok"}}
    c.mutation = mut
    c.update_subitem_single_column("s", column_id="c", value={"x": 1})
    assert captured["board"] == "BB"


def test_delete_doc_and_create_block_with_after(monkeypatch):
    c = MondayClient(token="t")
    del_vars = {}
    c.mutation = lambda q, v: del_vars.update(v) or {"delete_board": {"id": v["id"]}}
    c.delete_doc("d")
    assert del_vars["id"] == "d"

    blk_vars = {}
    def mut(q, v):
        blk_vars.update(v)
        return {"create_doc_block": {"id": "blk"}}
    c.mutation = mut
    c.create_doc_block("doc", block_type="normal_text", content={"deltaFormat": []}, after_block_id="after")
    assert blk_vars.get("after") == "after"


def test_items_move_duplicate_and_groups(monkeypatch):
    c = MondayClient(token="t")

    # items_by_column_values
    def q1(q, v):
        assert "items_by_column_values" in q and v["bid"] == "B" and v["col"] == "status"
        return {"items_by_column_values": [{"id": "1", "name": "N"}]}
    c.query = q1
    items = c.items_by_column_values("B", column_id="status", column_value={"index": 1})
    assert items and items[0]["id"] == "1"

    # duplicate_item
    def m1(q, v):
        assert "duplicate_item" in q and v["id"] == "I"
        return {"duplicate_item": {"id": "NI"}}
    c.mutation = m1
    dup = c.duplicate_item("I", with_updates=False, with_assets=False, target_board_id="B2", target_group_id="g")
    assert dup["id"] == "NI"

    # move_item_to_group and move_item_to_board
    moved = {}
    def m2(q, v):
        if "move_item_to_group" in q:
            moved.update(v)
            return {"move_item_to_group": {"id": v["id"]}}
        return {"move_item_to_board": {"id": v["id"]}}
    c.mutation = m2
    c.move_item_to_group("I", group_id="gg")
    assert moved["gid"] == "gg"
    res = c.move_item_to_board("I", board_id="B3", group_id="gg2")
    assert res["id"] == "I"

    # groups: list/create/rename/archive/delete
    def q2(q, v):
        return {"boards": [{"groups": [{"id": "g1", "title": "T", "archived": False}]}]}
    c.query = q2
    groups = c.list_groups("B")
    assert groups and groups[0]["id"] == "g1"

    def m3(q, v):
        if "create_group" in q:
            return {"create_group": {"id": "g2", "title": v["title"], "archived": False}}
        if "change_group_title" in q:
            return {"change_group_title": {"id": "g2"}}
        if "archive_group" in q:
            return {"archive_group": {"id": "g2"}}
        if "delete_group" in q:
            return {"delete_group": {"id": "g2"}}
        return {}
    c.mutation = m3
    g = c.create_group("B", title="New")
    assert g["id"] == "g2"
    c.rename_group("B", "g2", title="Newer")
    c.archive_group("B", "g2")
    c.delete_group("B", "g2")

    # board owners & role listing
    c.query = lambda q, v: {"boards": [{"owners": [{"id": "9"}], "subscribers": [{"id": "8"}]}]}
    roles = c.list_board_members_by_role("B")
    assert roles["owners"][0]["id"] == "9"
    assert roles["subscribers"][0]["id"] == "8"

    # add owners and set roles
    added = {}
    def mut2(q, v):
        added.setdefault("calls", []).append({"q": q, "v": v})
        return {"add_subscribers_to_board": {"id": v.get("bid")}}
    c.mutation = mut2
    c.add_board_owners("B", [9])
    c.set_board_subscriber_roles("B", {7: "subscriber", 8: "owner"})


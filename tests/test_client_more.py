import json

import pytest

from monpy import MondayClient, MondayAPIError


def test_augment_column_meta_variants():
    c = MondayClient(token="t")
    # invalid JSON settings_str
    col = {"id": "x", "type": "numbers", "settings_str": "{not json"}
    c._augment_column_meta(col)
    assert col["settings"] == {}
    # connect boards from singular key (use list to avoid scalar iteration issues)
    col2 = {"id": "y", "type": "connect_boards", "settings_str": json.dumps({"board_id": [7]})}
    c._augment_column_meta(col2)
    assert col2["connected_board_ids"] == ["7"]
    # prefer allowed_board_ids over settings
    col3 = {"id": "z", "type": "connect_boards", "allowed_board_ids": [9], "settings_str": json.dumps({"boardIds": [1, 2]})}
    c._augment_column_meta(col3)
    assert col3["connected_board_ids"] == ["9"]


def test_get_column_not_found_raises(monkeypatch):
    c = MondayClient(token="t")
    # query returns board with empty columns
    c.query = lambda q, v: {"boards": [{"columns": []}]}
    with pytest.raises(MondayAPIError):
        c.get_column("b", "c")


def test_list_boards_vars_and_filters(monkeypatch):
    c = MondayClient(token="t")
    captured = {}

    def fake_query(q, vars):
        captured.update(vars)
        return {"boards": []}

    c.query = fake_query
    c.list_boards(limit=10, workspace_id="w1", state=["active", "archived"], fields=("id",))
    assert captured["limit"] == 10 and captured["wids"] == ["w1"] and captured["st"] == ["active", "archived"]


def test_list_items_vars_cursor_and_state(monkeypatch):
    c = MondayClient(token="t")
    captured = {}
    c.query = lambda q, v: captured.update(v) or {"boards": [{"items_page": {"cursor": None, "items": []}}]}
    c.list_items("b", limit=100, state=None, cursor="abc")
    assert captured.get("cur") == "abc" and "st" not in captured


def test_get_items_values_options_and_empty_list(monkeypatch):
    c = MondayClient(token="t")
    # empty input short-circuit
    assert c.get_items_values([]) == []
    # include_board and column_ids with no JSON parsing
    c.query = lambda q, v: {"items": [{"id": "1", "board": {"id": "b"}, "column_values": [{"id": "x", "value": json.dumps({"a": 1}), "text": "t", "type": "text"}]}]}
    items = c.get_items_values(["1"], include_board=True, column_ids=["x"], parse_json_values=False)
    # value should remain a JSON string
    assert isinstance(items[0]["column_values"][0]["value"], str)


def test_create_and_delete_and_single_column(monkeypatch):
    c = MondayClient(token="t")
    c.mutation = lambda q, v: {"create_item": {"id": "42"}}
    got = c.create_item("b", group_id="g", item_name="n")
    assert got == {"id": "42"}

    captured = {}
    def mut(q, v):
        captured.update(v)
        return {"change_column_value": {"id": "1"}}
    c.mutation = mut
    c.update_item_single_column("b", "i", column_id="c", value={"k": 1})
    assert isinstance(captured["val"], str) and json.loads(captured["val"]) == {"k": 1}

    # delete item
    del_vars = {}
    c.mutation = lambda q, v: del_vars.update(v) or {"delete_item": {"id": "i"}}
    c.delete_item("i")
    assert del_vars["id"] == "i"


def test_subitems_helpers_and_cache(monkeypatch):
    c = MondayClient(token="t")
    # list_subitems not found
    c.query = lambda q, v: {"items": []}
    with pytest.raises(MondayAPIError):
        c.list_subitems("p")

    # get_subitem_values include blocks
    c.query = lambda q, v: {"items": [{"id": "s", "board": {"id": "b"}, "parent_item": {"id": "p"}, "column_values": []}]}
    s = c.get_subitem_values("s", include_board=True, include_parent=True)
    assert s["id"] == "s" and s["board"]["id"] == "b"

    # board id resolver cache
    calls = {"n": 0}
    def fake_query(q, v):
        calls["n"] += 1
        return {"items": [{"board": {"id": "B"}}]}
    c.query = fake_query
    assert c._get_board_id_for_subitem("10") == "B"
    assert c._get_board_id_for_subitem("10") == "B"
    assert calls["n"] == 1


def test_docs_helpers_and_tags(monkeypatch):
    c = MondayClient(token="t")
    # by_object_id False uses ids var
    captured = {}
    c.query = lambda q, v: captured.update(v) or {"docs": [{"id": "d"}]}
    d = c.get_doc("7", by_object_id=False)
    assert d["id"] == "d" and "ids" in captured

    # from column extract doc text and tags
    c.get_item_values = lambda item_id, column_ids=None, include_board=False: {"column_values": [{"value": {"files": [{"objectId": "obj1"}], "tag_ids": [1, 2]}, "text": "tag1, tag2"}]}
    c.get_doc_text = lambda doc_id: "doc body"
    assert c.get_doc_text_from_column("i", "c") == "doc body"
    tags = c.get_tags_from_column("i", "c")
    assert tags == [{"skill_id": "1", "skill_name": "tag1"}, {"skill_id": "2", "skill_name": "tag2"}]


def test_set_full_doc_plain_text_paths(monkeypatch):
    c = MondayClient(token="t")
    # path 1: cell already has doc
    c.get_item_values = lambda item_id, column_ids=None, include_board=False: {"column_values": [{"value": {"files": [{"objectId": "objc"}]}}]}
    c.get_doc = lambda object_id, by_object_id=True, fields=None: {"id": "real"}
    blocks_deleted = []
    c.get_all_blocks = lambda object_id: [{"id": "a", "type": "normal text"}, {"id": "b", "type": "large title"}]
    c.mutation = lambda q, v: blocks_deleted.append(v["b"]) or {"delete_doc_block": {"id": v["b"]}}
    created = {}
    def create_block(doc_id, *, block_type, content, after_block_id=None, fields=("id",)):
        created["doc_id"] = doc_id
        created["content"] = content
        return {"id": "blk"}
    c.create_doc_block = create_block
    c.set_full_doc_plain_text("item", "col", "Hello")
    assert created["doc_id"] == "real" and set(blocks_deleted) == {"a", "b"}

    # path 2: no existing doc → create first
    c.get_item_values = lambda item_id, column_ids=None, include_board=False: {"column_values": [{"value": {"files": []}}]}
    c.create_doc = lambda item_id, column_id, fields=None: {"id": "newdoc"}
    created.clear(); blocks_deleted.clear()
    c.set_full_doc_plain_text("item", "col", "World")
    assert created["doc_id"] == "newdoc"


def test_users_and_board_subscribers(monkeypatch):
    c = MondayClient(token="t")

    # list_users simple path
    c.query = lambda q, v=None: {"users": [{"id": "1", "name": "U", "email": "u@example.com"}]}
    users = c.list_users()
    assert users and users[0]["id"] == "1"

    # list_board_subscribers
    c.query = lambda q, v: {"boards": [{"subscribers": [{"id": "2"}]}]}
    subs = c.list_board_subscribers("B")
    assert subs and subs[0]["id"] == "2"

    # add/remove subscribers
    added = {}
    def mut(q, v):
        added.update(v)
        if "add_subscribers_to_board" in q:
            return {"add_subscribers_to_board": {"id": v["bid"]}}
        return {"remove_subscribers_from_board": {"id": v["bid"]}}
    c.mutation = mut
    c.add_board_subscribers("B", [1, 2])
    assert added["ids"] == [1, 2]
    c.remove_board_subscribers("B", [1])



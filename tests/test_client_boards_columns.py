import json

from monpy import MondayClient


def test_create_and_archive_board(monkeypatch):
    c = MondayClient(token="t")
    captured = {}

    def mut(query, vars):
        captured.update(vars)
        # echo back minimal board fields
        return {"create_board": {"id": "B", "name": "N", "board_kind": "public", "state": "active", "workspace_id": None, "updated_at": None}}

    c.mutation = mut
    b = c.create_board(name="N", board_kind="public", workspace_id="W", template_id=None)
    assert b["id"] == "B" and captured["name"] == "N" and captured["ws"] == "W"

    # archive path
    archived = {"id": None}
    c.mutation = lambda q, v: archived.update(v) or {"archive_board": {"id": v["id"]}}
    c.archive_board("B")
    assert archived["id"] == "B"


def test_create_and_update_column(monkeypatch):
    c = MondayClient(token="t")
    # create_column should JSON-encode defaults and augment settings
    c.mutation = lambda q, v: {"create_column": {"id": "c1", "title": "Links", "type": "connect_boards", "settings_str": json.dumps({"boardIds": [1]})}}
    col = c.create_column("B", title="Links", column_type="connect_boards", defaults={"x": 1}, description="desc")
    assert col["connected_board_ids"] == ["1"] and col["settings"] == {"boardIds": [1]}

    # update_column: title and description paths
    calls = {"title": None, "desc": None}

    def mut(q, v):
        if "change_column_title" in q:
            calls["title"] = v["t"]
            return {"change_column_title": {"id": "c1"}}
        if "change_column_metadata" in q:
            calls["desc"] = v["v"]
            return {"change_column_metadata": {"id": "c1"}}
        return {}

    c.mutation = mut
    c.update_column("B", "c1", title="New", description="D")
    assert calls == {"title": "New", "desc": "D"}



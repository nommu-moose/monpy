import types

import pytest

from monpy import Session


def test_session_identity_and_workspace(monkeypatch):
    class FakeClient:
        def get_workspace(self, wid):
            return {"id": wid, "name": "Main", "kind": "open", "description": "D"}

    sess = Session(FakeClient())
    ws1 = sess.workspace("w1")
    ws2 = sess.workspace("w1")
    assert ws1 is ws2
    assert ws1.name == "Main"


def test_board_columns_cached_and_lookup(monkeypatch):
    class FakeClient:
        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid):
            return [
                {"id": "colA", "title": "Due Date", "type": "date", "settings": {}},
                {"id": "colB", "title": "Status", "type": "status", "settings": {}},
            ]

    sess = Session(FakeClient())
    bd = sess.board("b1")
    # cache filled on first access
    cols = bd.columns
    assert cols.has_attr("due_date") and cols.has_id("colA")
    assert cols.by_attr("status").id == "colB"


def test_item_values_set_and_flush_batched(monkeypatch):
    called = {"payloads": []}

    class FakeClient:
        def get_item_values(self, iid, **k):
            return {"id": iid, "board": {"id": "b1"}}

        def get_board(self, bid):
            return {"id": bid}

        def get_columns(self, bid):
            return [{"id": "c1", "title": "Text", "type": "text", "settings": {}}]

        def mutation(self, q, v):
            called["payloads"].append(v)
            return {}

        def update_item_values(self, b, i, *, column_values):
            # Should be routed through batch path when possible
            called["payloads"].append({"board": b, "item": i, "vals": column_values})

    sess = Session(FakeClient())
    it = sess.item("i1")
    # Access values to ensure lazy path works
    _ = it.values
    # set via attribute encoder
    it.values.text = 123
    # saving triggers scheduled update
    it.save()
    assert called["payloads"]



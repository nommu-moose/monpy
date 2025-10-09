from monpy.oo.session import Session


class _FakeClient:
    def __init__(self):
        self.calls = {"single": 0, "multi": 0}

    def get_board(self, bid):
        return {"id": bid, "name": "B"}

    def get_columns(self, bid):
        return [
            {"id": "c_text", "title": "Text", "type": "text", "settings": {}},
            {"id": "c_status", "title": "Status", "type": "status", "settings": {}},
        ]

    def get_item_values(self, item_id, include_board=False, column_ids=None):
        self.calls["single"] += 1
        cvs = [
            {"id": "c_text", "value": "{\"text\":\"hello\"}", "text": "hello", "type": "text"},
            {"id": "c_status", "value": {"index": 1}, "text": "Working on it", "type": "status"},
        ]
        row = {"id": item_id, "name": "I", "state": "active", "updated_at": "t", "column_values": cvs}
        if include_board:
            row["board"] = {"id": "b1"}
        if column_ids:
            row["column_values"] = [cv for cv in cvs if cv["id"] in set(column_ids)]
        return row

    def get_items_values(self, item_ids, include_board=False, column_ids=None, batch_size=100, **_):
        self.calls["multi"] += 1
        rows = []
        for iid in item_ids:
            rows.append(self.get_item_values(iid, include_board=include_board, column_ids=column_ids))
        return rows


def test_item_prefetch_warms_cache_and_uses_ttl():
    c = _FakeClient()
    sess = Session(c, values_cache_ttl=60.0)
    it = sess.item("i1", board_id="b1")

    # Prefetch all values at once
    it.prefetch_values()
    single_calls = c.calls["single"]

    # Subsequent attribute reads should hit the warmed cache
    assert it.values.text == "hello"
    assert it.values.status == "Working on it"
    assert it.values.status_index == 1
    # No new single-value calls should have been made
    assert c.calls["single"] == single_calls


def test_session_prefetch_items_values_multi_item():
    c = _FakeClient()
    sess = Session(c, values_cache_ttl=60.0)
    # identity-map items
    i1 = sess.item("i1", board_id="b1")
    i2 = sess.item("i2", board_id="b1")

    # Bulk prefetch both items in one go
    rows = sess.prefetch_items_values(["i1", "i2"], column_ids=["c_text", "c_status"], batch_size=50)
    assert isinstance(rows, list) and len(rows) == 2
    # Attribute reads should be cached for both
    assert i1.values.text == "hello"
    assert i2.values.text == "hello"
    assert i1.values.status_index == 1
    assert i2.values.status == "Working on it"

    # Ensure client multi was used and subsequent single attribute access did not trigger per-column fetches
    assert c.calls["multi"] >= 1
    single_after = c.calls["single"]
    _ = i1.values.text
    _ = i2.values.status
    assert c.calls["single"] == single_after

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



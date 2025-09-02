from __future__ import annotations

import json


def test_iter_workspaces_uses_pages(monkeypatch):
    from monpy.client import MondayClient

    recorded: list[dict] = []

    def fake_query(q: str, vars: dict | None = None):
        recorded.append({"query": q, "vars": vars})
        page = (vars or {}).get("pg") or 1
        if page == 1:
            return {"workspaces": [{"id": "w1"}, {"id": "w2"}, {"id": "w3"}]}
        if page == 2:
            return {"workspaces": [{"id": "w4"}]}
        return {"workspaces": []}

    c = MondayClient(token="t")
    c.query = fake_query  # type: ignore[assignment]

    got = [w["id"] for w in c.iter_workspaces(page_size=3, fields=("id",))]
    assert got == ["w1", "w2", "w3", "w4"]
    # ensure we asked for page 1 then 2
    pages = [(rec["vars"] or {}).get("pg") for rec in recorded]
    assert pages[:2] == [None, 2]


def test_iter_boards_uses_pages(monkeypatch):
    from monpy.client import MondayClient

    captured_vars = []

    def q(q: str, v: dict | None = None):
        captured_vars.append(v)
        page = (v or {}).get("pg") or 1
        if page == 1:
            return {"boards": [{"id": "b1"}, {"id": "b2"}]}
        if page == 2:
            return {"boards": [{"id": "b3"}]}
        return {"boards": []}

    c = MondayClient(token="t")
    c.query = q  # type: ignore[assignment]

    got = [b["id"] for b in c.iter_boards(page_size=2, fields=("id",))]
    assert got == ["b1", "b2", "b3"]
    pages = [vars.get("pg") for vars in captured_vars]
    assert pages[:2] == [None, 2]


def test_iter_users_uses_pages(monkeypatch):
    from monpy.client import MondayClient

    seen_pages: list[int | None] = []

    def q(q: str, v: dict | None = None):
        seen_pages.append((v or {}).get("pg"))
        page = (v or {}).get("pg") or 1
        if page == 1:
            return {"users": [{"id": "u1"}]}
        if page == 2:
            return {"users": [{"id": "u2"}]}
        return {"users": []}

    c = MondayClient(token="t")
    c.query = q  # type: ignore[assignment]

    got = [u["id"] for u in c.iter_users(page_size=1, fields=("id",))]
    assert got == ["u1", "u2"]
    assert seen_pages[:2] == [None, 2]


def test_iter_items_cursor(monkeypatch):
    from monpy.client import MondayClient

    # Simulate items_page with cursor
    def q(q: str, v: dict | None = None):
        cur = (v or {}).get("cur")
        if cur is None:
            return {"boards": [{"items_page": {"cursor": "C2", "items": [{"id": "i1"}, {"id": "i2"}]}}]}
        if cur == "C2":
            return {"boards": [{"items_page": {"cursor": None, "items": [{"id": "i3"}]}}]}
        return {"boards": [{"items_page": {"cursor": None, "items": []}}]}

    c = MondayClient(token="t")
    c.query = q  # type: ignore[assignment]

    got = [it["id"] for it in c.iter_items("B", page_size=2, fields=("id",))]
    assert got == ["i1", "i2", "i3"]


def test_iter_items_by_column_values_cursor(monkeypatch):
    from monpy.client import MondayClient
    from monpy import MondayAPIError

    # Simulate items_page_by_column_values with cursor across two pages
    def q(q: str, v: dict | None = None):
        # Force modern path by causing legacy endpoint to error out
        if "items_by_column_values" in q and "items_page_by_column_values" not in q:
            raise MondayAPIError("legacy not available", errors=[{"message": "cannot query field"}])
        # Ensure we pass cursor variable after first page
        cur = (v or {}).get("cur")
        if cur is None:
            # first page
            assert "items_page_by_column_values" in q
            return {
                "items_page_by_column_values": {
                    "cursor": "N2",
                    "items": [{"id": "x1"}, {"id": "x2"}],
                }
            }
        if cur == "N2":
            # second page
            return {
                "items_page_by_column_values": {
                    "cursor": None,
                    "items": [{"id": "x3"}],
                }
            }
        return {"items_page_by_column_values": {"cursor": None, "items": []}}

    c = MondayClient(token="t")
    c.query = q  # type: ignore[assignment]

    got = [it["id"] for it in c.iter_items_by_column_values(
        "B", column_id="status", column_value={"index": 1}, page_size=2, fields=("id",)
    )]
    assert got == ["x1", "x2", "x3"]



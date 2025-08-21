import types
import time as _time

import pytest

from monpy import MondayClient, MondayAPIError


class FakeResp:
    def __init__(self, *, status_code=200, body=None, text="", json_payload=None):
        self.status_code = status_code
        self.text = text
        self._body = body
        self._json = json_payload

    def json(self):
        if self._json is not None:
            return self._json
        return {}


def test_fields_to_str_default_and_custom():
    c = MondayClient(token="t")
    assert c._fields_to_str(None, ("id", "name")) == "id name"
    assert c._fields_to_str(["id", "x"], ("id",)) == "id x"


def test_request_http_error(monkeypatch):
    c = MondayClient(token="t", max_retries=0)
    monkeypatch.setattr(c, "_session", types.SimpleNamespace(post=lambda *a, **k: FakeResp(status_code=500, text="boom")))
    with pytest.raises(MondayAPIError) as ei:
        c.query("query { x }")
    assert "HTTP 500" in str(ei.value)


def test_request_graphql_retry_then_success(monkeypatch):
    c = MondayClient(token="t", max_retries=2, backoff=0)

    calls = {"n": 0}

    def post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return FakeResp(json_payload={"errors": [{"message": "internal server error", "extensions": {"status_code": 500}}]})
        return FakeResp(json_payload={"data": {"ok": True}})

    monkeypatch.setattr(c, "_session", types.SimpleNamespace(post=post))
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)

    assert c.query("query { x }") == {"ok": True}
    assert calls["n"] == 2


def test_request_graphql_errors_raise(monkeypatch):
    c = MondayClient(token="t", max_retries=0)
    monkeypatch.setattr(c, "_session", types.SimpleNamespace(post=lambda *a, **k: FakeResp(json_payload={"errors": [{"message": "bad"}]})))
    with pytest.raises(MondayAPIError) as ei:
        c.query("query { x }")
    assert "GraphQL errors" in str(ei.value)


def test_resolve_board_and_column_ids_success(monkeypatch):
    c = MondayClient(token="t")
    monkeypatch.setattr(c, "list_workspaces", lambda **k: [{"id": "w1", "name": "Main"}])
    monkeypatch.setattr(c, "list_boards", lambda **k: [{"id": "b1", "name": "Roadmap", "workspace_id": "w1"}])
    monkeypatch.setattr(c, "get_columns", lambda board_id, **k: [{"id": "c1", "title": "Email address"}])
    bid, cmap = c.resolve_board_and_column_ids(workspace_name="Main", board_name="Roadmap", title_mappings={"email": "Email address"})
    assert bid == "b1"
    assert cmap == {"email": "c1"}


def test_resolve_board_and_column_ids_missing(monkeypatch):
    c = MondayClient(token="t")
    monkeypatch.setattr(c, "list_workspaces", lambda **k: [])
    with pytest.raises(ValueError):
        c.resolve_board_and_column_ids(workspace_name="X", board_name="Y", title_mappings={})


def test_get_column_id_by_title(monkeypatch):
    c = MondayClient(token="t")
    monkeypatch.setattr(c, "get_columns", lambda board_id: [{"id": "c1", "title": "Doc"}])
    assert c.get_column_id_by_title("b1", "Doc") == "c1"
    monkeypatch.setattr(c, "get_columns", lambda board_id: [])
    with pytest.raises(Exception):
        c.get_column_id_by_title("b1", "Anything")



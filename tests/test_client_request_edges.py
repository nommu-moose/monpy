import types
import requests
import pytest

from monpy import MondayClient, MondayAPIError


class _Resp:
    def __init__(self, status_code=200, json_payload=None, text=""):
        self.status_code = status_code
        self._json = json_payload
        self.text = text

    def json(self):
        return self._json or {}


def test_request_403_retry_then_ok(monkeypatch):
    c = MondayClient(token="t", backoff=0, max_retries=0)
    c.retries = 1
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return _Resp(status_code=403) if calls["n"] == 1 else _Resp(json_payload={"data": {"ok": True}})
    c._session = types.SimpleNamespace(post=post, headers={})
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    assert c.query("q") == {"ok": True}
    assert calls["n"] == 2


def test_request_429_backoff_then_ok(monkeypatch):
    c = MondayClient(token="t", max_retries=1, backoff=0)
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return _Resp(status_code=429) if calls["n"] == 1 else _Resp(json_payload={"data": {"ok": True}})
    c._session = types.SimpleNamespace(post=post, headers={})
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    assert c.query("q") == {"ok": True}


def test_request_exception_then_ok(monkeypatch):
    c = MondayClient(token="t", max_retries=1, backoff=0)
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.RequestException("net")
        return _Resp(json_payload={"data": {"ok": True}})
    c._session = types.SimpleNamespace(post=post, headers={})
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    assert c.query("q") == {"ok": True}


def test_request_5xx_then_ok(monkeypatch):
    c = MondayClient(token="t", max_retries=1, backoff=0)
    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return _Resp(status_code=503) if calls["n"] == 1 else _Resp(json_payload={"data": {"ok": True}})
    c._session = types.SimpleNamespace(post=post, headers={})
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    assert c.query("q") == {"ok": True}


def test_list_items_board_not_found_raises():
    c = MondayClient(token="t")
    c.query = lambda q, v: {"boards": []}
    with pytest.raises(MondayAPIError):
        c.list_items("b")



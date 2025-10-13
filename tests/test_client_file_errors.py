import types
import pytest

from monpy import MondayClient, MondayAPIError, HTTPError


def test_upload_file_http_error(monkeypatch):
    c = MondayClient(token="t")
    def r_post(url, headers=None, data=None, files=None, timeout=None):
        return types.SimpleNamespace(status_code=500, text="boom", json=lambda: {})
    monkeypatch.setattr("requests.post", r_post)
    with pytest.raises(HTTPError):
        c.upload_file_to_column("i", column_id="c", file_obj=types.SimpleNamespace(name="f"))


def test_upload_file_graphql_errors(monkeypatch):
    c = MondayClient(token="t")
    def r_post(url, headers=None, data=None, files=None, timeout=None):
        return types.SimpleNamespace(status_code=200, json=lambda: {"errors": [{"message": "bad"}]})
    monkeypatch.setattr("requests.post", r_post)
    with pytest.raises(MondayAPIError):
        c.upload_file_to_column("i", column_id="c", file_obj=types.SimpleNamespace(name="f"))


def test_download_file_http_error(monkeypatch):
    c = MondayClient(token="t")
    c.get_item_values = lambda item_id, column_ids=None: {"column_values": [{"value": {"files": [{"public_url": "http://x"}]}}]}
    def r_get(url, timeout=None, headers=None):
        return types.SimpleNamespace(status_code=404, text="nope")
    monkeypatch.setattr("requests.get", r_get)
    with pytest.raises(HTTPError):
        c.download_files_from_column("i", "c")


def test_list_files_asset_public_url_fallback_failure(monkeypatch):
    c = MondayClient(token="t")
    c.get_item_values = lambda item_id, column_ids=None: {"column_values": [{"value": {"files": [{"id": "a1"}]}}]}
    # make asset lookup raise
    def bad_query(q, v):
        raise RuntimeError("oops")
    c.query = bad_query
    files = c.list_files_from_column("i", "c")
    assert files[0]["public_url"] is None



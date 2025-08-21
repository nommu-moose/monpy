import types
import pytest

from monpy import MondayClient, MondayAPIError


def test_list_files_from_empty_column_returns_empty(monkeypatch):
    c = MondayClient(token="t")
    c.get_item_values = lambda item_id, column_ids=None: {"column_values": [{"value": {"files": []}}]}
    assert c.list_files_from_column("i", "c") == []


def test_download_files_from_column_missing_raises(monkeypatch):
    c = MondayClient(token="t")
    # No files payload at all -> triggers error path
    c.get_item_values = lambda item_id, column_ids=None: {"column_values": []}
    with pytest.raises(MondayAPIError):
        c.download_files_from_column("i", "c")


def test_list_files_from_column_resolves_public_url(monkeypatch):
    c = MondayClient(token="t")
    # Asset without public_url should be resolved via query
    c.get_item_values = lambda item_id, column_ids=None: {"column_values": [{"value": {"files": [{"id": "a1", "name": "x", "file_size": 1, "file_extension": "txt"}]}}]}
    c.query = lambda q, v: {"assets": [{"public_url": "http://p"}]}
    files = c.list_files_from_column("i", "c")
    assert files[0]["public_url"] == "http://p"



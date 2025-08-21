import io
import json
import types

import pytest

from monpy import MondayClient, MondayAPIError


def _ok(data):
    return types.SimpleNamespace(json=lambda: {"data": data}, status_code=200)


def test_get_doc_and_blocks_paging(monkeypatch):
    c = MondayClient(token="t")

    def post_first(*a, **k):
        return _ok({"docs": [{"id": "d1", "blocks": [{"id": "b1", "type": "normal text", "content": json.dumps({"deltaFormat": [{"insert": "A"}]})}]}]})

    def post_second(*a, **k):
        return _ok({"docs": [{"id": "d1", "blocks": []}]})

    calls = {"n": 0}
    def post(*a, **k):
        calls["n"] += 1
        return post_first() if calls["n"] == 1 else post_second()

    c._session = types.SimpleNamespace(post=post, headers={})

    blocks = c.get_all_blocks("object-1")
    assert [b["id"] for b in blocks] == ["b1"]
    # Reset stub to always return one block for text extraction
    def post_always(*a, **k):
        return _ok({"docs": [{"id": "d1", "blocks": [{"id": "b1", "type": "normal text", "content": json.dumps({"deltaFormat": [{"insert": "A"}]})}]}]})
    c._session = types.SimpleNamespace(post=post_always, headers={})
    txt = c.get_doc_text("object-1")
    assert "A" in txt


def test_create_doc_and_block(monkeypatch):
    c = MondayClient(token="t")
    def post(*a, **k):
        body = k.get("json", {}).get("variables", {}) if "json" in k else {}
        q = k.get("json", {}).get("query", "")
        if "create_doc_block" in q:
            return _ok({"create_doc_block": {"id": "blk"}})
        return _ok({"create_doc": {"id": "doc"}})

    c._session = types.SimpleNamespace(post=post, headers={})
    meta = c.create_doc(item_id="i", column_id="c")
    assert meta["id"] == "doc"
    blk = c.create_doc_block("doc", block_type="normal_text", content={"deltaFormat": []})
    assert blk["id"] == "blk"


def test_upload_file_and_list_download(monkeypatch):
    c = MondayClient(token="t")
    # Upload uses requests.post directly
    def r_post(url, headers=None, data=None, files=None, timeout=None):
        assert "add_file_to_column" in data.get("query", "")
        return types.SimpleNamespace(status_code=200, json=lambda: {"data": {"add_file_to_column": {"id": "a1", "url": "u", "public_url": "p"}}})

    # get_item_values for listing uses client.query
    def fake_query(q, v):
        return {"items": [{"column_values": [{"value": {"files": [{"id": "a1", "name": "x.txt", "file_size": 3, "file_extension": "txt", "public_url": "http://x"}]}}]}]}

    def r_get(url, timeout=None, headers=None):
        return types.SimpleNamespace(status_code=200, content=b"abc", text="ok")

    monkeypatch.setattr("requests.post", r_post)
    monkeypatch.setattr("requests.get", r_get)
    c.query = fake_query

    out = c.upload_file_to_column("i", column_id="c", file_obj=io.BytesIO(b"abc"))
    assert out["id"] == "a1"

    files = c.list_files_from_column("i", "c")
    assert files and files[0]["asset_id"] == "a1" and files[0]["public_url"]

    # download path
    def fake_query2(q, v):
        return {"items": [{"column_values": [{"value": {"files": [{"id": "a1", "public_url": "http://x"}]}}]}]}
    c.query = fake_query2
    blobs = c.download_files_from_column("i", "c")
    assert blobs == [b"abc"]



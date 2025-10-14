import io
import pytest
from monpy.exceptions import MondayAPIError, FeatureNotSupported


pytestmark = [pytest.mark.live]


@pytest.mark.files
def test_files_upload_list_download(live_env, client_live):
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]
    cols = live_env["cols"]
    item = bd1.create_item(group_id=g1["id"], item_name="file-item")
    uploaded = client_live.upload_file_to_column(
        item_id=item.id,
        column_id=cols["file"]["id"],
        file_obj=io.BytesIO(b"hello"),
        filename="hello.txt",
        mime_type="text/plain",
    )
    assert uploaded.get("id")
    meta = client_live.list_files_from_column(item.id, cols["file"]["id"])  # type: ignore[arg-type]
    assert meta and meta[0].get("asset_id")
    content = client_live.download_files_from_column(item.id, cols["file"]["id"])  # type: ignore[arg-type]
    assert content and isinstance(content[0], (bytes, bytearray)) and len(content[0]) > 0


@pytest.mark.docs
def test_docs_write_read(live_env, client_live):
    cols = live_env["cols"]
    if not (cols.get("doc") and cols["doc"].get("id")):
        pytest.skip("docs column unsupported")
    bd1 = live_env["bd1"]
    g1 = live_env["g1"]
    item = bd1.create_item(group_id=g1["id"], item_name="doc-item")
    try:
        client_live.set_full_doc_plain_text(item.id, cols["doc"]["id"], "hello doc")  # type: ignore[arg-type]
        txt = client_live.get_doc_text_from_column(item.id, cols["doc"]["id"])  # type: ignore[arg-type]
        assert "hello doc" in (txt or "")
    except (FeatureNotSupported, MondayAPIError):
        pytest.skip("Docs operations not permitted for this token/account")



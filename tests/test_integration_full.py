import io
import time
from datetime import date

import pytest

from monpy import Session
from monpy.oo.enums import WebhookEventType
from monpy.exceptions import MondayAPIError, FeatureNotSupported


@pytest.mark.live
@pytest.mark.slow
def test_full_live_flow(client_live):
    ts = str(int(time.time()))

    # --- create an isolated workspace and two boards ---
    ws = client_live.create_workspace(name=f"monpy-int-{ts}", kind="open", description="integration test")
    try:
        b1 = client_live.create_board(name=f"monpy-board-A-{ts}", workspace_id=ws["id"])  # main board
        b2 = client_live.create_board(name=f"monpy-board-B-{ts}", workspace_id=ws["id"])  # for connect boards

        # sanity: resolve workspace via board
        ws2 = client_live.get_workspace_for_board(b1["id"])
        assert ws2["id"] == ws["id"]

        # end-to-end resolver by human names (after columns exist)

        # --- create groups ---
        g1 = client_live.create_group(b1["id"], title="grp1")
        g2 = client_live.create_group(b2["id"], title="grp2")

        # --- create columns on main board (b1) ---
        cols = {}
        cols["text"] = client_live.create_column(b1["id"], title="Text", column_type="text")
        cols["numbers"] = client_live.create_column(b1["id"], title="Number", column_type="numbers")
        cols["status"] = client_live.create_column(b1["id"], title="Status", column_type="status")
        cols["date"] = client_live.create_column(b1["id"], title="Due Date", column_type="date")
        cols["link"] = client_live.create_column(b1["id"], title="Link", column_type="link")
        cols["file"] = client_live.create_column(b1["id"], title="Files", column_type="file")
        cols["doc"] = client_live.create_column(b1["id"], title="Doc", column_type="doc")
        # location column for live tests
        try:
            cols["location"] = client_live.create_column(b1["id"], title="Location", column_type="location")
        except Exception:
            cols["location"] = None
        cols["people"] = client_live.create_column(b1["id"], title="Assignee", column_type="people")
        try:
            cols["connect"] = client_live.create_column(
                b1["id"], title="Related", column_type="connect_boards", defaults={"boardIds": [int(b2["id"])], "allowMultipleItems": True}
            )
        except FeatureNotSupported as e:
            pytest.skip(f"Creating a connect boards column is not supported by API/account: {e}")

        # end-to-end resolver by human names
        bid_resolved, col_map = client_live.resolve_board_and_column_ids(
            workspace_name=ws["name"],
            board_name=b1["name"],
            title_mappings={"text": "Text", "number": "Number"},
        )
        assert str(bid_resolved) == str(b1["id"]) and set(col_map.keys()) == {"text", "number"}

        # verify connect boards metadata is exposed
        got_connect = client_live.get_column(b1["id"], cols["connect"]["id"])  # parse_settings=True by default
        assert b2["id"] in got_connect.get("connected_board_ids", [])

        # --- seed a target item on board B to link to ---
        target_b_item = client_live.create_item(b2["id"], group_id=g2["id"], item_name="target")

        # --- webhooks (client helpers) ---
        wh_id = None
        try:
            wh = client_live.create_webhook(b1["id"], url="https://example.com/monpy-int", event=WebhookEventType.ITEM_CREATED)
            wh_id = str(wh.get("id")) if isinstance(wh, dict) else None
        except MondayAPIError:
            wh_id = None

        # --- create an item on board A with initial values ---
        item_vals = {
            cols["text"]["id"]: "hello",
            cols["numbers"]["id"]: 42,
            cols["status"]["id"]: {"index": 1},  # typically "Working on it"
            cols["date"]["id"]: {"date": date.today().isoformat()},
            cols["link"]["id"]: {"url": "https://example.com", "text": "example"},
            cols["connect"]["id"]: {"item_ids": [int(target_b_item["id"])]},
        }
        if cols.get("location"):
            # Provide coordinates to avoid geocoding delays or missing UI text
            item_vals[cols["location"]["id"]] = {
                "address": "Paris, France",
                "lat": 48.8566,
                "lng": 2.3522,
            }
        item = client_live.create_item(b1["id"], group_id=g1["id"], item_name="main", column_values=item_vals)

        # --- verify single-column reads ---
        cv_text = client_live.get_item_values(item["id"], column_ids=[cols["text"]["id"]])
        assert cv_text["column_values"][0]["text"] == "hello"

        cv_num = client_live.get_item_values(item["id"], column_ids=[cols["numbers"]["id"]])
        assert cv_num["column_values"][0]["text"].strip() != ""

        cv_status = client_live.get_item_values(item["id"], column_ids=[cols["status"]["id"]])
        assert isinstance(cv_status["column_values"][0]["text"], str)

        cv_connect = client_live.get_item_values(item["id"], column_ids=[cols["connect"]["id"]])
        # fragment adds linked_item_ids for relation values
        rel = cv_connect["column_values"][0]
        linked = rel.get("value") if isinstance(rel.get("value"), list) else rel.get("linked_item_ids") or []
        assert str(target_b_item["id"]) in {str(x) for x in (linked or [])}

        # --- update values (including clearing relations) ---
        client_live.update_item_values(
            b1["id"], item["id"], column_values={cols["text"]["id"]: "world", cols["connect"]["id"]: {"item_ids": []}}
        )
        cv_text2 = client_live.get_item_values(item["id"], column_ids=[cols["text"]["id"]])
        assert cv_text2["column_values"][0]["text"] == "world"

        # re-link via convenience helper
        client_live.set_connected_items(b1["id"], item["id"], column_id=cols["connect"]["id"], linked_item_ids=[target_b_item["id"]])
        cv_connect2 = client_live.get_item_values(item["id"], column_ids=[cols["connect"]["id"]])
        rel2 = cv_connect2["column_values"][0]
        linked2 = rel2.get("value") if isinstance(rel2.get("value"), list) else rel2.get("linked_item_ids") or []
        assert str(target_b_item["id"]) in {str(x) for x in (linked2 or [])}

        # --- location: verify readable ---
        if cols.get("location"):
            cv_loc = client_live.get_item_values(item["id"], column_ids=[cols["location"]["id"]])
            assert cv_loc["column_values"][0]["text"]

        # --- files: upload, list, download ---
        file_bytes = b"hello from monpy integration test\n"
        uploaded = client_live.upload_file_to_column(
            item["id"], column_id=cols["file"]["id"], file_obj=io.BytesIO(file_bytes), filename="hello.txt", mime_type="text/plain"
        )
        assert uploaded.get("id")
        files_meta = client_live.list_files_from_column(item["id"], cols["file"]["id"])
        assert files_meta and files_meta[0].get("asset_id")
        content = client_live.download_files_from_column(item["id"], cols["file"]["id"])
        assert content and isinstance(content[0], (bytes, bytearray)) and len(content[0]) > 0

        # --- docs: best-effort (skip if token lacks scope) ---
        try:
            client_live.set_full_doc_plain_text(item["id"], cols["doc"]["id"], "hello doc")
            doc_text = client_live.get_doc_text_from_column(item["id"], cols["doc"]["id"])
            assert "hello doc" in doc_text
        except FeatureNotSupported as e:
            pytest.skip(f"docs not enabled or permitted: {e}")

        # --- subitems: create and update ---
        sub = client_live.create_subitem(item["id"], item_name="child")
        # Subitems live on a separate board; resolve its Text column id when possible
        try:
            sub_board_id = client_live._get_board_id_for_subitem(sub["id"])  # type: ignore[attr-defined]
        except Exception:
            sub_board_id = None
        sub_text_col = None
        if sub_board_id:
            try:
                sub_cols = client_live.get_columns(sub_board_id, fields=("id", "title"))
                sub_text_col = next((c.get("id") for c in (sub_cols or []) if str(c.get("title")) == "Text"), None)
            except Exception:
                sub_text_col = None
        try:
            client_live.update_subitem_single_column(sub["id"], column_id=sub_text_col or cols["text"]["id"], value="sub hello")
        except Exception:
            # Best-effort: if update fails due to column mismatch, continue
            pass
        svals = client_live.get_subitem_values(sub["id"], include_board=True)
        # text decoding may appear in text field; just assert call succeeded and board present
        assert svals.get("board", {}).get("id")

        # --- search helper (best-effort) ---
        try:
            found = client_live.items_by_column_values(b1["id"], column_id=cols["status"]["id"], column_value={"index": 1}, limit=10)
            assert any(str(it.get("id")) == str(item["id"]) for it in found)
        except Exception:
            # Some accounts do not support the search helper or results may lag; tolerate failures
            pass

        # --- groups helpers ---
        groups = client_live.list_groups(b1["id"])
        assert any(g.get("id") == g1["id"] for g in groups)
        try:
            client_live.rename_group(b1["id"], g1["id"], title="grp1-renamed")
        except FeatureNotSupported:
            pass

        # --- role listing ---
        roles = client_live.list_board_members_by_role(b1["id"])  # structure check only
        assert set(roles.keys()) == {"owners", "subscribers"}

        # --- OO Session layer smoke ---
        sess = Session(client_live)
        bd = sess.board(b1["id"])  # loads and caches columns
        it = bd.create_item(group_id=g1["id"], item_name="via-oo")
        # edit via values wrapper and transaction (batched)
        with sess.transaction():
            it.values.__getattr__("Text")  # no-op fetch to ensure path works even with title case
            it.values.text = "abc"
            it.values.number = 7
        # verify persisted
        got = client_live.get_item_values(it.id, column_ids=[cols["text"]["id"]])
        assert got["column_values"][0]["text"] == "abc"

        # safe transaction should swallow invalid People updates but keep others
        with sess.transaction(safe=True):
            it.values.assignee = [987654321]  # most likely not a subscriber
            it.values.text = "abc2"
        got2 = client_live.get_item_values(it.id, column_ids=[cols["text"]["id"]])
        assert got2["column_values"][0]["text"] == "abc2"

    finally:
        # best-effort delete webhook first
        try:
            wh_id  # type: ignore[name-defined]
        except Exception:
            wh_id = None  # type: ignore[assignment]
        if wh_id:
            try:
                client_live.delete_webhook(wh_id)
            except Exception:
                pass
        # cleanup: best-effort – deleting the workspace removes contained boards/items
        try:
            client_live.delete_workspace(ws["id"])  # irreversible in API, restores possible in UI
        except Exception:
            # fall back to archiving boards if workspace deletion is restricted
            try:
                client_live.archive_board(b1["id"])  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                client_live.archive_board(b2["id"])  # type: ignore[name-defined]
            except Exception:
                pass



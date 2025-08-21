import io
import time
from datetime import date

import pytest

from monpy import Session
from monpy.oo.enums import WebhookEventType
from monpy.exceptions import MondayAPIError, FeatureNotSupported
from monpy.oo.doc import Doc
from monpy.oo.file_asset import (
    upload_to_file_column,
    list_files_from_column,
    download_files_from_column,
)


@pytest.mark.live
def test_full_live_flow_oo(client_live):
    ts = str(int(time.time()))

    # --- OO Session over the real client ---
    sess = Session(client_live)

    # --- create an isolated workspace and two boards ---
    ws = client_live.create_workspace(name=f"monpy-oo-int-{ts}", kind="open", description="integration test (oo)")
    try:
        # Prefer OO to create boards bound to the session
        b1_obj = sess.create_board(workspace_id=ws["id"], name=f"monpy-oo-board-A-{ts}", board_kind="public")
        b2_obj = sess.create_board(workspace_id=ws["id"], name=f"monpy-oo-board-B-{ts}", board_kind="public")
        b1 = {"id": b1_obj.id, "name": b1_obj.name}
        b2 = {"id": b2_obj.id, "name": b2_obj.name}

        # sanity: resolve workspace via board (low-level), and OO workspace identity mapping
        ws2 = client_live.get_workspace_for_board(b1["id"])
        assert ws2["id"] == ws["id"]
        ws_model = sess.workspace(ws["id"])  # OO wrapper
        assert ws_model.name == ws["name"]

        # --- create groups via OO board wrapper ---
        bd1 = sess.board(b1["id"])  # loads and caches columns lazily
        bd2 = sess.board(b2["id"])  # secondary board (for relations)

        # --- webhooks (OO wrappers) ---
        wh_id = None
        try:
            wh = bd1.register_webhook(url="https://example.com/monpy-oo", event=WebhookEventType.ITEM_CREATED)
            wh_id = str(wh.get("id")) if isinstance(wh, dict) else None
        except MondayAPIError:
            # Not all tokens/accounts permit webhook creation; skip silently
            wh_id = None
        g1 = bd1.create_group(title="grp1")
        g2 = bd2.create_group(title="grp2")

        # --- create columns via OO board API ---
        cols = {}
        cols["text"] = bd1.create_column(title="Text", column_type="text").__dict__
        cols["numbers"] = bd1.create_column(title="Number", column_type="numbers").__dict__
        cols["status"] = bd1.create_column(title="Status", column_type="status").__dict__
        cols["date"] = bd1.create_column(title="Due Date", column_type="date").__dict__
        cols["link"] = bd1.create_column(title="Link", column_type="link").__dict__
        cols["file"] = bd1.create_column(title="Files", column_type="file").__dict__
        cols["doc"] = bd1.create_column(title="Doc", column_type="doc").__dict__
        cols["people"] = bd1.create_column(title="Assignee", column_type="people").__dict__
        try:
            cols["connect"] = bd1.create_column(title="Related", column_type="connect_boards", defaults={"boardIds": [int(b2["id"])], "allowMultipleItems": True}).__dict__
        except FeatureNotSupported:
            cols["connect"] = None

        # refresh board to see the new columns in OO cache
        bd1.refresh()
        assert bd1.columns.has_id(cols["text"]["id"]) and bd1.columns.has_attr("text")

        # end-to-end resolver by human names (low-level convenience)
        bid_resolved, col_map = client_live.resolve_board_and_column_ids(
            workspace_name=ws["name"],
            board_name=b1["name"],
            title_mappings={"text": "Text", "number": "Number"},
        )
        assert str(bid_resolved) == str(b1["id"]) and set(col_map.keys()) == {"text", "number"}

        # verify connect boards metadata is exposed when available
        if cols.get("connect"):
            got_connect = client_live.get_column(b1["id"], cols["connect"]["id"])  # parse_settings=True by default
            assert b2["id"] in got_connect.get("connected_board_ids", [])

        # --- seed a target item on board B to link to (OO) ---
        target_b_item = bd2.create_item(group_id=g2["id"], item_name="target")

        # --- create an item on board A with initial values (OO board.create_item) ---
        item_vals = {
            cols["text"]["id"]: "hello",
            cols["numbers"]["id"]: 42,
            cols["status"]["id"]: {"index": 1},  # typically "Working on it"
            cols["date"]["id"]: {"date": date.today().isoformat()},
            cols["link"]["id"]: {"url": "https://example.com", "text": "example"},
        }
        if cols.get("connect"):
            item_vals[cols["connect"]["id"]] = {"item_ids": [int(target_b_item.id)]}
        item = bd1.create_item(group_id=g1["id"], item_name="main", values=item_vals)

        # --- verify single-column reads via OO values ---
        assert item.values.text == "hello"
        assert item.values.number is not None
        # status returns human label when available; just assert it’s a str
        assert isinstance(item.values.status, (str, dict))
        # relation decodes to list of ids (when connect column exists)
        if cols.get("connect"):
            assert int(target_b_item.id) in set(int(i) for i in (item.values.related or []))

        # --- update values (including clearing relations) via OO and a transaction ---
        with sess.transaction():
            item.values.text = "world"
            if cols.get("connect"):
                item.values.related = []
        assert item.values.text == "world"

        # re-link via OO convenience helper (by column attribute name)
        if cols.get("connect"):
            item.set_connected_items(column_attr="related", linked_item_ids=[target_b_item.id])
            assert int(target_b_item.id) in set(int(i) for i in (item.values.related or []))

        # --- files: upload, list, download (OO helpers) ---
        file_bytes = b"hello from monpy OO integration test\n"
        uploaded = upload_to_file_column(
            sess,
            item_id=item.id,
            column_id=cols["file"]["id"],
            file_obj=io.BytesIO(file_bytes),
            filename="hello.txt",
            mime_type="text/plain",
        )
        assert uploaded.get("id")
        files_meta = list_files_from_column(sess, item_id=item.id, column_id=cols["file"]["id"])
        assert files_meta and files_meta[0].get("asset_id")
        content = download_files_from_column(sess, item_id=item.id, column_id=cols["file"]["id"])
        assert content and isinstance(content[0], (bytes, bytearray)) and len(content[0]) > 0

        # --- docs: best-effort (skip if token lacks scope) ---
        try:
            # Use OO Doc wrapper to route to client helper via column context
            Doc(id="_tmp").bind(sess).replace_plain_text("hello doc", column_item_id=item.id, column_id=cols["doc"]["id"])  # type: ignore[arg-type]
            doc_text = client_live.get_doc_text_from_column(item.id, cols["doc"]["id"])  # read back via client convenience
            assert "hello doc" in doc_text
        except FeatureNotSupported:
            pass

        # --- subitems: create (low-level), then edit via OO ---
        sub_raw = client_live.create_subitem(item.id, item_name="child")
        si = sess.subitem(sub_raw["id"])  # OO SubItem wrapper
        si.values.text = "sub hello"
        si.save()  # flush subitem changes (not batched with items)
        svals = client_live.get_subitem_values(si.id, include_board=True)
        assert svals.get("board", {}).get("id")

        # --- search helper (low-level) ---
        found = sess.client.items_by_column_values(b1["id"], column_id=cols["status"]["id"], column_value={"index": 1}, limit=10)
        assert any(str(it.get("id")) == str(item.id) for it in found)

        # --- groups helpers (OO) ---
        groups = bd1.groups()
        assert any(g.get("id") == g1["id"] for g in groups)
        bd1.rename_group(g1["id"], title="grp1-renamed")

        # --- role listing (OO) ---
        roles = bd1.members_by_role()  # structure check only
        assert set(roles.keys()) == {"owners", "subscribers"}

        # --- safe transaction should swallow invalid People updates but keep others (OO) ---
        with sess.transaction(safe=True):
            item.values.assignee = [987654321]  # most likely not a subscriber
            item.values.text = "abc2"
        assert item.values.text == "abc2"

    finally:
        # Attempt to delete webhook first (best-effort)
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



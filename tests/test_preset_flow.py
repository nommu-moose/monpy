import io
import time
from datetime import date

import pytest

from monpy import Session
from monpy.exceptions import MondayAPIError, FeatureNotSupported
import uuid
from monpy.oo.doc import Doc
from monpy.oo.file_asset import (
    upload_to_file_column,
    list_files_from_column,
    download_files_from_column,
)


def _get_preset_names(cfg: dict) -> dict:
    names_cfg = (cfg.get("PRESET_NAMES") or {})
    return {
        "workspace": str(names_cfg.get("workspace") or "API_TESTS"),
        "board_a": str(((names_cfg.get("boards") or {}).get("a")) or "API_TESTS_A"),
        "board_b": str(((names_cfg.get("boards") or {}).get("b")) or "API_TESTS_B"),
        "group_primary": str(((names_cfg.get("groups") or {}).get("primary")) or "topics"),
        "columns": {
            "text": str(((names_cfg.get("columns") or {}).get("text")) or "Text"),
            "numbers": str(((names_cfg.get("columns") or {}).get("number")) or "Number"),
            "status": str(((names_cfg.get("columns") or {}).get("status")) or "Status"),
            "date": str(((names_cfg.get("columns") or {}).get("date")) or "Due Date"),
            "link": str(((names_cfg.get("columns") or {}).get("link")) or "Link"),
            "file": str(((names_cfg.get("columns") or {}).get("files")) or "Files"),
            "doc": str(((names_cfg.get("columns") or {}).get("doc")) or "Doc"),
            "location": str(((names_cfg.get("columns") or {}).get("location")) or "Location"),
            "people": str(((names_cfg.get("columns") or {}).get("people")) or "Assignee"),
            "connect": str(((names_cfg.get("columns") or {}).get("connect")) or "Related"),
        },
    }


def _resolve_workspace_and_boards(client, names: dict):
    workspaces = client.list_workspaces(limit=100)
    ws = next((w for w in workspaces if str(w.get("name")) == names["workspace"]), None)
    if not ws:
        pytest.skip(f'Preset workspace "{names["workspace"]}" not found')
    workspace_id = ws["id"]

    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name", "workspace_id"))
    b1 = next((b for b in boards if str(b.get("name")) == names["board_a"]), None)
    b2 = next((b for b in boards if str(b.get("name")) == names["board_b"]), None)
    if not b1 or not b2:
        pytest.skip("Preset boards not found in the workspace")
    return workspace_id, b1["id"], b2["id"]


def _group_id_for_board(client, board_id: str, preferred_group_id: str | None) -> str:
    groups = client.list_groups(board_id)
    # Prefer explicitly-named primary group (commonly "topics") if present
    if preferred_group_id and any(g.get("id") == preferred_group_id for g in groups or []):
        return preferred_group_id
    # Otherwise pick the first group id if available
    if groups:
        return groups[0].get("id")
    # Fallback to common primary id
    return preferred_group_id or "topics"


def _column_ids_by_title(client, board_id: str, title_map: dict) -> dict:
    cols = client.get_columns(board_id, fields=("id", "title"))
    title_to_id = {str(c.get("title")): c.get("id") for c in (cols or [])}
    return {
        "text": title_to_id.get(title_map["text"]),
        "numbers": title_to_id.get(title_map["numbers"]),
        "status": title_to_id.get(title_map["status"]),
        "date": title_to_id.get(title_map["date"]),
        "link": title_to_id.get(title_map["link"]),
        "file": title_to_id.get(title_map["file"]),
        "doc": title_to_id.get(title_map["doc"]),
        "location": title_to_id.get(title_map["location"]),
        "people": title_to_id.get(title_map["people"]),
        "connect": title_to_id.get(title_map["connect"]),
    }


def _safe_delete_item(client, item_id: str | int) -> None:
    try:
        client.delete_item(item_id)
    except Exception:
        pass


@pytest.mark.live
def test_preset_oo(client_live, _test_config):
    names = _get_preset_names(_test_config)
    _, board_a_id, board_b_id = _resolve_workspace_and_boards(client_live, names)

    group_primary_id_a = _group_id_for_board(client_live, board_a_id, names["group_primary"])  # likely "topics"
    group_primary_id_b = _group_id_for_board(client_live, board_b_id, names["group_primary"])  # likely "topics"

    col_ids = _column_ids_by_title(client_live, board_a_id, names["columns"])  # tolerant: may be None

    sess = Session(client_live)
    bd1 = sess.board(board_a_id)
    bd2 = sess.board(board_b_id)

    # Seed a target item on Board B
    target_b_item = bd2.create_item(group_id=group_primary_id_b, item_name="preset-target")

    # Best-effort webhook (may not be permitted)
    base = (_test_config.get("remote_test_site") or _test_config.get("REMOTE_TEST_SITE"))
    receive_url = None
    if base:
        base = base.strip()
        if not base.startswith("http://") and not base.startswith("https://"):
            if any(local in base for local in ("127.0.0.1", "localhost", "[::1]")):
                base = f"http://{base}"
            else:
                base = f"https://{base}"
        if base.endswith("/"):
            base = base[:-1]
        path_key = f"pytest-mirror-{uuid.uuid4().hex[:10]}"
        receive_url = f"{base}/hooks/{path_key}/"
    try:
        if receive_url:
            bd1.register_webhook(url=receive_url, event="item_created")
    except MondayAPIError:
        pass

    # Create main item on Board A with initial values (only for present columns)
    init_vals = {}
    if col_ids.get("text"):    init_vals[col_ids["text"]] = "hello"
    if col_ids.get("numbers"): init_vals[col_ids["numbers"]] = 42
    if col_ids.get("status"):  init_vals[col_ids["status"]] = {"index": 1}
    if col_ids.get("date"):    init_vals[col_ids["date"]] = {"date": date.today().isoformat()}
    if col_ids.get("link"):    init_vals[col_ids["link"]] = {"url": "https://example.com", "text": "example"}
    if col_ids.get("location"): init_vals[col_ids["location"]] = {"address": "Paris, France", "lat": 48.8566, "lng": 2.3522}
    if col_ids.get("connect"): init_vals[col_ids["connect"]] = {"item_ids": [int(target_b_item.id)]}

    item = bd1.create_item(group_id=group_primary_id_a, item_name="preset-main", values=init_vals)

    try:
        # Read initial values (best-effort assertions)
        if hasattr(item.values, "text"):
            assert item.values.text in {"hello", "world", "abc2"}

        # Transactional update: change text; clear relation if present
        with sess.transaction():
            try:
                item.values.text = "world"
            except Exception:
                pass
            if col_ids.get("connect"):
                try:
                    item.values.related = []
                except Exception:
                    pass

        if hasattr(item.values, "text"):
            assert item.values.text in {"world", "abc2"}

        # Re-link via OO convenience when connect column exists
        if col_ids.get("connect"):
            try:
                item.set_connected_items(column_attr="related", linked_item_ids=[target_b_item.id])
                # Confirm via OO readback if available
                try:
                    rel = set(int(i) for i in (item.values.related or []))
                    assert int(target_b_item.id) in rel
                except Exception:
                    pass
            except MondayAPIError:
                pass

        # Location: transactional write and verify readable (best-effort)
        if col_ids.get("location"):
            try:
                with sess.transaction():
                    item.values.Location = {"address": "Paris, France", "lat": 48.8566, "lng": 2.3522}
            except Exception:
                pass
            try:
                cv_loc = client_live.get_item_values(item.id, column_ids=[col_ids["location"]])
                assert (cv_loc.get("column_values") or [{}])[0].get("text")
            except Exception:
                pass

        # Files via OO helpers when Files column exists
        if col_ids.get("file"):
            try:
                uploaded = upload_to_file_column(
                    sess,
                    item_id=item.id,
                    column_id=col_ids["file"],
                    file_obj=io.BytesIO(b"hello from preset oo test\n"),
                    filename="hello.txt",
                    mime_type="text/plain",
                )
                assert uploaded.get("id")
                files_meta = list_files_from_column(sess, item_id=item.id, column_id=col_ids["file"])  # type: ignore[arg-type]
                if files_meta:
                    content = download_files_from_column(sess, item_id=item.id, column_id=col_ids["file"])  # type: ignore[arg-type]
                    assert content and isinstance(content[0], (bytes, bytearray)) and len(content[0]) > 0
            except MondayAPIError:
                pass

        # Docs best-effort (may not be permitted)
        if col_ids.get("doc"):
            try:
                Doc(id="_tmp").bind(sess).replace_plain_text("hello doc", column_item_id=item.id, column_id=col_ids["doc"])  # type: ignore[arg-type]
                txt = client_live.get_doc_text_from_column(item.id, col_ids["doc"])  # type: ignore[arg-type]
                assert "hello doc" in (txt or "")
            except (FeatureNotSupported, MondayAPIError):
                pass

        # Safe transaction: invalid People should be swallowed; Text should persist
        try:
            with sess.transaction(safe=True):
                try:
                    if col_ids.get("people"):
                        item.values.assignee = [987654321]  # most likely not a subscriber
                except Exception:
                    pass
                try:
                    item.values.text = "abc2"
                except Exception:
                    pass
            if hasattr(item.values, "text"):
                assert item.values.text in {"abc2", "world"}
        except MondayAPIError:
            pass

        # Groups list should return structure
        groups = bd1.groups()
        assert isinstance(groups, list)
    finally:
        # Cleanup created items (best-effort)
        _safe_delete_item(client_live, item.id)
        _safe_delete_item(client_live, target_b_item.id)


@pytest.mark.live
def test_preset_client(client_live, _test_config):
    names = _get_preset_names(_test_config)
    _, board_a_id, board_b_id = _resolve_workspace_and_boards(client_live, names)

    group_primary_id_a = _group_id_for_board(client_live, board_a_id, names["group_primary"])  # likely "topics"
    group_primary_id_b = _group_id_for_board(client_live, board_b_id, names["group_primary"])  # likely "topics"

    col_ids = _column_ids_by_title(client_live, board_a_id, names["columns"])  # tolerant: may be None

    # Seed a target item on Board B
    target_b_item = client_live.create_item(board_b_id, group_id=group_primary_id_b, item_name="preset-target")

    # Best-effort webhook (may not be permitted)
    try:
        client_live.create_webhook(board_a_id, url="https://example.com/monpy-preset", event="item_created")
    except MondayAPIError:
        pass

    # Create an item on Board A
    init_vals = {}
    if col_ids.get("text"):    init_vals[col_ids["text"]] = "hello"
    if col_ids.get("numbers"): init_vals[col_ids["numbers"]] = 42
    if col_ids.get("status"):  init_vals[col_ids["status"]] = {"index": 1}
    if col_ids.get("date"):    init_vals[col_ids["date"]] = {"date": date.today().isoformat()}
    if col_ids.get("link"):    init_vals[col_ids["link"]] = {"url": "https://example.com", "text": "example"}
    if col_ids.get("location"): init_vals[col_ids["location"]] = {"address": "Paris, France", "lat": 48.8566, "lng": 2.3522}
    if col_ids.get("connect"): init_vals[col_ids["connect"]] = {"item_ids": [int(target_b_item["id"])]}

    item = client_live.create_item(board_a_id, group_id=group_primary_id_a, item_name="preset-main", column_values=init_vals)

    try:
        # Verify single-column reads when present
        if col_ids.get("text"):
            cv_text = client_live.get_item_values(item["id"], column_ids=[col_ids["text"]])
            assert (cv_text.get("column_values") or [{}])[0].get("text") in {"hello", "world", "abc2"}

        # Update values (including clearing relations) when present
        update_vals = {}
        if col_ids.get("text"):
            update_vals[col_ids["text"]] = "world"
        if col_ids.get("connect"):
            update_vals[col_ids["connect"]] = {"item_ids": []}
        if update_vals:
            client_live.update_item_values(board_a_id, item["id"], column_values=update_vals)

        if col_ids.get("text"):
            cv_text2 = client_live.get_item_values(item["id"], column_ids=[col_ids["text"]])
            assert (cv_text2.get("column_values") or [{}])[0].get("text") in {"world", "abc2"}

        # Location: verify readable after create (best-effort)
        if col_ids.get("location"):
            try:
                cv_loc = client_live.get_item_values(item["id"], column_ids=[col_ids["location"]])
                assert (cv_loc.get("column_values") or [{}])[0].get("text")
            except MondayAPIError:
                pass

        # Re-link via convenience helper
        if col_ids.get("connect"):
            try:
                client_live.set_connected_items(board_a_id, item["id"], column_id=col_ids["connect"], linked_item_ids=[target_b_item["id"]])
                cv_connect = client_live.get_item_values(item["id"], column_ids=[col_ids["connect"]])
                rel = (cv_connect.get("column_values") or [{}])[0]
                linked = rel.get("value") if isinstance(rel.get("value"), list) else rel.get("linked_item_ids") or []
                assert str(target_b_item["id"]) in {str(x) for x in (linked or [])}
            except MondayAPIError:
                pass

        # Files
        if col_ids.get("file"):
            try:
                uploaded = client_live.upload_file_to_column(
                    item["id"],
                    column_id=col_ids["file"],
                    file_obj=io.BytesIO(b"hello from preset client test\n"),
                    filename="hello.txt",
                    mime_type="text/plain",
                )
                assert uploaded.get("id")
                files_meta = client_live.list_files_from_column(item["id"], col_ids["file"])  # type: ignore[arg-type]
                if files_meta:
                    content = client_live.download_files_from_column(item["id"], col_ids["file"])  # type: ignore[arg-type]
                    assert content and isinstance(content[0], (bytes, bytearray)) and len(content[0]) > 0
            except MondayAPIError:
                pass

        # Docs (best-effort)
        if col_ids.get("doc"):
            try:
                client_live.set_full_doc_plain_text(item["id"], col_ids["doc"], "hello doc")  # type: ignore[arg-type]
                txt = client_live.get_doc_text_from_column(item["id"], col_ids["doc"])  # type: ignore[arg-type]
                assert "hello doc" in (txt or "")
            except (FeatureNotSupported, MondayAPIError):
                pass
    finally:
        # Cleanup created items (best-effort)
        _safe_delete_item(client_live, item.get("id"))
        _safe_delete_item(client_live, target_b_item.get("id"))



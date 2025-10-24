from __future__ import annotations

import argparse
import io
import json
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import requests  # noqa: E402
from monpy import MondayClient, Session  # noqa: E402
from monpy.exceptions import MondayAPIError  # noqa: E402
from monpy.oo.file_asset import (  # noqa: E402
    upload_to_file_column,
    list_files_from_column,
    download_files_from_column,
)
from monpy.oo import WebhookEventType  # noqa: E402


def read_tests_config() -> dict:
    cfg = ROOT / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _wait(seconds: float) -> None:
    try:
        sec = float(seconds)
    except Exception:
        return
    if sec > 0:
        threading.Event().wait(sec)


def apply_runtime_knobs(delay: float, force_serial: bool) -> None:
    if delay > 0:
        orig_sess_post = requests.Session.post
        orig_post = requests.post
        orig_get = requests.get

        def delayed_sess_post(self, *a, **k):
            _wait(delay)
            return orig_sess_post(self, *a, **k)

        def delayed_post(*a, **k):
            _wait(delay)
            return orig_post(*a, **k)

        def delayed_get(*a, **k):
            _wait(delay)
            return orig_get(*a, **k)

        requests.Session.post = delayed_sess_post  # type: ignore[assignment]
        requests.post = delayed_post  # type: ignore[assignment]
        requests.get = delayed_get  # type: ignore[assignment]

    if force_serial:
        def _serial_execute(self, updates):
            for board_id, item_id, values in updates:
                if delay > 0:
                    _wait(delay)
                self.client.update_item_values(board_id, item_id, column_values=values)

        # Monkeypatch Session batching to serial execution
        Session._execute_batched_item_updates = _serial_execute  # type: ignore[assignment]


def step_pause(enabled: bool, message: str) -> None:
    if not enabled:
        return
    try:
        input(f"\n[STEP] {message}  Press Enter to continue… ")
    except KeyboardInterrupt:
        print("\nAborted by user.")
        sys.exit(1)


def ensure_connect_link(
    client: MondayClient,
    *,
    board_id: str,
    item_id: str,
    connect_column_id: Optional[str],
    target_item_id: str,
    retries: int = 5,
    wait_seconds: float = 0.8,
) -> bool:
    """
    Ensure the connect-boards relationship is present by writing it and verifying
    via a readback loop. Returns True when confirmed.
    """
    if not connect_column_id:
        print("No connect column configured – skipping link ensure.")
        return False

    # Feature-detect that the connect column actually allows links to the target board
    try:
        col = client.get_column(board_id, connect_column_id)
        allowed = [str(x) for x in (col.get("connected_board_ids") or [])]
    except Exception:
        allowed = []

    # Best-effort write + verify
    for attempt in range(max(1, retries)):
        try:
            client.set_connected_items(board_id, item_id, column_id=connect_column_id, linked_item_ids=[target_item_id])
        except MondayAPIError as e:
            print(f"Connect write failed on attempt {attempt+1}: {e}")
        # read back
        try:
            data = client.get_item_values(item_id, column_ids=[connect_column_id])
            cvs = data.get("column_values") or []
            cv = cvs[0] if cvs else {}
            # prefer typed edge when available
            typed_ids = [int(i) for i in (cv.get("linked_item_ids") or [])]
            # fallback to JSON
            raw = cv.get("value") or {}
            if isinstance(raw, str) and raw and raw[0] in "{[":
                try:
                    import json as _json
                    raw = _json.loads(raw)
                except ValueError:
                    raw = {}
            json_ids = [int(i) for i in (raw.get("item_ids") or [])] if isinstance(raw, dict) else []
            present_ids = set(typed_ids or json_ids)
            if int(target_item_id) in present_ids:
                print("Confirmed connect link present.")
                return True
        except MondayAPIError as e:
            print(f"Connect readback failed on attempt {attempt+1}: {e}")

        _wait(wait_seconds)

    print("WARNING: Unable to confirm connect link after retries.")
    if allowed:
        print("Connect column is configured for boards:", allowed)
    return False


@dataclass
class PresetNames:
    workspace: str = "API_TESTS"
    board_a: str = "API_TESTS_A"
    board_b: str = "API_TESTS_B"
    group_primary: str = "topics"
    # Column titles
    title_text: str = "Text"
    title_numbers: str = "Number"
    title_status: str = "Status"
    title_date: str = "Due Date"
    title_link: str = "Link"
    title_files: str = "Files"
    title_doc: str = "Doc"
    title_people: str = "Assignee"
    title_connect: str = "Related"
    # Optional mirror column (read-only meta check)
    title_mirror: Optional[str] = None


@dataclass
class LiveOptions:
    token: str
    api_version: str
    endpoint: str
    files_endpoint: str
    max_retries: int
    backoff: float
    retries: int
    delay: float
    force_serial: bool
    step: bool
    values_cache_ttl: Optional[float]
    names: PresetNames
    purge_all_items: bool
    link_retries: int
    link_wait: float


def build_client(opts: LiveOptions) -> MondayClient:
    client = MondayClient(
        token=opts.token,
        api_version=opts.api_version,
        max_retries=opts.max_retries,
        backoff=opts.backoff,
        endpoint=opts.endpoint,
        files_endpoint=opts.files_endpoint,
    )
    client.retries = int(opts.retries)
    return client


def resolve_by_names(client: MondayClient, names: PresetNames) -> Tuple[str, str, Dict[str, str], Dict[str, str]]:
    """
    Returns: (workspace_id, board_a_id, col_ids_map, groups_map_on_a)
    col_ids_map keys: text, numbers, status, date, link, file, doc, people, connect
    Tolerant: missing columns are returned as None and should be feature-detected by callers.
    """
    # 1) Workspace ➜ ID
    workspaces = client.list_workspaces(limit=100)
    ws = next((w for w in workspaces if w["name"] == names.workspace), None)
    if not ws:
        raise ValueError(f'Workspace "{names.workspace}" not found')
    workspace_id = ws["id"]

    # 2) Boards ➜ IDs (within workspace)
    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name", "workspace_id"))
    b1 = next((b for b in boards if b["name"] == names.board_a), None)
    b2 = next((b for b in boards if b["name"] == names.board_b), None)
    if not b1:
        raise ValueError(f'Board "{names.board_a}" not found in workspace "{names.workspace}"')
    if not b2:
        raise ValueError(f'Board "{names.board_b}" not found in workspace "{names.workspace}"')
    board_a_id = b1["id"]
    board_b_id = b2["id"]

    # 3) Columns on A ➜ Map titles to IDs (tolerant)
    cols = client.get_columns(board_a_id, fields=("id", "title"))
    title_to_id = {c.get("title"): c.get("id") for c in cols}
    col_ids = {
        "text": title_to_id.get(names.title_text),
        "numbers": title_to_id.get(names.title_numbers),
        "status": title_to_id.get(names.title_status),
        "date": title_to_id.get(names.title_date),
        "link": title_to_id.get(names.title_link),
        "file": title_to_id.get(names.title_files),
        "doc": title_to_id.get(names.title_doc),
        "people": title_to_id.get(names.title_people),
        "connect": title_to_id.get(names.title_connect),
    }

    # 4) Groups on A ➜ title ➜ id (tolerant)
    groups_a = client.list_groups(board_a_id)
    groups_map = {g.get("title"): g.get("id") for g in groups_a}
    groups_map["_board_b_id"] = board_b_id

    return workspace_id, board_a_id, col_ids, groups_map


def run_flow(opts: LiveOptions) -> int:
    apply_runtime_knobs(delay=opts.delay, force_serial=opts.force_serial)
    client = build_client(opts)

    print("Starting preset OO flow against:")
    print(f"- endpoint: {client.endpoint}")
    print(f"- api_version: {client.api_version}")
    print(f"- delay: {opts.delay}s | force_serial: {opts.force_serial} | step: {opts.step}")

    try:
        step_pause(opts.step, "Resolving workspace, boards, groups and columns by names")
        ws_id, board_a_id, cols, groups = resolve_by_names(client, opts.names)
        board_b_id = groups.pop("_board_b_id")
        g_primary = groups.get(opts.names.group_primary) or groups.get("topics")
        if not g_primary:
            raise ValueError("Primary group not found on Board A")
        print("Workspace:", ws_id)
        print("Board A:", board_a_id, "Board B:", board_b_id)

        # Optional: inspect connect boards allowed IDs
        if cols.get("connect"):
            got_connect = client.get_column(board_a_id, cols["connect"])  # parse_settings=True
            allowed = got_connect.get("connected_board_ids", [])
            print("Connect boards allowed IDs:", allowed)

        step_pause(opts.step, "Init OO Session and binding boards")
        sess = Session(client, values_cache_ttl=opts.values_cache_ttl)
        bd1 = sess.board(board_a_id)
        bd2 = sess.board(board_b_id)

        # Resolve current user and ensure they can be assigned to People column
        step_pause(opts.step, "Resolving current user; ensuring board subscription")
        me = {}
        try:
            me_raw = client.me(fields=("id", "name", "email"))
            me = me_raw.get("me", me_raw) if isinstance(me_raw, dict) else {}
        except Exception:
            me = {}
        me_id = str(me.get("id")) if me.get("id") is not None else None
        if me_id:
            print("Current user:", me_id, me.get("name"), me.get("email"))
            try:
                bd1.add_subscribers([int(me_id)])
                print("Ensured current user is a subscriber on Board A")
            except MondayAPIError as e:
                print("Could not add current user as subscriber (continuing):", e)
        else:
            print("WARNING: Could not resolve current user; People assignment may be skipped")

        # Optional: show a few users for visibility
        try:
            users = client.list_users(limit=10)
            print("Users count (first 10):", len(users))
        except Exception:
            pass

        step_pause(opts.step, "Seed a target item on Board B (OO)")
        target_b_item = bd2.create_item(group_id=g_primary, item_name="preset-target")
        print("Target item on B:", target_b_item.id)

        step_pause(opts.step, "Registering webhook on Board A (OO)")
        # Build helper receive URL from config (tests/config.json -> remote_test_site)
        cfg = read_tests_config()
        base = (cfg.get("remote_test_site") or cfg.get("REMOTE_TEST_SITE"))
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
            import uuid as _uuid
            path_key = f"dev-util-test-{_uuid.uuid4().hex[:12]}"
            receive_url = f"{base}/hooks/{path_key}/"

        wh_id = None
        if receive_url:
            try:
                wh = bd1.register_webhook(url=receive_url, event=WebhookEventType.ITEM_CREATED)
                wh_id = (wh.get("id") if isinstance(wh, dict) else None)
                print("Webhook created:", wh_id or wh)
            except MondayAPIError as e:
                print("Webhook creation not permitted or unsupported (skipping):", e)
        else:
            print("remote_test_site missing in tests/config.json; skipping webhook registration")

        step_pause(opts.step, "Create main item on Board A with initial values (OO)")
        from datetime import date
        init_vals = {}
        if cols.get("text"):     init_vals[cols["text"]] = "hello"
        if cols.get("numbers"):  init_vals[cols["numbers"]] = 42
        if cols.get("status"):   init_vals[cols["status"]] = {"index": 1}
        if cols.get("date"):     init_vals[cols["date"]] = {"date": date.today().isoformat()}
        if cols.get("link"):     init_vals[cols["link"]] = {"url": "https://example.com", "text": "example"}
        if cols.get("connect"):
            init_vals[cols["connect"]] = {"item_ids": [int(target_b_item.id)]}
        item = bd1.create_item(group_id=g_primary, item_name="preset-main", values=init_vals)
        print("Item A:", item.id)

        # Assign current user to People column (safe) if available
        if cols.get("people") and me_id:
            step_pause(opts.step, "Assigning People column to the current user (safe)")
            try:
                with sess.transaction(safe=True):
                    try:
                        item.values.assignee = [int(me_id)]
                    except Exception:
                        pass
                try:
                    print("assignee now:", item.values.assignee)
                except Exception:
                    pass
            except MondayAPIError as e:
                print("People assignment failed (skipping):", e)

        step_pause(opts.step, "Reading initial values via OO")
        try:
            if hasattr(item.values, "text"):   print("text:", item.values.text)
        except Exception:
            pass
        try:
            if hasattr(item.values, "number"): print("number:", item.values.number)
        except Exception:
            pass
        try:
            if cols.get("connect"):            print("related:", item.values.related)
        except Exception:
            pass

        step_pause(opts.step, "Updating values via OO transaction (batched)")
        with sess.transaction():
            try:
                item.values.text = "world"
            except Exception:
                pass
            if cols.get("connect"):
                try:
                    item.values.related = []
                except Exception:
                    pass
        try:
            if hasattr(item.values, "text"): print("text now:", item.values.text)
        except Exception:
            pass

        if cols.get("connect"):
            step_pause(opts.step, "Re-linking via OO convenience to the target on B")
            try:
                item.set_connected_items(column_attr="related", linked_item_ids=[target_b_item.id])
                print("related now:", item.values.related)
            except MondayAPIError as e:
                print("Connect boards operation failed (skipping):", e)

        # Always attempt to ensure link via client-level helper with verification
        step_pause(opts.step, "Ensure connect link is set (write+verify loop)")
        link_ok = ensure_connect_link(
            client,
            board_id=board_a_id,
            item_id=item.id,
            connect_column_id=cols.get("connect"),
            target_item_id=str(target_b_item.id),
            retries=opts.link_retries,
            wait_seconds=opts.link_wait,
        )

        if cols.get("file"):
            step_pause(opts.step, "Uploading a file, listing and downloading via OO helpers")
            try:
                uploaded = upload_to_file_column(
                    sess,
                    item_id=item.id,
                    column_id=cols["file"],
                    file_obj=io.BytesIO(b"hello from preset oo runner\n"),
                    filename="hello.txt",
                    mime_type="text/plain",
                )
                print("Uploaded asset:", uploaded.get("id"))
                files_meta = list_files_from_column(sess, item_id=item.id, column_id=cols["file"]) 
                print("Files meta count:", len(files_meta))
                content = download_files_from_column(sess, item_id=item.id, column_id=cols["file"]) 
                print("Downloaded bytes:", len(content[0]) if content else 0)
            except MondayAPIError as e:
                print("Files operation failed (skipping):", e)

        if cols.get("doc"):
            step_pause(opts.step, "Docs: replace plain text and read back (best-effort)")
            from monpy.oo.doc import Doc  # import lazily
            try:
                Doc(id="_tmp").bind(sess).replace_plain_text("hello doc", column_item_id=item.id, column_id=cols["doc"])  # type: ignore[arg-type]
                txt = client.get_doc_text_from_column(item.id, cols["doc"])  # type: ignore[arg-type]
                print("Doc text contains:", "hello doc" in txt)
            except MondayAPIError as e:
                print("Docs not permitted or available (skipping):", e)

        step_pause(opts.step, "Safe transaction: People + Text (expect People to be skipped)")
        try:
            with sess.transaction(safe=True):
                try:
                    item.values.assignee = [987654321]  # most likely not a subscriber
                except Exception:
                    pass
                try:
                    item.values.text = "abc2"
                except Exception:
                    pass
            try:
                if hasattr(item.values, "text"): print("text after safe tx:", item.values.text)
            except Exception:
                pass
        except MondayAPIError as e:
            print("Safe tx not supported (skipping):", e)

        step_pause(opts.step, "Groups via OO (read-only)")
        groups = bd1.groups()
        print("Groups on A:", [g.get("id") for g in groups])

        # Purge – delete all items on both boards
        step_pause(opts.step, "Purging ALL items on both boards (use with care)")
        for bid in (board_a_id, board_b_id):
            try:
                print("Purging board:", bid)
                cursor = None
                while True:
                    items, cursor = client.list_items(bid, limit=500, cursor=cursor)  # type: ignore[arg-type]
                    if not items:
                        break
                    for it in items:
                        try:
                            client.delete_item(it["id"])  # permanent
                        except Exception as e:
                            print("  - delete failed for", it.get("id"), e)
                    if not cursor:
                        break
            except Exception as e:
                print("Purge failed on board", bid, e)

        print("\nPreset flow complete.")
        return 0 if link_ok else 1

    except MondayAPIError as e:
        print("API error:", e)
        return 2
    except Exception as e:
        print("Unexpected error:", e)
        return 1
    finally:
        # Best-effort webhook cleanup; preset may keep boards/items, but we can delete the webhook
        try:
            if locals().get("wh_id"):
                client = build_client(opts)
                client.delete_webhook(str(wh_id))
                print("Cleanup: webhook deleted")
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    cfg = read_tests_config()

    names_cfg = (cfg.get("PRESET_NAMES") or {})
    names = PresetNames(
        workspace=str(names_cfg.get("workspace") or "API_TESTS"),
        board_a=str(((names_cfg.get("boards") or {}).get("a")) or "API_TESTS_A"),
        board_b=str(((names_cfg.get("boards") or {}).get("b")) or "API_TESTS_B"),
        group_primary=str(((names_cfg.get("groups") or {}).get("primary")) or "topics"),
        title_text=str(((names_cfg.get("columns") or {}).get("text")) or "Text"),
        title_numbers=str(((names_cfg.get("columns") or {}).get("number")) or "Number"),
        title_status=str(((names_cfg.get("columns") or {}).get("status")) or "Status"),
        title_date=str(((names_cfg.get("columns") or {}).get("date")) or "Due Date"),
        title_link=str(((names_cfg.get("columns") or {}).get("link")) or "Link"),
        title_files=str(((names_cfg.get("columns") or {}).get("files")) or "Files"),
        title_doc=str(((names_cfg.get("columns") or {}).get("doc")) or "Doc"),
        title_people=str(((names_cfg.get("columns") or {}).get("people")) or "Assignee"),
        title_connect=str(((names_cfg.get("columns") or {}).get("connect")) or "Related"),
        title_mirror=(names_cfg.get("columns") or {}).get("mirror"),
    )

    p = argparse.ArgumentParser(description="Run the live OO flow against a preset workspace/boards (no structural mutations)")
    p.add_argument("--token", default=cfg.get("MONDAY_API_TOKEN") or cfg.get("token"), help="API token (or set in tests/config.json)")
    p.add_argument("--api-version", default=str(cfg.get("API_VERSION") or "2025-10"))
    p.add_argument("--endpoint", default=cfg.get("ENDPOINT") or "https://api.monday.com/v2")
    p.add_argument("--files-endpoint", default=cfg.get("FILES_ENDPOINT") or "https://api.monday.com/v2/file")
    p.add_argument("--max-retries", type=int, default=int(cfg.get("MAX_RETRIES") or 3))
    p.add_argument("--backoff", type=float, default=float(cfg.get("BACKOFF") or 1.0))
    p.add_argument("--retries", type=int, default=int(cfg.get("RETRIES") or 3), help="Extra 403 retries")
    p.add_argument("--delay", type=float, default=float(cfg.get("MONPY_DELAY") or 0.0), help="Artificial delay before each HTTP call")
    p.add_argument("--force-serial", action="store_true", default=bool(cfg.get("MONPY_FORCE_SERIAL") or False), help="Disable OO batching; send updates one-by-one")
    p.add_argument("--step", action="store_false", help="Pause for Enter between steps")
    p.add_argument("--values-cache-ttl", type=float, default=None, help="TTL seconds for OO item values cache")
    p.add_argument("--purge-all-items", action="store_true", help="Delete ALL items on both boards at the end (DANGEROUS)")
    p.add_argument("--link-retries", type=int, default=5, help="Retries for verifying connect link is present")
    p.add_argument("--link-wait", type=float, default=0.8, help="Seconds to wait between connect-link verification attempts")

    # Name-based configuration overrides
    p.add_argument("--workspace-name", default=names.workspace)
    p.add_argument("--board-a-name", default=names.board_a)
    p.add_argument("--board-b-name", default=names.board_b)
    p.add_argument("--group-name", default=names.group_primary)
    p.add_argument("--title-text", default=names.title_text)
    p.add_argument("--title-numbers", default=names.title_numbers)
    p.add_argument("--title-status", default=names.title_status)
    p.add_argument("--title-date", default=names.title_date)
    p.add_argument("--title-link", default=names.title_link)
    p.add_argument("--title-files", default=names.title_files)
    p.add_argument("--title-doc", default=names.title_doc)
    p.add_argument("--title-people", default=names.title_people)
    p.add_argument("--title-connect", default=names.title_connect)

    args = p.parse_args(argv)
    if not args.token:
        print("Missing API token. Provide --token or set tests/config.json with MONDAY_API_TOKEN.")
        return 3

    names = PresetNames(
        workspace=str(args.workspace_name),
        board_a=str(args.board_a_name),
        board_b=str(args.board_b_name),
        group_primary=str(args.group_name),
        title_text=str(args.title_text),
        title_numbers=str(args.title_numbers),
        title_status=str(args.title_status),
        title_date=str(args.title_date),
        title_link=str(args.title_link),
        title_files=str(args.title_files),
        title_doc=str(args.title_doc),
        title_people=str(args.title_people),
        title_connect=str(args.title_connect),
        title_mirror=names.title_mirror,
    )

    opts = LiveOptions(
        token=str(args.token),
        api_version=str(args.api_version),
        endpoint=str(args.endpoint),
        files_endpoint=str(args.files_endpoint),
        max_retries=int(args.max_retries),
        backoff=float(args.backoff),
        retries=int(args.retries),
        delay=float(args.delay),
        force_serial=bool(args.force_serial),
        step=bool(args.step),
        values_cache_ttl=float(args.values_cache_ttl) if args.values_cache_ttl is not None else None,
        names=names,
        purge_all_items=bool(args.purge_all_items),
        link_retries=int(args.link_retries),
        link_wait=float(args.link_wait),
    )

    return run_flow(opts)


if __name__ == "__main__":
    raise SystemExit(main())



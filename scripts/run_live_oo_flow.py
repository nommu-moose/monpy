from __future__ import annotations

import argparse
import json
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import requests  # noqa: E402
from monpy import MondayClient, Session  # noqa: E402
from monpy.exceptions import MondayAPIError  # noqa: E402
from monpy.oo.doc import Doc  # noqa: E402
from monpy.oo.file_asset import (  # noqa: E402
    upload_to_file_column,
    list_files_from_column,
    download_files_from_column,
)
from monpy.oo.enums import ColumnType  # noqa: E402
from monpy.oo.columns import ConnectBoardsDefaults  # noqa: E402
from monpy.oo.enums import WebhookEventType  # noqa: E402


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
    keep: bool
    values_cache_ttl: Optional[float]


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


def run_flow(opts: LiveOptions) -> int:
    apply_runtime_knobs(delay=opts.delay, force_serial=opts.force_serial)
    client = build_client(opts)

    from datetime import date
    import io
    import time

    print("Starting live OO flow against:")
    print(f"- endpoint: {client.endpoint}")
    print(f"- api_version: {client.api_version}")
    print(f"- delay: {opts.delay}s | force_serial: {opts.force_serial} | step: {opts.step}")

    ts = str(int(time.time()))
    ws = None
    b1 = None
    b2 = None

    try:
        step_pause(opts.step, "Creating workspace")
        ws = client.create_workspace(name=f"monpy-oo-int-{ts}", kind="open", description="manual run (oo)")
        print(f"Workspace: {ws['id']} {ws['name']}")

        step_pause(opts.step, "Creating two boards")
        b1_obj = Session(client).create_board(workspace_id=ws["id"], name=f"monpy-oo-board-A-{ts}")
        b2_obj = Session(client).create_board(workspace_id=ws["id"], name=f"monpy-oo-board-B-{ts}")
        b1 = {"id": b1_obj.id, "name": b1_obj.name}
        b2 = {"id": b2_obj.id, "name": b2_obj.name}
        print(f"Board A: {b1['id']}, Board B: {b2['id']}")

        step_pause(opts.step, "Init OO Session and validating workspace via board")
        sess = Session(client, values_cache_ttl=opts.values_cache_ttl)
        ws2 = client.get_workspace_for_board(b1["id"])
        print(f"Workspace via board: {ws2['id']}")
        ws_model = sess.workspace(ws["id"])  # OO
        print(f"OO Workspace name: {ws_model.name}")

        step_pause(opts.step, "Creating groups via OO Board")
        bd1 = sess.board(b1["id"])  # OO board
        bd2 = sess.board(b2["id"])  # OO board
        g1 = bd1.create_group(title="grp1")
        g2 = bd2.create_group(title="grp2")
        print(f"Groups: {g1['id']} on A, {g2['id']} on B")

        step_pause(opts.step, "Creating columns (OO)")
        cols = {}
        cols["text"] = bd1.create_column(title="Text", column_type=ColumnType.TEXT).__dict__
        cols["numbers"] = bd1.create_column(title="Number", column_type=ColumnType.NUMBER).__dict__
        cols["status"] = bd1.create_column(title="Status", column_type=ColumnType.STATUS).__dict__
        cols["date"] = bd1.create_column(title="Due Date", column_type=ColumnType.DATE).__dict__
        cols["link"] = bd1.create_column(title="Link", column_type=ColumnType.LINK).__dict__
        cols["file"] = bd1.create_column(title="Files", column_type=ColumnType.FILES).__dict__
        cols["doc"] = bd1.create_column(title="Doc", column_type=ColumnType.DOC).__dict__
        cols["people"] = bd1.create_column(title="Assignee", column_type=ColumnType.PEOPLE).__dict__
        try:
            cols["connect"] = (
                bd1.create_column(
                    title="Related",
                    column_type=ColumnType.CONNECT_BOARDS,
                    defaults=ConnectBoardsDefaults(board_ids=[int(b2["id"])], allow_multiple_items=True),
                ).__dict__
            )
        except MondayAPIError as e:
            print(f"SKIP connect boards: {e}")
            cols["connect"] = None

        bd1.refresh()
        print("Board columns now:", [c.title for c in bd1.columns._by_id.values()])

        step_pause(opts.step, "Resolving board+column IDs by names (low-level)")
        bid_resolved, col_map = client.resolve_board_and_column_ids(
            workspace_name=ws["name"],
            board_name=b1["name"],
            title_mappings={"text": "Text", "number": "Number"},
        )
        print("Resolved:", bid_resolved, col_map)

        if cols.get("connect"):
            got_connect = client.get_column(b1["id"], cols["connect"]["id"])  # parse_settings=True
            print("Connect boards allowed IDs:", got_connect.get("connected_board_ids", []))

        step_pause(opts.step, "Seeding target item on Board B (OO)")
        target_b_item = bd2.create_item(group_id=g2["id"], item_name="target")
        print("Target item on B:", target_b_item.id)

        step_pause(opts.step, "Creating main item on Board A with initial values (OO)")
        item_vals = {
            cols["text"]["id"]: "hello",
            cols["numbers"]["id"]: 42,
            cols["status"]["id"]: {"index": 1},
            cols["date"]["id"]: {"date": date.today().isoformat()},
            cols["link"]["id"]: {"url": "https://example.com", "text": "example"},
        }
        if cols.get("connect"):
            item_vals[cols["connect"]["id"]] = {"item_ids": [int(target_b_item.id)]}
        item = bd1.create_item(group_id=g1["id"], item_name="main", values=item_vals)
        print("Item A:", item.id)

        step_pause(opts.step, "Registering webhook on Board A (OO)")
        wh_id = None
        try:
            wh = bd1.register_webhook(url="https://eo4xstnn32il7em.m.pipedream.net", event=WebhookEventType.ITEM_CREATED)
            wh_id = (wh.get("id") if isinstance(wh, dict) else None)
            print("Webhook created:", wh_id or wh)
        except MondayAPIError as e:
            print("Webhook creation not permitted or unsupported (skipping):", e)

        step_pause(opts.step, "Reading initial values via OO")
        print("text:", item.values.text)
        print("number:", item.values.number)
        if cols.get("connect"):
            print("related:", item.values.related)

        step_pause(opts.step, "Updating values via OO transaction (batched)")
        with sess.transaction():
            item.values.text = "world"
            if cols.get("connect"):
                item.values.related = []
        print("text now:", item.values.text)

        if cols.get("connect"):
            step_pause(opts.step, "Re-linking via OO convenience")
            item.set_connected_items(column_attr="related", linked_item_ids=[target_b_item.id])
            print("related now:", item.values.related)

        step_pause(opts.step, "Uploading a file, listing and downloading via OO helpers")
        uploaded = upload_to_file_column(
            sess,
            item_id=item.id,
            column_id=cols["file"]["id"],
            file_obj=io.BytesIO(b"hello from manual oo runner\n"),
            filename="hello.txt",
            mime_type="text/plain",
        )
        print("Uploaded asset:", uploaded.get("id"))
        files_meta = list_files_from_column(sess, item_id=item.id, column_id=cols["file"]["id"])
        print("Files meta count:", len(files_meta))
        content = download_files_from_column(sess, item_id=item.id, column_id=cols["file"]["id"])
        print("Downloaded bytes:", len(content[0]) if content else 0)

        step_pause(opts.step, "Docs: replace plain text and read back (best-effort)")
        try:
            Doc(id="_tmp").bind(sess).replace_plain_text("hello doc", column_item_id=item.id, column_id=cols["doc"]["id"])  # type: ignore[arg-type]
            txt = client.get_doc_text_from_column(item.id, cols["doc"]["id"])
            print("Doc text contains:", "hello doc" in txt)
        except MondayAPIError as e:
            print("Docs not permitted or available:", e)

        step_pause(opts.step, "Subitems: create and update one text-like column if present")
        sub_raw = client.create_subitem(item.id, item_name="child")
        si = sess.subitem(sub_raw["id"])  # OO SubItem wrapper
        svals = client.get_subitem_values(si.id, include_board=True)
        print("Subitem board present:", bool(svals.get("board", {}).get("id")))
        # Try to find a text column on the subitems board
        cvid = None
        for cv in (svals.get("column_values") or []):
            if str(cv.get("type")).lower() in {"text", "long_text"}:
                cvid = cv.get("id")
                break
        if cvid:
            client.update_subitem_single_column(si.id, column_id=cvid, value="sub hello")
            print("Updated subitem text column:", cvid)
        else:
            print("No text-like column on subitems board; skipping update")

        step_pause(opts.step, "Verify status via direct read (low-level)")
        st = client.get_item_values(item.id, column_ids=[cols["status"]["id"]])
        st_txt = (st.get("column_values") or [{}])[0].get("text")
        print("Status text:", st_txt)

        step_pause(opts.step, "Groups and roles via OO")
        groups = bd1.groups()
        print("Groups on A:", [g.get("id") for g in groups])
        try:
            bd1.rename_group(g1["id"], title="grp1-renamed")
            print("Renamed group to 'grp1-renamed'")
        except MondayAPIError as e:
            print("Rename group unsupported on this API/version or token permissions:", e)
        roles = bd1.members_by_role()
        print("Roles keys:", sorted(roles.keys()))

        step_pause(opts.step, "Safe transaction: People + Text (expect People to be skipped)")
        with sess.transaction(safe=True):
            item.values.assignee = [987654321]  # most likely not a subscriber
            item.values.text = "abc2"
        print("text after safe tx:", item.values.text)

        print("\nFlow complete.")
        return 0

    except MondayAPIError as e:
        print("API error:", e)
        return 2
    except Exception as e:
        print("Unexpected error:", e)
        return 1
    finally:
        # Best-effort webhook cleanup first
        try:
            if locals().get("wh_id"):
                client.delete_webhook(str(wh_id))
                print("Cleanup: webhook deleted")
        except Exception:
            pass

        if not opts.keep and ws is not None:
            try:
                client.delete_workspace(ws["id"])  # irreversible at API level
                print("Cleanup: workspace deleted")
            except Exception:
                # Fall back to archiving boards if workspace deletion restricted
                for bx in (b1, b2):
                    if bx:
                        try:
                            client.archive_board(bx["id"])  # type: ignore[index]
                        except Exception:
                            pass


def main(argv: list[str] | None = None) -> int:
    cfg = read_tests_config()
    p = argparse.ArgumentParser(description="Run the live OO flow manually (no pytest)")
    p.add_argument("--token", default=cfg.get("MONDAY_API_TOKEN") or cfg.get("token"), help="API token (or set in tests/config.json)")
    p.add_argument("--api-version", default=str(cfg.get("API_VERSION") or "2025-04"))
    p.add_argument("--endpoint", default=cfg.get("ENDPOINT") or "https://api.monday.com/v2")
    p.add_argument("--files-endpoint", default=cfg.get("FILES_ENDPOINT") or "https://api.monday.com/v2/file")
    p.add_argument("--max-retries", type=int, default=int(cfg.get("MAX_RETRIES") or 3))
    p.add_argument("--backoff", type=float, default=float(cfg.get("BACKOFF") or 1.0))
    p.add_argument("--retries", type=int, default=int(cfg.get("RETRIES") or 3), help="Extra 403 retries")
    p.add_argument("--delay", type=float, default=float(cfg.get("MONPY_DELAY") or 0.0), help="Artificial delay before each HTTP call")
    p.add_argument("--force-serial", action="store_true", default=bool(cfg.get("MONPY_FORCE_SERIAL") or False), help="Disable OO batching; send updates one-by-one")
    p.add_argument("--step", action="store_false", help="Pause for Enter between steps")
    p.add_argument("--keep", action="store_false", help="Do not delete the created workspace at the end")
    p.add_argument("--values-cache-ttl", type=float, default=None, help="TTL seconds for OO item values cache")

    args = p.parse_args(argv)
    if not args.token:
        print("Missing API token. Provide --token or set tests/config.json with MONDAY_API_TOKEN.")
        return 3

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
        keep=bool(args.keep),
        values_cache_ttl=float(args.values_cache_ttl) if args.values_cache_ttl is not None else None,
    )

    return run_flow(opts)


if __name__ == "__main__":
    raise SystemExit(main())



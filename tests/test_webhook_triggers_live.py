from __future__ import annotations

import json
from datetime import date
import time
import uuid
from typing import Any, Optional

import pytest
import requests

from monpy.client import MondayClient
from monpy.oo import Session, Board
from monpy.oo import WebhookEventType
from monpy.oo import parse_webhook
from monpy.helpers import parse_monday_webhook_request
from monpy.oo.webhooks.events import (
    ItemCreatedEvent,
    ItemDeletedEvent,
    ItemArchivedEvent,
    ItemRestoredEvent,
    ItemMovedEvent,
    ItemNameChangedEvent,
    ColumnChangeEvent,
    ColumnCreatedEvent,
    UpdateCreatedEvent,
    UpdateChangedEvent,
    UpdateDeletedEvent,
    SubitemCreatedEvent,
    SubitemColumnChangeEvent,
    SubitemMovedEvent,
    SubitemArchivedEvent,
    SubitemRestoredEvent,
    SubitemDeletedEvent,
)
from monpy.exceptions import MondayAPIError, FeatureNotSupported


def _ensure_scheme(base: str) -> str:
    base = (base or "").strip()
    if base.startswith("http://") or base.startswith("https://"):
        return base
    if any(local in base for local in ("127.0.0.1", "localhost", "[::1]")):
        return f"http://{base}"
    return f"https://{base}"


def _normalize_base_url(base_url: str) -> str:
    if base_url.endswith("/"):
        return base_url[:-1]
    return base_url


def _resolve_helper_base_url(cfg: dict) -> str:
    value = (
        cfg.get("remote_test_site")
        or cfg.get("REMOTE_TEST_SITE")
    )
    if not value:
        raise RuntimeError("Missing 'remote_test_site' in tests/config.json (e.g., https://utils.today-hub.com)")
    return _normalize_base_url(_ensure_scheme(str(value)))


def _parse_mirror_to_django_like(obj: dict) -> dict:
    body = obj.get("body") or {}
    raw_bytes: bytes = b""
    b64_val = body.get("base64")
    if isinstance(b64_val, str) and b64_val.strip():
        try:
            import base64

            raw_bytes = base64.b64decode(b64_val)
        except Exception:
            raw_bytes = b""
    if not raw_bytes:
        text_val = body.get("text")
        if isinstance(text_val, str):
            raw_bytes = text_val.encode("utf-8", errors="replace")
    try:
        return json.loads(raw_bytes or b"{}")
    except ValueError:
        return {}


def _mirror_raw_bytes(obj: dict) -> bytes:
    body = obj.get("body") or {}
    b64_val = body.get("base64")
    if isinstance(b64_val, str) and b64_val.strip():
        try:
            import base64

            return base64.b64decode(b64_val)
        except Exception:
            pass
    text_val = body.get("text")
    if isinstance(text_val, str):
        try:
            return text_val.encode("utf-8", errors="replace")
        except Exception:
            return b""
    return b""


def _wait_for_event(mirror_url: str, *, expect_type: str, delays: list[int]) -> Optional[dict]:
    last_obj: Optional[dict] = None
    for d in delays:
        time.sleep(d)
        try:
            resp = requests.get(mirror_url, timeout=10)
        except requests.RequestException:
            continue
        if resp.status_code == 404:
            continue
        try:
            obj = resp.json()
        except ValueError:
            continue
        last_obj = obj
        payload = _parse_mirror_to_django_like(obj)
        if isinstance(payload, dict) and isinstance(payload.get("event"), dict):
            ev_type = str((payload.get("event") or {}).get("type") or "")
            if ev_type == expect_type:
                return payload
    return last_obj


@pytest.mark.live
@pytest.mark.webhook
@pytest.mark.slow
def test_webhook_triggers_oo_end_to_end(client_live, _test_config):
    ts = str(int(time.time()))
    sess = Session(client_live)

    base_url = _resolve_helper_base_url(_test_config)
    path_key = f"pytest-trigger-{uuid.uuid4().hex[:10]}"
    receive_url = f"{base_url}/hooks/{path_key}/"
    mirror_url = f"{base_url}/hooks/{path_key}/mirror/"

    ws = None
    wh_ids: list[str] = []
    try:
        # Workspace/board setup
        ws = client_live.create_workspace(name=f"monpy-webhook-{ts}", kind="open", description="webhook trigger live test")
        bd = sess.create_board(workspace_id=ws["id"], name=f"monpy-webhook-board-{ts}")

        # Groups
        g1 = bd.create_group(title="grp1")
        g2 = bd.create_group(title="grp2")

        # Minimal columns to drive changes
        col_text = bd.create_column(title="Text", column_type="text").__dict__["id"]
        col_status = bd.create_column(title="Status", column_type="status").__dict__["id"]
        col_date = bd.create_column(title="Due", column_type="date").__dict__["id"]

        # Register target webhooks (best-effort; some may fail due to permissions)
        desired = [
            WebhookEventType.ITEM_CREATED,
            WebhookEventType.ITEM_DELETED,
            WebhookEventType.ITEM_ARCHIVED,
            WebhookEventType.ITEM_RESTORED,
            WebhookEventType.ITEM_MOVED,
            WebhookEventType.ITEM_NAME_CHANGE,
            WebhookEventType.COLUMN_CHANGE,
            WebhookEventType.COLUMN_CREATED,
            WebhookEventType.NEW_UPDATE,
            WebhookEventType.SUBITEM_CREATED,
            WebhookEventType.SUBITEM_COLUMN_CHANGE,
            WebhookEventType.SUBITEM_MOVED,
            WebhookEventType.SUBITEM_ARCHIVED,
            WebhookEventType.SUBITEM_RESTORED,
            WebhookEventType.SUBITEM_DELETED,
            WebhookEventType.UPDATE_DELETE,
        ]
        for ev in desired:
            try:
                wh = bd.register_webhook(url=receive_url, event=ev)
                if isinstance(wh, dict) and wh.get("id"):
                    wh_ids.append(str(wh.get("id")))
            except MondayAPIError:
                continue

        if not wh_ids:
            pytest.skip("Token/account does not permit webhook creation on monday.com")

        # Ensure challenge seen before triggering events
        delays = [2, 3, 5, 8, 13]
        _ = _wait_for_event(mirror_url, expect_type="", delays=delays)  # ignore result

        # Create an item (will drive many subsequent actions)
        item = bd.create_item(group_id=g1["id"], item_name="main", values={col_text: "hello", col_status: {"index": 1}})

        # 1) ITEM_CREATED
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_CREATED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemCreatedEvent)
            # helper wrapper + type coercion (trigger_time)
            req_created = parse_monday_webhook_request(body=json.dumps(payload))
            ev_created = req_created.event
            assert isinstance(ev_created, ItemCreatedEvent)
            if getattr(ev_created, "trigger_time", None) is not None:
                assert getattr(ev_created, "trigger_time_datetime", None) is not None

        # 2) ITEM_NAME_CHANGE
        item.rename("renamed")
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_NAME_CHANGE.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemNameChangedEvent)

        # 3) COLUMN_CHANGE (Text)
        with sess.transaction():
            item.values.text = "world"
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.COLUMN_CHANGE.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            # Validate both raw OO parser and helper wrapper
            ev = parse_webhook(payload)
            assert isinstance(ev, ColumnChangeEvent)
            req = parse_monday_webhook_request(body=json.dumps(payload))
            ev2 = req.event
            assert isinstance(ev2, ColumnChangeEvent)
            # typed value available and matches new text
            tv = getattr(ev2, "typed_value", None)
            assert isinstance(tv, str)
            assert tv == "world"

        # 3b) COLUMN_CHANGE (Status)
        with sess.transaction():
            item.values.status = "Done"
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.COLUMN_CHANGE.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            req = parse_monday_webhook_request(body=json.dumps(payload))
            evs = req.event
            if isinstance(evs, ColumnChangeEvent) and getattr(evs, "column_id", None) is not None:
                # typed value should be a dict with label/index
                tvs = getattr(evs, "typed_value", None)
                assert isinstance(tvs, dict)
                assert "label" in tvs
                assert "index" in tvs

        # 3c) COLUMN_CHANGE (Date)
        with sess.transaction():
            item.values.due = date(2025, 1, 31)
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.COLUMN_CHANGE.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            req = parse_monday_webhook_request(body=json.dumps(payload))
            evd = req.event
            if isinstance(evd, ColumnChangeEvent) and getattr(evd, "column_id", None) is not None:
                tvd = getattr(evd, "typed_value", None)
                assert isinstance(tvd, date)

        # 4) COLUMN_CREATED
        _ = bd.create_column(title="Extra", column_type="text")
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.COLUMN_CREATED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ColumnCreatedEvent)

        # 5) ITEM_MOVED (to grp2)
        item.move_to_group(g2["id"])
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_MOVED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemMovedEvent)

        # 6) NEW_UPDATE (best-effort via raw mutation)
        try:
            m = "mutation ($item: ID!, $body: String!){ create_update (item_id:$item, body:$body){ id } }"
            created = client_live.mutation(m, {"item": item.id, "body": "hello from test"})
            assert created and created.get("create_update")
            payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.NEW_UPDATE.value, delays=delays)
            if isinstance(payload, dict) and payload.get("event"):
                ev = parse_webhook(payload)
                assert isinstance(ev, UpdateCreatedEvent)

            # Attempt to change the update (best-effort)
            try:
                upd_id = str((created.get("create_update") or {}).get("id"))
            except Exception:
                upd_id = None
            if upd_id:
                m2 = "mutation ($id: ID!, $body: String!){ edit_update (id:$id, body:$body){ id } }"
                try:
                    changed = client_live.mutation(m2, {"id": upd_id, "body": "updated body"})
                    if changed and changed.get("edit_update"):
                        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.UPDATE_CHANGE.value, delays=delays)
                        if isinstance(payload, dict) and payload.get("event"):
                            ev = parse_webhook(payload)
                            assert isinstance(ev, UpdateChangedEvent)
                except MondayAPIError:
                    pass

                # Attempt to delete the update (best-effort)
                m3 = "mutation ($id: ID!){ delete_update (id:$id){ id } }"
                try:
                    deleted = client_live.mutation(m3, {"id": upd_id})
                    if deleted and deleted.get("delete_update"):
                        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.UPDATE_DELETE.value, delays=delays)
                        if isinstance(payload, dict) and payload.get("event"):
                            ev = parse_webhook(payload)
                            assert isinstance(ev, UpdateDeletedEvent)
                except MondayAPIError:
                    pass
        except MondayAPIError:
            pass

        # 7) SUBITEM_CREATED / SUBITEM_COLUMN_CHANGE
        try:
            sub = client_live.create_subitem(item.id, item_name="child")
            payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_CREATED.value, delays=delays)
            if isinstance(payload, dict) and payload.get("event"):
                ev = parse_webhook(payload)
                assert isinstance(ev, SubitemCreatedEvent)
            # change subitem text (reuse Text column id)
            client_live.update_subitem_single_column(sub["id"], column_id=col_text, value="sub hello")
            payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_COLUMN_CHANGE.value, delays=delays)
            if isinstance(payload, dict) and payload.get("event"):
                ev = parse_webhook(payload)
                assert isinstance(ev, SubitemColumnChangeEvent)

            # move subitem to a new group on subitems board (best-effort)
            try:
                sub_board_id = client_live._get_board_id_for_subitem(sub["id"])  # type: ignore[attr-defined]
                grp = client_live.create_group(sub_board_id, title="subgrp2")
                client_live.move_item_to_group(sub["id"], group_id=grp["id"])  # uses generic move mutation
                payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_MOVED.value, delays=delays)
                if isinstance(payload, dict) and payload.get("event"):
                    ev = parse_webhook(payload)
                    assert isinstance(ev, SubitemMovedEvent)
            except MondayAPIError:
                pass

            # archive/unarchive subitem
            try:
                client_live.archive_item(sub["id"])  # generic archive works for subitems
                payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_ARCHIVED.value, delays=delays)
                if isinstance(payload, dict) and payload.get("event"):
                    ev = parse_webhook(payload)
                    assert isinstance(ev, SubitemArchivedEvent)
                client_live.unarchive_item(sub["id"])  # restore
                payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_RESTORED.value, delays=delays)
                if isinstance(payload, dict) and payload.get("event"):
                    ev = parse_webhook(payload)
                    assert isinstance(ev, SubitemRestoredEvent)
            except MondayAPIError:
                pass

            # delete subitem
            try:
                client_live.delete_item(sub["id"])  # remove
                payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.SUBITEM_DELETED.value, delays=delays)
                if isinstance(payload, dict) and payload.get("event"):
                    ev = parse_webhook(payload)
                    assert isinstance(ev, SubitemDeletedEvent)
            except MondayAPIError:
                pass
        except MondayAPIError:
            pass

        # 8) ITEM_ARCHIVED / ITEM_RESTORED
        item.archive()
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_ARCHIVED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemArchivedEvent)

        item.unarchive()
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_RESTORED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemRestoredEvent)

        # 9) ITEM_DELETED (last)
        item.delete()
        payload = _wait_for_event(mirror_url, expect_type=WebhookEventType.ITEM_DELETED.value, delays=delays)
        if isinstance(payload, dict) and payload.get("event"):
            ev = parse_webhook(payload)
            assert isinstance(ev, ItemDeletedEvent)
            # helper wrapper + type coercion (trigger_time)
            req_deleted = parse_monday_webhook_request(body=json.dumps(payload))
            ev_deleted = req_deleted.event
            assert isinstance(ev_deleted, ItemDeletedEvent)
            if getattr(ev_deleted, "trigger_time", None) is not None:
                assert getattr(ev_deleted, "trigger_time_datetime", None) is not None

    finally:
        # Cleanup webhooks first (best-effort)
        for wid in wh_ids:
            try:
                client_live.delete_webhook(wid)
            except Exception:
                pass
        # Cleanup workspace
        if ws is not None:
            try:
                client_live.delete_workspace(ws["id"])  # irreversible
            except Exception:
                pass



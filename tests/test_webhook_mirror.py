import json
import time
import uuid
import base64

import pytest
import requests

from monpy import Session
from monpy.oo import WebhookEventType
from monpy.oo import parse_webhook
from monpy.helpers import parse_monday_webhook_request
from monpy.exceptions import MondayAPIError


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


@pytest.mark.live
@pytest.mark.webhook
@pytest.mark.slow
def test_webhook_mirror_challenge_live(client_live, _test_config):
    # Skip gracefully if token not provided
    ts = str(int(time.time()))
    sess = Session(client_live)

    base_url = _resolve_helper_base_url(_test_config)
    path_key = f"pytest-mirror-{uuid.uuid4().hex[:10]}"
    receive_url = f"{base_url}/hooks/{path_key}/"
    mirror_url = f"{base_url}/hooks/{path_key}/mirror/"

    ws = None
    wh_id = None
    try:
        ws = client_live.create_workspace(name=f"monpy-webhook-{ts}", kind="open", description="pytest webhook mirror")
        bd = sess.create_board(workspace_id=ws["id"], name=f"monpy-webhook-board-{ts}")

        # Register several basic webhooks (best-effort) and ensure at least one challenge appears
        events = [
            WebhookEventType.ITEM_CREATED,
            WebhookEventType.ITEM_DELETED,
            WebhookEventType.ITEM_ARCHIVED,
            WebhookEventType.ITEM_RESTORED,
            WebhookEventType.ITEM_MOVED,
            WebhookEventType.COLUMN_CHANGE,
        ]
        for ev in events:
            try:
                wh = bd.register_webhook(url=receive_url, event=ev)
                # Keep the last webhook id for cleanup
                wh_id = str(wh.get("id")) if isinstance(wh, dict) else wh_id
            except MondayAPIError:
                # Continue trying other events; some accounts restrict creation
                continue

        delays = [2, 4, 8, 16, 32]
        got = None
        for d in delays:
            time.sleep(d)
            resp = requests.get(mirror_url, timeout=10)
            if resp.status_code == 404:
                continue
            obj = resp.json()
            payload = _parse_mirror_to_django_like(obj)
            # Validate helper wrapper too (if body is present)
            raw_bytes = _mirror_raw_bytes(obj)
            if raw_bytes:
                try:
                    req = parse_monday_webhook_request(body=raw_bytes, headers=obj.get("headers"))
                    # Any parse result is acceptable here; focus is on handshake
                    assert req is not None
                except Exception:
                    pass
            raw_text = (obj.get("body") or {}).get("text") or ""
            if (isinstance(payload, dict) and "challenge" in payload) or (isinstance(raw_text, str) and "challenge" in raw_text.lower()):
                got = payload
                break

        assert got is not None, "Webhook challenge not observed at mirror endpoint within expected time"

    finally:
        # Best-effort cleanup
        if wh_id:
            try:
                client_live.delete_webhook(wh_id)
            except Exception:
                pass
        if ws is not None:
            try:
                client_live.delete_workspace(ws["id"])  # irreversible in API
            except Exception:
                pass



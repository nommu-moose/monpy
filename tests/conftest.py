import json
from pathlib import Path
import threading
import requests
import pytest
from monpy import MondayClient
from monpy.oo.session import Session
from monpy.exceptions import FeatureNotSupported
import uuid
from typing import NamedTuple
import time


class WebhookReceiver(NamedTuple):
    base_url: str
    path_key: str
    receive_url: str
    mirror_url: str

    def wait_for_event(self, *, expect_type: str, delays: list[int] | None = None) -> dict | None:
        """Poll the mirror URL until an event of `expect_type` is seen.

        Returns the parsed JSON body of the webhook payload, or the last seen object
        if the expected event type is not found after all delays.
        """
        delays = delays or [2, 3, 5, 8, 13]
        for d in delays:
            time.sleep(d)
            try:
                resp = requests.get(self.mirror_url, timeout=10)
            except requests.RequestException:
                continue
            if resp.status_code == 404:
                continue
            try:
                obj = resp.json()
            except ValueError:
                continue
            
            body_bytes = b""
            body_b64 = (obj.get("body") or {}).get("base64")
            if isinstance(body_b64, str):
                try:
                    import base64
                    body_bytes = base64.b64decode(body_b64)
                except Exception:
                    pass
            
            payload: dict | None = None
            if body_bytes:
                try:
                    payload = json.loads(body_bytes)
                except (ValueError, TypeError):
                    pass
            
            if isinstance(payload, dict):
                if "challenge" in payload and expect_type == "":
                    return payload
                if isinstance(payload.get("event"), dict):
                    ev_type = str((payload.get("event") or {}).get("type") or "")
                    if ev_type == expect_type:
                        return payload
        return None


@pytest.fixture(scope="function")
def webhook_receiver(_test_config: dict) -> WebhookReceiver:
    """Fixture to generate a unique webhook URL for a test function."""
    base_url_raw = _test_config.get("remote_test_site") or _test_config.get("REMOTE_TEST_SITE")
    if not base_url_raw:
        pytest.skip("Webhook tests require 'remote_test_site' in tests/config.json")
    
    base_url = str(base_url_raw).rstrip("/")
    path_key = f"pytest-wh-{uuid.uuid4().hex[:10]}"
    
    return WebhookReceiver(
        base_url=base_url,
        path_key=path_key,
        receive_url=f"{base_url}/hooks/{path_key}/",
        mirror_url=f"{base_url}/hooks/{path_key}/mirror/",
    )


def _load_config() -> dict:
    cfg = Path(__file__).parent / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


@pytest.fixture(scope="session")
def _test_config() -> dict:
    return _load_config()


@pytest.fixture(scope="session")
def client_live(_test_config: dict):
    token = (_test_config.get("MONDAY_API_TOKEN") or _test_config.get("token"))
    if not token:
        pytest.skip(
            "Live tests require tests/config.json with MONDAY_API_TOKEN",
            allow_module_level=True,
        )

    # Optional client tuning via config.json (no env vars)
    api_version = _test_config.get("API_VERSION") or "2025-10"
    def _as_int(val, default):
        try:
            return int(val)
        except Exception:
            return default
    def _as_float(val, default):
        try:
            return float(val)
        except Exception:
            return default

    max_retries = _as_int(_test_config.get("MAX_RETRIES"), 3)
    backoff = _as_float(_test_config.get("BACKOFF"), 1.0)
    endpoint = _test_config.get("ENDPOINT") or "https://api.monday.com/v2"
    files_endpoint = _test_config.get("FILES_ENDPOINT") or "https://api.monday.com/v2/file"

    client = MondayClient(
        token=token,
        api_version=str(api_version),
        max_retries=max_retries,
        backoff=backoff,
        endpoint=endpoint,
        files_endpoint=files_endpoint,
        dev_mode=True,
    )

    # Additional 403-retry knob
    client.retries = _as_int(_test_config.get("RETRIES"), 0)
    # Allow overriding dev mode via tests/config.json if needed
    try:
        dm = _test_config.get("DEV_MODE")
        if dm is not None:
            if isinstance(dm, str):
                enabled = dm.strip().lower() in {"1", "true", "yes", "y"}
            else:
                enabled = bool(dm)
            client.set_dev_mode(enabled)
    except Exception:
        pass
    return client


def _wait(seconds: float) -> None:
    try:
        sec = float(seconds)
    except Exception:
        return
    if sec > 0:
        # Use Event().wait to avoid interaction with tests that monkeypatch time.sleep
        threading.Event().wait(sec)


@pytest.fixture(autouse=True)
def _runtime_behaviour(_test_config: dict, monkeypatch):
    """
    Optional runtime knobs driven by tests/config.json (no environment variables):
      - MONPY_DELAY: seconds to wait before every HTTP call
      - MONPY_FORCE_SERIAL: if truthy, disable OO-layer batching and send updates one-by-one
    """
    delay_raw = _test_config.get("MONPY_DELAY")
    force_serial_raw = _test_config.get("MONPY_FORCE_SERIAL")

    # Normalize values
    try:
        delay = float(delay_raw) if delay_raw is not None else 0.0
    except Exception:
        delay = 0.0
    force_serial = False
    if isinstance(force_serial_raw, str):
        force_serial = force_serial_raw.strip().lower() in {"1", "true", "yes", "y"}
    elif isinstance(force_serial_raw, (int, float)):
        force_serial = bool(force_serial_raw)
    elif isinstance(force_serial_raw, bool):
        force_serial = force_serial_raw

    # Apply per-request artificial delay
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

        monkeypatch.setattr(requests.Session, "post", delayed_sess_post, raising=True)
        monkeypatch.setattr(requests, "post", delayed_post, raising=True)
        monkeypatch.setattr(requests, "get", delayed_get, raising=True)

    # Disable OO batching if requested – send updates serially
    if force_serial:
        def _serial_execute(self, updates):
            for board_id, item_id, values in updates:
                if delay > 0:
                    _wait(delay)
                self.client.update_item_values(board_id, item_id, column_values=values)

        monkeypatch.setattr(Session, "_execute_batched_item_updates", _serial_execute, raising=True)



# Live test shared environment: ephemeral workspace/boards/columns reused per module
@pytest.fixture(scope="module")
def live_env(client_live, _test_config):
    """
    Create one workspace, two boards, primary groups, and a standard set of columns on board A.
    Yields a context dict and performs best-effort cleanup at the end.
    """
    prefix = f"monpy-int-{uuid.uuid4().hex[:8]}"
    ws = client_live.create_workspace(name=f"{prefix}-ws", kind="open", description="module live env")
    b1 = client_live.create_board(name=f"{prefix}-A", board_kind="public", workspace_id=ws["id"])  # main board
    b2 = client_live.create_board(name=f"{prefix}-B", board_kind="public", workspace_id=ws["id"])  # related board
    g1 = client_live.create_group(b1["id"], title="grp1")
    g2 = client_live.create_group(b2["id"], title="grp2")

    sess = Session(client_live)
    bd1 = sess.board(b1["id"])  # OO wrappers for board A
    bd2 = sess.board(b2["id"])  # OO wrappers for board B

    cols = {}
    cols["text"] = bd1.create_column(title="Text", column_type="text").__dict__
    cols["numbers"] = bd1.create_column(title="Number", column_type="numbers").__dict__
    cols["status"] = bd1.create_column(title="Status", column_type="status").__dict__
    cols["date"] = bd1.create_column(title="Due Date", column_type="date").__dict__
    cols["link"] = bd1.create_column(title="Link", column_type="link").__dict__
    cols["file"] = bd1.create_column(title="Files", column_type="file").__dict__
    cols["doc"] = bd1.create_column(title="Doc", column_type="doc").__dict__
    try:
        cols["location"] = bd1.create_column(title="Location", column_type="location").__dict__
    except Exception:
        cols["location"] = None
    cols["people"] = bd1.create_column(title="Assignee", column_type="people").__dict__
    try:
        cols["connect"] = bd1.create_column(
            title="Related",
            column_type="connect_boards",
            defaults={"boardIds": [int(b2["id"])], "allowMultipleItems": True},
        ).__dict__
    except FeatureNotSupported:
        cols["connect"] = None

    bd1.refresh()

    ctx = {
        "prefix": prefix,
        "ws": ws,
        "b1": b1,
        "b2": b2,
        "g1": g1,
        "g2": g2,
        "sess": sess,
        "bd1": bd1,
        "bd2": bd2,
        "cols": cols,
        "webhook_url_base": _test_config.get("remote_test_site")
    }

    try:
        yield ctx
    finally:
        # Cleanup workspace removes contained boards/items; best-effort
        try:
            client_live.delete_workspace(ws["id"])  # irreversible in API
        except Exception:
            try:
                client_live.archive_board(b1["id"])  # type: ignore[name-defined]
            except Exception:
                pass
            try:
                client_live.archive_board(b2["id"])  # type: ignore[name-defined]
            except Exception:
                pass

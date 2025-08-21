import json
from pathlib import Path
import threading
import requests
import pytest
from monpy import MondayClient
from monpy.oo.session import Session


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
    )

    # Additional 403-retry knob
    client.retries = _as_int(_test_config.get("RETRIES"), 0)
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



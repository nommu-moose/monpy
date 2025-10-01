from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import base64  # noqa: E402
import requests  # noqa: E402
from monpy import MondayClient, Session  # noqa: E402
from monpy.exceptions import MondayAPIError  # noqa: E402
from monpy.oo.enums import WebhookEventType  # noqa: E402


def _read_tests_config() -> dict:
    cfg = ROOT / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _ensure_scheme(base: str) -> str:
    base = (base or "").strip()
    if base.startswith("http://") or base.startswith("https://"):
        return base
    # Use https for non-local hosts by default
    if any(local in base for local in ("127.0.0.1", "localhost", "[::1]")):
        return f"http://{base}"
    return f"https://{base}"


def _normalize_base_url(base_url: str) -> str:
    if base_url.endswith("/"):
        return base_url[:-1]
    return base_url


def _resolve_helper_base_url(conf: Dict[str, Any]) -> str:
    # Require explicit helper site in tests/config.json; do not hardcode defaults
    value: Optional[str] = (
        conf.get("remote_test_site")
        or conf.get("REMOTE_TEST_SITE")
    )
    if not value:
        raise RuntimeError(
            "Missing 'remote_test_site' in tests/config.json (e.g., https://utils.today-hub.com)"
        )
    value = _ensure_scheme(str(value))
    return _normalize_base_url(value)


@dataclass
class ClientOptions:
    token: str
    api_version: str
    endpoint: str
    files_endpoint: str
    max_retries: int
    backoff: float
    retries: int


def _build_client(opts: ClientOptions) -> MondayClient:
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


def _parse_mirror_payload_to_django_like(payload: dict) -> dict:
    """
    Recreate what a Django view would parse via json.loads(request.body).
    Mirrors scripts/webhook_roundtrip.py behaviour for parity.
    """
    body = payload.get("body") or {}
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


def _print_overview(label: str, resp: requests.Response) -> None:
    print(f"\n== {label} ==")
    print(f"status_code: {resp.status_code}")
    try:
        obj = resp.json()
    except ValueError:
        print("(no JSON body)")
        return
    print("parsed JSON (pretty):")
    print(json.dumps(obj, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    cfg = _read_tests_config()
    token = (cfg.get("MONDAY_API_TOKEN") or cfg.get("token"))
    if not token:
        print("Missing MONDAY_API_TOKEN in tests/config.json", file=sys.stderr)
        return 3

    api_version = str(cfg.get("API_VERSION") or "2025-10")
    endpoint = str(cfg.get("ENDPOINT") or "https://api.monday.com/v2")
    files_endpoint = str(cfg.get("FILES_ENDPOINT") or "https://api.monday.com/v2/file")
    max_retries = int(cfg.get("MAX_RETRIES") or 3)
    backoff = float(cfg.get("BACKOFF") or 1.0)
    retries = int(cfg.get("RETRIES") or 0)

    client = _build_client(ClientOptions(
        token=token,
        api_version=api_version,
        endpoint=endpoint,
        files_endpoint=files_endpoint,
        max_retries=max_retries,
        backoff=backoff,
        retries=retries,
    ))

    base_url = _resolve_helper_base_url(cfg)

    # Unique path for this run; mirror endpoint will expose the first request it sees
    path_key = f"dev-util-test-{uuid.uuid4().hex[:12]}"
    receive_url = f"{base_url}/hooks/{path_key}/"
    mirror_url = f"{base_url}/hooks/{path_key}/mirror/"

    ws = None
    wh_id: Optional[str] = None

    try:
        # Create minimal workspace+board and register webhook via OO wrappers
        sess = Session(client)
        ts = str(int(time.time()))
        ws = client.create_workspace(name=f"monpy-webhook-{ts}", kind="open", description="webhook mirror helper run")
        bd = sess.create_board(workspace_id=ws["id"], name=f"monpy-webhook-board-{ts}")

        try:
            wh = bd.register_webhook(url=receive_url, event=WebhookEventType.ITEM_CREATED)
            wh_id = str(wh.get("id")) if isinstance(wh, dict) else None
        except MondayAPIError as e:
            print("Webhook creation not permitted or unsupported:", e, file=sys.stderr)
            return 2

        # Poll the mirror with exponential backoff: 2, 4, 8, 16, 32 seconds
        delays = [2, 4, 8, 16, 32]
        last_resp: Optional[requests.Response] = None
        django_like_payload: dict = {}
        for idx, d in enumerate(delays):
            time.sleep(d)
            try:
                resp = requests.get(mirror_url, timeout=10)
            except requests.RequestException as exc:
                print(f"GET mirror attempt {idx+1} failed: {exc}", file=sys.stderr)
                continue
            last_resp = resp
            if resp.status_code == 404:
                # Not yet stored/propagated
                continue
            _print_overview("GET mirror response", resp)
            try:
                obj = resp.json()
            except ValueError:
                continue
            django_like_payload = _parse_mirror_payload_to_django_like(obj)
            # Consider the challenge successful if payload contains a 'challenge' key
            # or raw text mentions 'challenge'.
            body = (obj.get("body") or {})
            raw_text = body.get("text") or ""
            has_challenge = (
                (isinstance(django_like_payload, dict) and "challenge" in django_like_payload)
                or (isinstance(raw_text, str) and "challenge" in raw_text.lower())
            )
            if has_challenge:
                print("\nChallenge detected in mirror payload.")
                print("django_like_payload:")
                print(json.dumps(django_like_payload, indent=2, sort_keys=True))
                break
        else:
            # Exhausted without detecting challenge
            msg = (
                "Webhook challenge was not observed at mirror endpoint after waits "
                + ", ".join(str(x) for x in delays)
                + " seconds"
            )
            raise RuntimeError(msg)

        return 0

    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 4
    finally:
        # Best-effort cleanup
        if wh_id:
            try:
                client.delete_webhook(wh_id)
            except Exception:
                pass
        if ws is not None:
            try:
                client.delete_workspace(ws["id"])  # irreversible
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())



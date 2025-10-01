import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import requests
import base64


def _load_conf(conf_path: Path) -> Dict[str, Any]:
    if not conf_path.exists():
        print(f"config file not found at: {conf_path}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(conf_path.read_text() or "{}")
    except json.JSONDecodeError as exc:
        print(f"failed to parse conf.json: {exc}", file=sys.stderr)
        sys.exit(1)


def _ensure_scheme(base: str) -> str:
    base = base.strip()
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


def _resolve_base_url(conf: Dict[str, Any]) -> str:
    # Prefer explicit remote_test_site (snake or upper)
    value: Optional[str] = (
        conf.get("remote_test_site")
        or conf.get("REMOTE_TEST_SITE")
    )
    if not value:
        # Fallback: try first allowed host
        allowed = conf.get("ALLOWED_HOSTS") or []
        if isinstance(allowed, list) and allowed:
            value = str(allowed[0])
        else:
            value = "127.0.0.1:8000"
        print(
            f"remote_test_site missing in conf.json; falling back to {value}",
            file=sys.stderr,
        )
    value = _ensure_scheme(str(value))
    return _normalize_base_url(value)


def _resolve_request_options(conf: Dict[str, Any]) -> Dict[str, Any]:
    opts: Dict[str, Any] = {}
    rt = conf.get("webhook_roundtrip") or {}
    headers = rt.get("headers") or {}
    timeout_seconds = rt.get("timeout_seconds")
    if isinstance(headers, dict):
        opts["headers"] = {str(k): str(v) for k, v in headers.items()}
    if isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0:
        opts["timeout"] = float(timeout_seconds)
    return opts


def _print_raw_and_parsed(label: str, resp: requests.Response) -> None:
    print(f"\n== {label} ==")
    print(f"status_code: {resp.status_code}")
    print("-- raw response text (begin) --")
    print(resp.text)
    print("-- raw response text (end) --")
    try:
        obj = resp.json()
    except ValueError:
        print("(no JSON body)")
        return
    print("parsed JSON (pretty):")
    print(json.dumps(obj, indent=2, sort_keys=True))


def _print_mirror_components(obj: Dict[str, Any]) -> None:
    # Print all top-level components explicitly
    print("\n== Mirror JSON components ==")
    for key in ("path_key", "method", "content_type", "client_ip", "created_at"):
        print(f"{key}: {obj.get(key)}")
    print("headers:")
    print(json.dumps(obj.get("headers"), indent=2, sort_keys=True))
    print("query_params:")
    print(json.dumps(obj.get("query_params"), indent=2, sort_keys=True))
    body = obj.get("body") or {}
    print("body.base64:")
    print(body.get("base64"))
    print("body.text:")
    print(body.get("text"))
    # Recreate what a Django view would parse via json.loads(request.body)
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
        django_like_payload = json.loads(raw_bytes or b"{}")
    except ValueError:
        django_like_payload = {}
    print("\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\nbody.parsed_json_like_django (json.loads(request.body)):")
    print(json.dumps(django_like_payload, indent=2, sort_keys=True))
    print("\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n")


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    conf_path = project_root / "config" / "conf.json"
    # Fallback to tests/config.json if dedicated config not present
    if not conf_path.exists():
        alt = project_root / "tests" / "config.json"
        if alt.exists():
            conf_path = alt

    conf = _load_conf(conf_path)
    base_url = _resolve_base_url(conf)

    # Use a unique path_key for this test
    path_key = f"dev-util-test-{uuid.uuid4().hex[:12]}"
    receive_url = f"{base_url}/hooks/{path_key}/"
    mirror_url = f"{base_url}/hooks/{path_key}/mirror/"

    payload = {
        "event": "roundtrip_test",
        "message": "hello from webhook_roundtrip.py",
        "uuid": uuid.uuid4().hex,
        "sent_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    request_opts = _resolve_request_options(conf)

    try:
        post_resp = requests.post(
            receive_url,
            json=payload,
            headers=request_opts.get("headers") or {"X-Webhook-Test": "true"},
            timeout=request_opts.get("timeout") or 10,
        )
    except requests.RequestException as exc:
        print(f"POST failed: {exc}", file=sys.stderr)
        return 2

    _print_raw_and_parsed("POST /hooks/<path_key>/ response", post_resp)

    # Fetch mirror, retry briefly in case of storage latency
    get_resp: Optional[requests.Response] = None
    for attempt in range(5):
        try:
            resp = requests.get(
                mirror_url,
                timeout=request_opts.get("timeout") or 10,
                headers=request_opts.get("headers") or None,
            )
        except requests.RequestException as exc:
            print(f"GET attempt {attempt+1} failed: {exc}", file=sys.stderr)
            time.sleep(0.3)
            continue
        if resp.status_code == 404 and attempt < 4:
            time.sleep(0.3)
            continue
        get_resp = resp
        break

    if get_resp is None:
        print("failed to GET mirror response", file=sys.stderr)
        return 3

    _print_raw_and_parsed("GET /hooks/<path_key>/mirror/ response", get_resp)

    try:
        mirror_obj = get_resp.json()
    except ValueError:
        return 0
    _print_mirror_components(mirror_obj)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

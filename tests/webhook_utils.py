import requests
import base64
import json
from datetime import datetime
from typing import NamedTuple, Optional, Dict, Any, Union, List


class MirrorResponse(NamedTuple):
    path_key: Optional[str]
    method: Optional[str]
    headers: Dict[str, str]
    query_params: Dict[str, List[str]]
    content_type: Optional[str]
    client_ip: Optional[str]
    created_at: Optional[Union[datetime, str]]
    body_b64: str
    body_text: Optional[str]
    body_json: Optional[Any]
    raw_bytes: bytes


def expect_webhook_events(url: str, timeout: int = 10) -> MirrorResponse:
    # Retrieve the mirror payload
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()  # raise for non-2xx responses
    payload = resp.json()

    # Parse components
    path_key = payload.get("path_key")
    method = payload.get("method")
    headers = payload.get("headers", {})  # dict
    query_params = payload.get("query_params", {})  # dict of lists
    content_type = payload.get("content_type", "")
    client_ip = payload.get("client_ip")
    created_at_iso = payload.get("created_at")

    # Convert created_at to datetime if present
    created_at: Optional[Union[datetime, str]] = None
    if created_at_iso:
        try:
            created_at = datetime.fromisoformat(created_at_iso)
        except Exception:
            created_at = created_at_iso  # keep raw if parsing fails

    # Body: base64 and text representations
    body = payload.get("body", {})
    body_b64 = body.get("base64", "") or ""
    body_text = body.get("text")  # may be None

    raw_bytes = base64.b64decode(body_b64) if body_b64 else b""

    # Best-effort JSON parse of body
    body_json: Optional[Any] = None
    if body_text is not None:
        try:
            body_json = json.loads(body_text)
        except Exception:
            body_json = None
    else:
        # try decode raw bytes then parse
        try:
            decoded = raw_bytes.decode("utf-8")
            body_text = decoded
            body_json = json.loads(decoded)
        except Exception:
            # keep `body_text` as a UTF-8 fallback if possible
            try:
                body_text = raw_bytes.decode("utf-8", errors="replace") if raw_bytes else None
            except Exception:
                body_text = None

    return MirrorResponse(
        path_key=path_key,
        method=method,
        headers=headers,
        query_params=query_params,
        content_type=content_type,
        client_ip=client_ip,
        created_at=created_at,
        body_b64=body_b64,
        body_text=body_text,
        body_json=body_json,
        raw_bytes=raw_bytes,
    )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional

from monpy.oo import parse_webhook, verify_signature
from monpy.oo.webhooks.events import WebhookEvent


def _to_bytes(body: Any) -> Optional[bytes]:
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    if isinstance(body, str):
        try:
            return body.encode("utf-8")
        except Exception:
            return None
    return None


def _ensure_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        try:
            s = bytes(payload).decode("utf-8")
        except Exception:
            return {}
        try:
            import json as _json

            return _json.loads(s)
        except Exception:
            return {}
    if isinstance(payload, str):
        try:
            import json as _json

            return _json.loads(payload)
        except Exception:
            return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _get_header(headers: Optional[Mapping[str, str]], name: str) -> Optional[str]:
    if not headers:
        return None
    target = name.lower()
    for k, v in headers.items():
        try:
            if str(k).lower() == target:
                return None if v is None else str(v)
        except Exception:
            continue
    return None


@dataclass
class MondayWebhookRequest:
    """
    Parsed monday.com webhook request wrapper.

    - `event`: typed `WebhookEvent` instance from the OO layer
    - `is_challenge` / `challenge`: URL verification handshake data
    - `signature_valid`: result of HMAC validation (None if not attempted)
    - `is_retry`: whether monday flagged the delivery as a retry
    - `raw`: original request body parsed as dict
    """

    event: WebhookEvent
    is_challenge: bool = False
    challenge: Optional[str] = None
    signature_valid: Optional[bool] = None
    is_retry: bool = False
    headers: Optional[Mapping[str, str]] = field(default=None, repr=False)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


def parse_monday_webhook_request(
    body: Any,
    *,
    headers: Optional[Mapping[str, str]] = None,
    signing_secret: Optional[str] = None,
) -> MondayWebhookRequest:
    """
    Parse a monday.com webhook HTTP request into a structured object.

    Parameters
    ----------
    body
        Raw request body. Accepts bytes, str (JSON), or dict.
    headers
        Optional HTTP headers mapping for signature verification.
    signing_secret
        If provided, validates `X-Monday-Signature` against the raw body.

    Returns
    -------
    MondayWebhookRequest
        A convenience wrapper exposing `event` and handshake/signature info.
    """

    raw_dict = _ensure_dict(body)

    # Determine handshake/challenge
    challenge = raw_dict.get("challenge")
    is_challenge = challenge is not None

    # Retry hint (present on real deliveries under event.isRetry)
    ev_obj = raw_dict.get("event") or {}
    is_retry = bool(ev_obj.get("isRetry", False))

    # Typed event from the OO layer (falls back to base WebhookEvent)
    event = parse_webhook(body)

    # Optional signature verification
    signature_valid: Optional[bool] = None
    if signing_secret:
        sig_header = _get_header(headers, "X-Monday-Signature")
        raw_bytes = _to_bytes(body)
        if sig_header is not None and raw_bytes is not None:
            try:
                signature_valid = verify_signature(
                    secret=str(signing_secret), body=raw_bytes, header_signature=sig_header
                )
            except Exception:
                signature_valid = False

    return MondayWebhookRequest(
        event=event,
        is_challenge=is_challenge,
        challenge=str(challenge) if challenge is not None else None,
        signature_valid=signature_valid,
        is_retry=is_retry,
        headers=headers,
        raw=raw_dict,
    )



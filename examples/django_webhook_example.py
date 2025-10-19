from __future__ import annotations

import os
from typing import Any, Mapping, Optional
from dataclasses import asdict, fields
from datetime import date, datetime
import json

# Copy this into your Django project (e.g., views.py)
from django.http import HttpRequest, JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt

from monpy.helpers import parse_monday_webhook_request
from monpy.oo.webhooks.events import ColumnChangeEvent, SubitemColumnChangeEvent
from monpy.oo.columns.values import LocationValue


# Configure via environment variable in your deployment
MONDAY_WEBHOOK_SECRET = os.environ.get("MONDAY_WEBHOOK_SECRET")


def _extract_headers(request: HttpRequest) -> Mapping[str, str]:
    """Return a case-insensitive mapping of HTTP headers.

    Works across Django versions by preferring `request.headers` and
    falling back to `request.META`.
    """
    try:
        hdrs = getattr(request, "headers", None)
        if hdrs and hasattr(hdrs, "items"):
            return {str(k): str(v) for k, v in hdrs.items()}
    except Exception:
        pass

    # Fallback for older Django versions
    try:
        meta = getattr(request, "META", {}) or {}
        # Convert HTTP_FOO_BAR -> Foo-Bar; include common direct keys
        out: dict[str, str] = {}
        for k, v in meta.items():
            if not isinstance(k, str):
                continue
            if k.startswith("HTTP_"):
                name = k[5:].replace("_", "-").title()
                out[name] = str(v)
            elif k in {"CONTENT_TYPE", "CONTENT_LENGTH"}:
                out[k.replace("_", "-").title()] = str(v)
        return out
    except Exception:
        return {}


def _parse_iso8601_to_datetime(s: Optional[str]) -> Optional[datetime]:
    if not s or not isinstance(s, str):
        return None
    try:
        # Handle trailing 'Z' (UTC) by converting to +00:00
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _decode_json_if_str(val: Any) -> Any:
    if isinstance(val, str) and val and val[0] in "[{":
        try:
            return json.loads(val)
        except ValueError:
            return val
    return val


def _coerce_column_change_values(ev: ColumnChangeEvent | SubitemColumnChangeEvent) -> dict[str, Any]:
    """Return natural Python types for `value` and `previous_value` based on column type."""
    col_type = (ev.column_type or "").lower()
    raw_v = _decode_json_if_str(ev.value)
    raw_prev = _decode_json_if_str(ev.previous_value)

    def _coerce_one(v: Any) -> Any:
        if col_type in ("text",):
            return v if not isinstance(v, dict) else v.get("text") or v.get("value") or v
        if col_type in ("numbers", "number"):
            try:
                if isinstance(v, (int, float)):
                    return v
                if isinstance(v, str) and v.strip() != "":
                    f = float(v)
                    return int(f) if f.is_integer() else f
                if isinstance(v, dict):
                    # Prefer numeric from common shapes
                    txt = v.get("text")
                    if isinstance(txt, str) and txt.strip() != "":
                        f = float(txt)
                        return int(f) if f.is_integer() else f
                return v
            except Exception:
                return v
        if col_type in ("status",):
            if isinstance(v, dict):
                idx = v.get("index")
                try:
                    idx = int(idx) if idx is not None else None
                except Exception:
                    idx = None
                label = v.get("label")
                return {"label": label, "index": idx}
            return v
        if col_type in ("date",):
            if isinstance(v, dict):
                d = v.get("date")
                t = v.get("time")
                try:
                    if isinstance(d, str) and d:
                        dd = date.fromisoformat(d)
                        if isinstance(t, str) and t:
                            try:
                                hh, mm = t.split(":", 1)
                                return datetime(dd.year, dd.month, dd.day, int(hh), int(mm))
                            except Exception:
                                return dd
                        return dd
                except Exception:
                    return v
            return v
        if col_type in ("people", "person"):
            if isinstance(v, dict):
                pts = v.get("personsAndTeams") or []
                out: list[int] = []
                for e in pts:
                    try:
                        pid = e.get("id")
                        if pid is not None:
                            out.append(int(pid))
                    except Exception:
                        continue
                return out
            return v
        if col_type in ("board_relation", "connect_boards"):
            if isinstance(v, dict):
                ids = v.get("item_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(v, list):
                try:
                    return [int(i) for i in v]
                except Exception:
                    return v
            return v
        if col_type in ("tags", "tag"):
            if isinstance(v, dict):
                ids = v.get("tag_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(v, list):
                try:
                    return [int(i) for i in v]
                except Exception:
                    return v
            return v
        if col_type in ("link",):
            if isinstance(v, dict):
                url = v.get("url")
                text = v.get("text")
                return (url, text) if text else url
            return v
        if col_type in ("location",):
            if isinstance(v, dict):
                return LocationValue.from_raw(v, text=v.get("address") if isinstance(v.get("address"), str) else None)
            if isinstance(v, str):
                return LocationValue(address=v, text=v)
            return None if v is None else v
        if col_type in ("doc",):
            if isinstance(v, dict):
                files = v.get("files") or []
                if files:
                    return files[0].get("objectId")
            return v
        # default: passthrough
        return v

    return {
        "value": _coerce_one(raw_v),
        "previous_value": _coerce_one(raw_prev),
    }


@csrf_exempt
def monday_webhook(request: HttpRequest) -> HttpResponse:
    """Minimal, production-ready monday.com webhook endpoint example.

    - Responds to URL verification challenges
    - Optionally validates HMAC signature via X-Monday-Signature
    - Parses into a typed event with definite attributes for processing
    """
    if request.method != "POST":
        return HttpResponse(status=405)

    body = request.body  # bytes
    headers = _extract_headers(request)

    # Parse and validate
    req = parse_monday_webhook_request(
        body=body,
        headers=headers,
        signing_secret=MONDAY_WEBHOOK_SECRET,
    )

    # 1) Challenge handshake (must return only the challenge)
    if req.is_challenge:
        return JsonResponse({"challenge": req.challenge})

    # 2) Optional: enforce signature validity when a secret is configured
    if MONDAY_WEBHOOK_SECRET and req.signature_valid is False:
        return HttpResponse(status=401)

    # 3) Optional: ignore retry deliveries
    if req.is_retry:
        return HttpResponse("ok")

    # 4) Access typed attributes directly (OOP, linter-friendly)
    ev = req.event
    # Example usages (branch by event type if needed):
    # - Base attributes on all events:
    #     ev.type, ev.board_id, ev.group_id, ev.item_id, ev.item_name,
    #     ev.user_id, ev.trigger_time, ev.subscription_id, ev.trigger_uuid, ev.app
    # - Event-specific attributes:
    #     COLUMN_CHANGE:        ev.column_id, ev.column_type, ev.column_title, ev.value, ev.previous_value
    #     COLUMN_CREATED:       ev.column_id, ev.column_type, ev.column_title
    #     ITEM_MOVED:           ev.target_group_id
    #     UPDATE_*:             ev.update_id
    #     SUBITEM_COLUMN_CHANGE: ev.column_id, ev.column_type, ev.column_title, ev.value, ev.previous_value
    #     SUBITEM_MOVED:        ev.target_group_id

    # List all available dataclass attributes for this specific event instance
    available_attrs = [f.name for f in fields(ev)]

    # Serialize dataclass to primitives for JSON response/logging
    event_payload = asdict(ev)
    if getattr(ev, "type", None) is not None:
        try:
            event_payload["type"] = ev.type.value  # Enum -> str
        except Exception:
            event_payload["type"] = str(ev.type)

    # Automatic coercions to natural Python types
    typed: dict[str, Any] = {}
    # Add parsed trigger_time when available
    dt = _parse_iso8601_to_datetime(getattr(ev, "trigger_time", None))
    if dt is not None:
        typed["trigger_time"] = dt
    # Coerce column change payload values
    if isinstance(ev, (ColumnChangeEvent, SubitemColumnChangeEvent)):
        typed.update(_coerce_column_change_values(ev))

    return JsonResponse({
        "ok": True,
        "event": event_payload,
        "available_attrs": available_attrs,
        "typed": typed,
        "meta": {
            "is_retry": req.is_retry,
            "signature_valid": req.signature_valid,
        },
    })



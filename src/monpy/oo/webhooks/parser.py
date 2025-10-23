from __future__ import annotations

import json
from typing import Any, Dict

from ..enums import WebhookEventType
from .events import (
    WebhookEvent,
    EVENT_CLASS_BY_TYPE,
)


def _ensure_dict(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    if isinstance(payload, str):
        return json.loads(payload)
    if isinstance(payload, dict):
        return payload
    raise TypeError("payload must be dict, JSON str, or bytes")


def _as_str(val: Any) -> str | None:
    if val is None:
        return None
    try:
        return str(int(val))
    except Exception:
        try:
            return str(val)
        except Exception:
            return None


def _detect_event_type(event: dict) -> WebhookEventType:
    t = (event.get("type") or event.get("event", {}).get("type") or "").strip()
    if not t:
        return WebhookEventType.UNKNOWN
    # Normalize known aliases if monday changes naming
    alias = {
        "change_column_values": "change_column_value",
        "item_created": "create_item",
        "create_pulse": "create_item",
        "delete_pulse": "item_deleted",
        "change_name": "item_name_changed",
        "create_subitem": "subitem_created",
        "create_update": "update_created",
    }.get(t, t)
    try:
        return WebhookEventType(alias)
    except ValueError:
        return WebhookEventType.UNKNOWN


def parse_webhook(payload: Any) -> WebhookEvent:
    """
    Parse a monday.com webhook request body into a typed `WebhookEvent`.

    Accepts dict, JSON string, or bytes. Unknown types map to
    `WebhookEventType.UNKNOWN` and return a plain `WebhookEvent` instance.
    """
    data = _ensure_dict(payload)
    ev = data.get("event") or data

    typ = _detect_event_type(ev)
    cls = EVENT_CLASS_BY_TYPE.get(typ, WebhookEvent)

    common = dict(
        type=typ,
        board_id=_as_str(ev.get("boardId")),
        group_id=_as_str(ev.get("groupId")),
        item_id=_as_str(ev.get("pulseId") or ev.get("itemId") or ev.get("entityId")),
        item_name=ev.get("pulseName") or ev.get("itemName"),
        user_id=_as_str(ev.get("userId")),
        trigger_time=str(ev.get("triggerTime")) if ev.get("triggerTime") is not None else None,
        subscription_id=_as_str(ev.get("subscriptionId")),
        trigger_uuid=str(ev.get("triggerUuid")) if ev.get("triggerUuid") is not None else None,
        app=ev.get("app"),
    )

    if cls.__name__ == "ColumnChangeEvent":
        specific = dict(
            column_id=_as_str(ev.get("columnId")),
            column_type=(ev.get("columnType") or ev.get("type")),
            column_title=ev.get("columnTitle"),
            value=ev.get("value"),
            previous_value=ev.get("previousValue"),
        )
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    elif cls.__name__ == "ColumnCreatedEvent":
        specific = dict(
            column_id=_as_str(ev.get("columnId")),
            column_type=(ev.get("columnType") or ev.get("type")),
            column_title=ev.get("columnTitle"),
        )
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    elif cls.__name__ in {"UpdateCreatedEvent", "UpdateChangedEvent", "UpdateDeletedEvent"}:
        specific = dict(update_id=_as_str(ev.get("updateId") or ev.get("id")))
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    elif cls.__name__ == "ItemMovedEvent":
        specific = dict(target_group_id=_as_str(ev.get("toGroupId") or ev.get("targetGroupId")))
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    elif cls.__name__ == "SubitemMovedEvent":
        specific = dict(target_group_id=_as_str(ev.get("toGroupId") or ev.get("targetGroupId")))
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    elif cls.__name__ == "SubitemColumnChangeEvent":
        specific = dict(
            column_id=_as_str(ev.get("columnId")),
            column_type=(ev.get("columnType") or ev.get("type")),
            column_title=ev.get("columnTitle"),
            value=ev.get("value"),
            previous_value=ev.get("previousValue"),
        )
        obj = cls(**common, **specific)  # type: ignore[arg-type]
    else:
        obj = cls(**common)  # type: ignore[arg-type]

    # keep original request for debugging/advanced use
    obj.raw = data  # type: ignore[attr-defined]
    return obj



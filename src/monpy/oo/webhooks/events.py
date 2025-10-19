from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from datetime import datetime, date
import json

from ..enums import WebhookEventType
from ..columns.values import LocationValue


@dataclass
class WebhookEvent:
    """
    Base webhook event object for monday.com callbacks.

    Attributes are normalized to snake_case and IDs are represented as strings
    where possible for consistency with the OO layer.
    """

    type: WebhookEventType
    board_id: Optional[str] = None
    group_id: Optional[str] = None
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    user_id: Optional[str] = None
    trigger_time: Optional[str] = None
    subscription_id: Optional[str] = None
    trigger_uuid: Optional[str] = None
    app: Optional[str] = None

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def trigger_time_datetime(self) -> Optional[datetime]:
        """Return `trigger_time` parsed as `datetime` when possible.

        Accepts ISO-8601 strings and best-effort 'Z' suffix handling.
        """
        s = self.trigger_time
        if not s:
            return None
        try:
            # Convert trailing 'Z' to +00:00 for fromisoformat support
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s)
        except Exception:
            return None


@dataclass
class ItemCreatedEvent(WebhookEvent):
    pass


@dataclass
class ItemDeletedEvent(WebhookEvent):
    pass


@dataclass
class ItemArchivedEvent(WebhookEvent):
    pass


@dataclass
class ItemRestoredEvent(WebhookEvent):
    pass


@dataclass
class ItemMovedEvent(WebhookEvent):
    target_group_id: Optional[str] = None


@dataclass
class ColumnChangeEvent(WebhookEvent):
    column_id: Optional[str] = None
    column_type: Optional[str] = None
    column_title: Optional[str] = None
    value: Any = None
    previous_value: Any = None

    # --- Natural Python type coercions for column values -----------------
    def _decode_json_if_str(self, v: Any) -> Any:
        if isinstance(v, str) and v and v[0] in "[{":
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v

    def _coerce_by_type(self, v: Any) -> Any:
        t = (self.column_type or "").lower()
        vv = self._decode_json_if_str(v)
        if t in ("text",):
            return vv if not isinstance(vv, dict) else vv.get("text") or vv.get("value") or vv
        if t in ("numbers", "number"):
            try:
                if isinstance(vv, (int, float)):
                    return vv
                if isinstance(vv, str) and vv.strip() != "":
                    f = float(vv)
                    return int(f) if f.is_integer() else f
                if isinstance(vv, dict):
                    txt = vv.get("text")
                    if isinstance(txt, str) and txt.strip() != "":
                        f = float(txt)
                        return int(f) if f.is_integer() else f
                return vv
            except Exception:
                return vv
        if t in ("status",):
            if isinstance(vv, dict):
                idx = vv.get("index")
                try:
                    idx = int(idx) if idx is not None else None
                except Exception:
                    idx = None
                label = vv.get("label")
                return {"label": label, "index": idx}
            return vv
        if t in ("date",):
            if isinstance(vv, dict):
                d = vv.get("date")
                tm = vv.get("time")
                try:
                    if isinstance(d, str) and d:
                        dd = date.fromisoformat(d)
                        if isinstance(tm, str) and tm:
                            try:
                                hh, mm = tm.split(":", 1)
                                return datetime(dd.year, dd.month, dd.day, int(hh), int(mm))
                            except Exception:
                                return dd
                        return dd
                except Exception:
                    return vv
            return vv
        if t in ("people", "person"):
            if isinstance(vv, dict):
                pts = vv.get("personsAndTeams") or []
                out: list[int] = []
                for e in pts:
                    try:
                        pid = e.get("id")
                        if pid is not None:
                            out.append(int(pid))
                    except Exception:
                        continue
                return out
            return vv
        if t in ("board_relation", "connect_boards"):
            if isinstance(vv, dict):
                ids = vv.get("item_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(vv, list):
                try:
                    return [int(i) for i in vv]
                except Exception:
                    return vv
            return vv
        if t in ("tags", "tag"):
            if isinstance(vv, dict):
                ids = vv.get("tag_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(vv, list):
                try:
                    return [int(i) for i in vv]
                except Exception:
                    return vv
            return vv
        if t in ("link",):
            if isinstance(vv, dict):
                url = vv.get("url")
                text = vv.get("text")
                return (url, text) if text else url
            return vv
        if t in ("location",):
            if isinstance(vv, dict):
                return LocationValue.from_raw(vv, text=vv.get("address") if isinstance(vv.get("address"), str) else None)
            if isinstance(vv, str):
                return LocationValue(address=vv, text=vv)
            return None if vv is None else vv
        if t in ("doc",):
            if isinstance(vv, dict):
                files = vv.get("files") or []
                if files:
                    return files[0].get("objectId")
            return vv
        # default: passthrough
        return vv

    @property
    def typed_value(self) -> Any:
        return self._coerce_by_type(self.value)

    @property
    def typed_previous_value(self) -> Any:
        return self._coerce_by_type(self.previous_value)


@dataclass
class ColumnCreatedEvent(WebhookEvent):
    column_id: Optional[str] = None
    column_type: Optional[str] = None
    column_title: Optional[str] = None


@dataclass
class UpdateCreatedEvent(WebhookEvent):
    update_id: Optional[str] = None


@dataclass
class UpdateChangedEvent(WebhookEvent):
    update_id: Optional[str] = None


@dataclass
class UpdateDeletedEvent(WebhookEvent):
    update_id: Optional[str] = None


# --- Additional OO event subclasses for parity ----------------------------


@dataclass
class ItemNameChangedEvent(WebhookEvent):
    pass


@dataclass
class SubitemCreatedEvent(WebhookEvent):
    pass


@dataclass
class SubitemDeletedEvent(WebhookEvent):
    pass


@dataclass
class SubitemArchivedEvent(WebhookEvent):
    pass


@dataclass
class SubitemRestoredEvent(WebhookEvent):
    pass


@dataclass
class SubitemMovedEvent(WebhookEvent):
    target_group_id: Optional[str] = None


@dataclass
class SubitemColumnChangeEvent(WebhookEvent):
    column_id: Optional[str] = None
    column_type: Optional[str] = None
    column_title: Optional[str] = None
    value: Any = None
    previous_value: Any = None

    # Mirror the same coercion API as ColumnChangeEvent
    def _decode_json_if_str(self, v: Any) -> Any:
        if isinstance(v, str) and v and v[0] in "[{":
            try:
                return json.loads(v)
            except ValueError:
                return v
        return v

    def _coerce_by_type(self, v: Any) -> Any:
        t = (self.column_type or "").lower()
        vv = self._decode_json_if_str(v)
        if t in ("text",):
            return vv if not isinstance(vv, dict) else vv.get("text") or vv.get("value") or vv
        if t in ("numbers", "number"):
            try:
                if isinstance(vv, (int, float)):
                    return vv
                if isinstance(vv, str) and vv.strip() != "":
                    f = float(vv)
                    return int(f) if f.is_integer() else f
                if isinstance(vv, dict):
                    txt = vv.get("text")
                    if isinstance(txt, str) and txt.strip() != "":
                        f = float(txt)
                        return int(f) if f.is_integer() else f
                return vv
            except Exception:
                return vv
        if t in ("status",):
            if isinstance(vv, dict):
                idx = vv.get("index")
                try:
                    idx = int(idx) if idx is not None else None
                except Exception:
                    idx = None
                label = vv.get("label")
                return {"label": label, "index": idx}
            return vv
        if t in ("date",):
            if isinstance(vv, dict):
                d = vv.get("date")
                tm = vv.get("time")
                try:
                    if isinstance(d, str) and d:
                        dd = date.fromisoformat(d)
                        if isinstance(tm, str) and tm:
                            try:
                                hh, mm = tm.split(":", 1)
                                return datetime(dd.year, dd.month, dd.day, int(hh), int(mm))
                            except Exception:
                                return dd
                        return dd
                except Exception:
                    return vv
            return vv
        if t in ("people", "person"):
            if isinstance(vv, dict):
                pts = vv.get("personsAndTeams") or []
                out: list[int] = []
                for e in pts:
                    try:
                        pid = e.get("id")
                        if pid is not None:
                            out.append(int(pid))
                    except Exception:
                        continue
                return out
            return vv
        if t in ("board_relation", "connect_boards"):
            if isinstance(vv, dict):
                ids = vv.get("item_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(vv, list):
                try:
                    return [int(i) for i in vv]
                except Exception:
                    return vv
            return vv
        if t in ("tags", "tag"):
            if isinstance(vv, dict):
                ids = vv.get("tag_ids") or []
                try:
                    return [int(i) for i in ids]
                except Exception:
                    return ids
            if isinstance(vv, list):
                try:
                    return [int(i) for i in vv]
                except Exception:
                    return vv
            return vv
        if t in ("link",):
            if isinstance(vv, dict):
                url = vv.get("url")
                text = vv.get("text")
                return (url, text) if text else url
            return vv
        if t in ("location",):
            if isinstance(vv, dict):
                return LocationValue.from_raw(vv, text=vv.get("address") if isinstance(vv.get("address"), str) else None)
            if isinstance(vv, str):
                return LocationValue(address=vv, text=vv)
            return None if vv is None else vv
        if t in ("doc",):
            if isinstance(vv, dict):
                files = vv.get("files") or []
                if files:
                    return files[0].get("objectId")
            return vv
        # default: passthrough
        return vv

    @property
    def typed_value(self) -> Any:
        return self._coerce_by_type(self.value)

    @property
    def typed_previous_value(self) -> Any:
        return self._coerce_by_type(self.previous_value)


# Mapping from enum to concrete OO event type
EVENT_CLASS_BY_TYPE: dict[WebhookEventType, type[WebhookEvent]] = {
    WebhookEventType.ITEM_CREATED: ItemCreatedEvent,
    WebhookEventType.ITEM_DELETED: ItemDeletedEvent,
    WebhookEventType.ITEM_ARCHIVED: ItemArchivedEvent,
    WebhookEventType.ITEM_RESTORED: ItemRestoredEvent,
    WebhookEventType.ITEM_MOVED: ItemMovedEvent,
    WebhookEventType.ITEM_NAME_CHANGE: ItemNameChangedEvent,
    WebhookEventType.COLUMN_CHANGE: ColumnChangeEvent,
    WebhookEventType.COLUMN_CREATED: ColumnCreatedEvent,
    WebhookEventType.NEW_UPDATE: UpdateCreatedEvent,
    WebhookEventType.UPDATE_CHANGE: UpdateChangedEvent,
    WebhookEventType.UPDATE_DELETE: UpdateDeletedEvent,
    WebhookEventType.SUBITEM_CREATED: SubitemCreatedEvent,
    WebhookEventType.SUBITEM_DELETED: SubitemDeletedEvent,
    WebhookEventType.SUBITEM_ARCHIVED: SubitemArchivedEvent,
    WebhookEventType.SUBITEM_RESTORED: SubitemRestoredEvent,
    WebhookEventType.SUBITEM_MOVED: SubitemMovedEvent,
    WebhookEventType.SUBITEM_COLUMN_CHANGE: SubitemColumnChangeEvent,
}



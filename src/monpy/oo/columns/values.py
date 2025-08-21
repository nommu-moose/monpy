from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, Optional
import json

from ..column import ColumnCollection
from ..utils import to_attr


def _encode_value(col_type: str | None, value: Any) -> Any:
    t = (col_type or "").lower()
    if t in ("text",):
        if value is None:
            return ""
        return str(value)
    if t in ("numbers", "number"):
        return value
    if t in ("status",):
        # Support either string label or index; pass-through for JSON shape
        if isinstance(value, dict):
            return value
        if isinstance(value, int):
            return {"index": value}
        return {"label": str(value)}
    if t in ("date",):
        if isinstance(value, (date, datetime)):
            d = value.date() if isinstance(value, datetime) else value
            return {"date": d.isoformat()}
        return value
    if t in ("people", "person"):
        # allow single or list
        if value is None:
            return {"personsAndTeams": []}
        if isinstance(value, (list, tuple)):
            ids = [int(v) for v in value]
        else:
            ids = [int(value)]
        return {"personsAndTeams": [{"id": pid, "kind": "person"} for pid in ids]}
    if t in ("board_relation", "connect_boards"):
        if value is None:
            return {"item_ids": []}
        if isinstance(value, (list, tuple)):
            ids = [int(v) for v in value]
        else:
            ids = [int(value)]
        return {"item_ids": ids}
    if t in ("tags", "tag"):
        # Expect list of tag IDs
        if value is None:
            return {"tag_ids": []}
        if isinstance(value, (list, tuple)):
            ids = [int(v) for v in value]
        else:
            ids = [int(value)]
        return {"tag_ids": ids}
    if t in ("link",):
        # Accept str URL or (url, text)
        if isinstance(value, tuple) and len(value) == 2:
            return {"url": str(value[0]), "text": str(value[1])}
        if isinstance(value, str):
            return {"url": value}
        return value
    # default: pass through
    return value


def _decode_value(col_type: str | None, cv: Dict[str, Any]) -> Any:
    t = (col_type or "").lower()
    raw = cv.get("value")
    txt = cv.get("text")
    if isinstance(raw, str) and raw and raw[0] in "{[":
        try:
            raw = json.loads(raw)
        except ValueError:
            pass
    if t in ("text",):
        return txt if txt is not None else raw
    if t in ("numbers", "number"):
        return float(txt) if txt is not None and txt != "" else raw
    if t in ("status",):
        # return human label when available
        return txt if txt is not None else raw
    if t in ("date",):
        # prefer ISO date string
        if isinstance(raw, dict) and raw.get("date"):
            return raw["date"]
        return txt or raw
    if t in ("people", "person"):
        if isinstance(raw, dict):
            return [e.get("id") for e in raw.get("personsAndTeams", []) if isinstance(e.get("id"), int)]
        return raw
    if t in ("board_relation", "connect_boards"):
        # Prefer native GraphQL typed field when available (API ≥ 2025-04)
        typed = cv.get("linked_item_ids")
        if isinstance(typed, list):
            try:
                return [int(i) for i in typed]
            except Exception:
                return typed
        # Fallback to the JSON-encoded value blob
        if isinstance(raw, dict):
            return [int(i) for i in raw.get("item_ids", [])]
        # Extended: some APIs may project list directly
        if isinstance(raw, list):
            return [int(i) for i in raw]
        return raw
    if t in ("tags", "tag"):
        if isinstance(raw, dict):
            return [int(i) for i in raw.get("tag_ids", [])]
        return raw
    if t in ("link",):
        if isinstance(raw, dict):
            return raw.get("url") or raw
        return raw or txt
    if t in ("doc",):
        # return objectId if present
        if isinstance(raw, dict):
            files = raw.get("files") or []
            if files:
                return files[0].get("objectId")
        return raw
    return raw if raw is not None else txt


class ColumnValues:
    """Attribute access wrapper for an item's column values.

    Usage:
        item.values.status = "Done"
        item.values.due_date = date(2025, 1, 1)
    """

    def __init__(self, item: Any) -> None:
        self._item = item
        self._cache: Dict[str, tuple[float, Any]] = {}

    def _columns(self) -> ColumnCollection:
        board = self._item._session.board(self._item.board_id)
        return board.columns

    def _find_column_for_attr(self, name: str):
        """Resolve a column by attribute name with a best-effort fallback for sub-items.

        Primary lookup uses the item's board columns. If not found and the item is a
        SubItem, fall back to the hidden sub-items board's "name" column when present
        to avoid failing writes due to slow column replication.
        """
        # 1) Try current board (and one refresh attempt already handled by callers)
        try:
            return self._columns().by_attr(name)
        except KeyError:
            pass

        # 2) SubItem fallback: use the Name column on the sub-items board when available
        try:
            from ..subitem import SubItem  # type: ignore
            if isinstance(self._item, SubItem):  # type: ignore[arg-type]
                try:
                    return self._columns().by_attr("name")
                except Exception:
                    pass
        except Exception:
            pass

        # If all else fails, propagate lookup failure
        raise AttributeError(name)

    def __getattr__(self, name: str) -> Any:
        # Lazy fetch current value from API for items or subitems
        try:
            col = self._columns().by_attr(name)
        except KeyError:
            # Columns cache might be stale (e.g., created just now). Refresh board and retry once.
            try:
                board = self._item._session.board(self._item.board_id)
                board.refresh()
                col = board.columns.by_attr(name)
            except Exception:
                # try parent-board fallback for SubItems
                col = self._find_column_for_attr(name)
        client = self._item._session.client
        cv = None
        # check cache
        ttl = getattr(self._item._session, "values_cache_ttl", None)
        if ttl is not None:
            import time
            ent = self._cache.get(col.id)
            if ent and (time.time() - ent[0]) <= ttl:
                return ent[1]
        try:
            data = client.get_item_values(self._item.id, column_ids=[col.id])
            cvs = data.get("column_values") or []
            cv = cvs[0] if cvs else None
        except Exception:
            # subitem path: fetch only the requested column when possible
            data = client.get_subitem_values(self._item.id, column_ids=[col.id])
            cvs = data.get("column_values") or []
            cv = cvs[0] if cvs else None
        if not cv:
            value = None
        else:
            value = _decode_value(col.type, cv)
        if ttl is not None:
            import time
            self._cache[col.id] = (time.time(), value)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            return super().__setattr__(name, value)
        try:
            col = self._columns().by_attr(name)
        except KeyError:
            try:
                board = self._item._session.board(self._item.board_id)
                board.refresh()
                col = board.columns.by_attr(name)
            except Exception:
                col = self._find_column_for_attr(name)
        payload = _encode_value(col.type, value)
        self._item.mark_dirty("column_values", {
            **self._item._dirty.get("column_values", {}),
            col.id: payload,
        })
        # If inside a Session transaction, schedule the update immediately so
        # it is flushed on commit (and can be batched safely). Outside a
        # transaction, the caller should invoke item.save() explicitly.
        try:
            sess = getattr(self._item, "_session", None)
            if sess is not None and getattr(sess, "_active_tx", None) is not None:
                sess._schedule_item_update(
                    board_id=self._item.board_id,
                    item_id=self._item.id,
                    column_values={col.id: payload},
                )
        except Exception:
            # best-effort only; fall back to explicit save()
            pass



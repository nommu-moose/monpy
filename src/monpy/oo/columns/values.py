from __future__ import annotations

from datetime import date, datetime
from dataclasses import dataclass
from typing import Any, Dict, Optional
import json

from ..column import ColumnCollection
from ..utils import to_attr


@dataclass
class LocationValue:
    address: Optional[str] = None
    street: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    country_code: Optional[str] = None
    zip: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    text: Optional[str] = None

    @classmethod
    def from_raw(cls, raw: Dict[str, Any], text: Optional[str] = None) -> "LocationValue":
        return cls(
            address=raw.get("address") or raw.get("formattedAddress") or raw.get("formatted_address"),
            street=raw.get("street") or raw.get("street_name") or raw.get("route"),
            city=raw.get("city") or raw.get("locality"),
            state=raw.get("state") or raw.get("administrative_area_level_1"),
            country=raw.get("country"),
            country_code=raw.get("country_short") or raw.get("countryCode") or raw.get("country_code"),
            zip=raw.get("zip") or raw.get("zipcode") or raw.get("postal_code"),
            lat=(float(raw["lat"]) if isinstance(raw.get("lat"), (int, float, str)) and raw.get("lat") not in (None, "") else None),
            lng=(float(raw["lng"]) if isinstance(raw.get("lng"), (int, float, str)) and raw.get("lng") not in (None, "") else None),
            text=text if text is not None else (raw.get("address") or None),
        )

    def to_raw(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        if self.address is not None:
            payload["address"] = self.address
        if self.street is not None:
            payload["street"] = self.street
        if self.city is not None:
            payload["city"] = self.city
        if self.state is not None:
            payload["state"] = self.state
        if self.country is not None:
            payload["country"] = self.country
        if self.country_code is not None:
            payload["country_short"] = self.country_code
        if self.zip is not None:
            payload["zip"] = self.zip
        if self.lat is not None:
            payload["lat"] = float(self.lat)
        if self.lng is not None:
            payload["lng"] = float(self.lng)
        return payload


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
    if t in ("location",):
        if value is None:
            return {}
        if isinstance(value, LocationValue):
            return value.to_raw()
        if isinstance(value, str):
            return {"address": value}
        if isinstance(value, dict):
            # best-effort: normalize lat/lng types
            out = dict(value)
            try:
                if out.get("lat") not in (None, ""):
                    out["lat"] = float(out["lat"])  # type: ignore[index]
                if out.get("lng") not in (None, ""):
                    out["lng"] = float(out["lng"])  # type: ignore[index]
            except Exception:
                pass
            return out
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
    if t in ("location",):
        # When value is a JSON blob, return a structured LocationValue
        if isinstance(raw, dict):
            return LocationValue.from_raw(raw, text=txt)
        # Some APIs may return a plain string address in text/raw
        if isinstance(raw, str) or isinstance(txt, str):
            return LocationValue(address=raw if isinstance(raw, str) else None, text=txt or raw)
        return None
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
        # 1) Normalize attribute name (support title-case/human names like "Location")
        norm = to_attr(name)

        # 2) Try current board (and one refresh attempt already handled by callers)
        try:
            return self._columns().by_attr(norm)
        except KeyError:
            pass

        # 3) SubItem fallback: use the Name column on the sub-items board when available
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
        norm = to_attr(name)
        # Support reading status index via attribute suffix "_index"
        is_index_accessor = False
        base_norm = norm
        if norm.endswith("_index"):
            is_index_accessor = True
            base_norm = norm[:-6]
        try:
            col = self._columns().by_attr(base_norm)
        except KeyError:
            # Columns cache might be stale (e.g., created just now). Refresh board and retry once.
            try:
                board = self._item._session.board(self._item.board_id)
                board.refresh()
                col = board.columns.by_attr(base_norm)
            except Exception:
                # try parent-board fallback for SubItems
                col = self._find_column_for_attr(base_norm)
        client = self._item._session.client
        cv = None
        # check cache
        ttl = getattr(self._item._session, "values_cache_ttl", None)
        if ttl is not None:
            import time
            cache_key = col.id if not is_index_accessor else f"{col.id}::index"
            ent = self._cache.get(cache_key)
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
            # also compute counterpart for completeness
            index_value = None
            label_value = None
        else:
            # Always compute both label and index so one fetch warms both caches
            label_value = _decode_value(col.type, cv)
            # Best-effort extraction of numeric index from raw JSON payload
            raw = cv.get("value")
            if isinstance(raw, str) and raw and raw[0] in "{[":
                try:
                    raw = json.loads(raw)
                except ValueError:
                    pass
            index_value = None
            try:
                if isinstance(raw, dict):
                    idx = raw.get("index")
                    index_value = int(idx) if idx is not None else None
            except Exception:
                index_value = None
            value = index_value if is_index_accessor else label_value
        if ttl is not None:
            import time
            now = time.time()
            # cache label
            self._cache[col.id] = (now, label_value if cv else None)
            # cache index (for status columns)
            self._cache[f"{col.id}::index"] = (now, index_value if cv else None)
        return value

    # --- cache warming from bulk/row payloads -------------------------
    def warm_from_row(self, row: Dict[str, Any]) -> None:
        """Warm the per-item values cache using a full item "row" payload.

        The payload is expected to be compatible with client.get_item_values or
        client.get_items_values, containing ``column_values`` entries with
        ``id``, ``value``, ``text`` and ``type``.

        Notes
        -----
        - This respects the same decoding as attribute access and precomputes
          both the human label and status index so either accessor hits cache.
        - Caching effectiveness depends on Session.values_cache_ttl being set.
        """
        cvs = (row or {}).get("column_values") or []
        if not cvs:
            return
        try:
            board_columns = self._columns()
        except Exception:
            return
        try:
            import time
            now = time.time()
        except Exception:
            now = 0.0
        for cv in cvs:
            try:
                col_id = cv.get("id")
                if not isinstance(col_id, str):
                    continue
                # Resolve column to obtain its type when available
                try:
                    col = board_columns.by_id(col_id)
                    col_type = col.type
                except Exception:
                    # Fall back to type from payload
                    col_type = cv.get("type")

                label_value = _decode_value(col_type, cv)

                # Compute status index counterpart similar to __getattr__
                raw = cv.get("value")
                if isinstance(raw, str) and raw and raw[0] in "{[":
                    try:
                        raw = json.loads(raw)
                    except ValueError:
                        pass
                index_value = None
                try:
                    if isinstance(raw, dict):
                        idx = raw.get("index")
                        index_value = int(idx) if idx is not None else None
                except Exception:
                    index_value = None

                # Store both label and index under standard cache keys
                self._cache[col_id] = (now, label_value)
                self._cache[f"{col_id}::index"] = (now, index_value)
            except Exception:
                # Best-effort warming; ignore malformed entries
                continue

    def __setattr__(self, name: str, value: Any) -> None:
        if name.startswith("_"):
            return super().__setattr__(name, value)
        norm = to_attr(name)
        try:
            col = self._columns().by_attr(norm)
        except KeyError:
            try:
                board = self._item._session.board(self._item.board_id)
                board.refresh()
                col = board.columns.by_attr(norm)
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



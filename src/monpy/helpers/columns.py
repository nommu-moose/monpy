from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from ..client import MondayClient
from .upsert_item import (
    ColumnSpec,
    StatusColor,
    StatusDefaults,
    StatusOption,
    _resolve_or_create_columns,
)


def _normalize_simple_type(raw: str) -> str:
    t = (raw or "").strip().lower()
    if t in ("hyperlink", "url", "link"):
        return "link"
    if t in ("files", "file"):
        return "file"
    if t in ("person",):
        return "people"
    if t in ("connect_boards", "board_relation", "connect"):
        return "board_relation"
    return t


def _enum_attr(member: object, key: str, default: Any = None) -> Any:
    if key == "label":
        try:
            v = getattr(member, "label")
            return v
        except Exception:
            return default
    try:
        return getattr(member, key)
    except Exception:
        pass
    try:
        attrs = getattr(member, "attrs")
        if isinstance(attrs, Mapping):
            return attrs.get(key, default)
    except Exception:
        pass
    return default


def _rich_choices_to_status_defaults(choices_cls: object) -> Mapping[str, Any]:
    members: Iterable[object]
    try:
        members = list(choices_cls)  # type: ignore[call-arg]
    except Exception:
        members = []

    # Collect raw data first (including index 0)
    entries: list[dict] = []
    used: set[int] = set()

    for m in members:
        # Prefer explicit monday_index; then generic index; else None
        idx_val = _enum_attr(m, "monday_index")
        if idx_val is None:
            idx_val = _enum_attr(m, "index")
        try:
            idx: Optional[int] = int(idx_val) if idx_val is not None else None
        except Exception:
            idx = None

        lbl = _enum_attr(m, "label")
        if lbl is None:
            try:
                lbl = getattr(m, "name")
            except Exception:
                lbl = ""
        label = str(lbl) if lbl is not None else ""

        col = _enum_attr(m, "monday_color")
        if isinstance(col, StatusColor):
            color = col.value
        else:
            try:
                color = str(col).strip().lower() if col is not None else ""
            except Exception:
                color = ""

        entries.append({"index": idx, "label": label, "color": color})

    # Reserve explicit indices (including 0) and assign missing ones starting at 0
    for e in entries:
        if isinstance(e.get("index"), int):
            used.add(int(e["index"]))

    next_idx = 0
    for e in entries:
        if e.get("index") is None:
            while next_idx in used:
                next_idx += 1
            e["index"] = next_idx
            used.add(next_idx)
            next_idx += 1

    # Drop empty color and sort ascending by index
    out: list[dict] = []
    for e in entries:
        ent: Dict[str, Any] = {"index": int(e["index"]), "label": e["label"]}
        if e.get("color"):
            ent["color"] = e["color"]
        out.append(ent)

    out.sort(key=lambda d: d["index"])
    return {"labels": out}


def ensure_board_columns(
    api_key: str,
    *,
    board_id: str,
    fields: Sequence[Mapping[str, Any]],
) -> Dict[str, str]:
    """
    Ensure a set of columns exist on a board (create if missing) and return a
    mapping from field name to column id.

    Each entry in `fields` must have:
      - fieldname: str
      - fieldtype: one of
          - "text", "phone", "email", "date", "hyperlink", "tags", "files", "people"
          - {"connect": [<board ids>]}  → connect boards
          - {"status": <RichChoices-like Enum class>}

    Optionally, a field dict may include:
      - title: str  → human title to use when creating a new column (defaults to fieldname)

    Parameters
    ----------
    api_key
        monday.com API token used to create a temporary client internally.
    board_id
        Target board id where columns should exist.
    fields
        Field specifications as described below.

    Each entry in `fields` must have:
      - fieldname: str
      - fieldtype: one of
          - "text", "phone", "email", "date", "hyperlink", "tags", "files", "people"
          - {"connect": [<board ids>]}  → connect boards
          - {"status": <RichChoices-like Enum class>}

    Optionally, a field dict may include an explicit id via keys "id" or
    "column_id" to prefer/validate an existing column.
    """
    # Create a short-lived client instance using the provided API token
    client = MondayClient(api_key)
    specs: list[ColumnSpec] = []

    for f in fields:
        name = str(f.get("fieldname") or "").strip()
        if not name:
            continue

        # Use provided human title when present; otherwise fall back to fieldname
        title = str(f.get("title") or name).strip()

        raw_ft = f.get("fieldtype")
        defaults: Optional[Mapping[str, Any]] = None
        col_type: str

        if isinstance(raw_ft, str):
            col_type = _normalize_simple_type(raw_ft)
        elif isinstance(raw_ft, Mapping):
            if "connect" in raw_ft:
                col_type = "board_relation"
                ids = raw_ft.get("connect")
                if isinstance(ids, (list, tuple)):
                    try:
                        defaults = {"boardIds": [int(x) if str(x).isdigit() else x for x in ids]}
                    except Exception:
                        defaults = {"boardIds": list(ids)}  # type: ignore[arg-type]
                else:
                    defaults = None
            elif "status" in raw_ft:
                col_type = "status"
                defaults = _rich_choices_to_status_defaults(raw_ft.get("status"))
            else:
                # Unknown mapping form; treat as text unless a "type" key is present
                t = raw_ft.get("type") if isinstance(raw_ft.get("type"), str) else "text"
                col_type = _normalize_simple_type(t)
        else:
            col_type = "text"

        cid = f.get("column_id") or f.get("id")
        specs.append(
            ColumnSpec(
                type=col_type,
                title=title,
                column_id=str(cid) if cid else None,
                value=None,
                defaults=defaults,
                description=None,
            )
        )

    resolved, name_to_id = _resolve_or_create_columns(
        client,
        board_id,
        specs,
        strict_resolution=True,
        infer_connect_from_values=False,
    )

    # Ensure mapping preserves provided field order via the returned specs
    out: Dict[str, str] = {}
    for cs in resolved:
        if cs.title and cs.column_id:
            out[cs.title] = str(cs.column_id)
    return out


__all__ = [
    "ensure_board_columns",
]



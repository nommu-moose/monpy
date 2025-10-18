from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..client import MondayClient
from ..exceptions import (
    BoardNotFound,
    ColumnNotFound,
    ItemNotFound,
    MondayAPIError,
    WorkspaceNotFound,
)


# ----------------------------- Data models ------------------------------


@dataclass
class WorkspaceSpec:
    name: str
    id: Optional[str] = None
    kind: str = "open"
    description: Optional[str] = None


@dataclass
class BoardSpec:
    name: str
    id: Optional[str] = None
    board_kind: str = "public"
    workspace_id: Optional[str] = None


@dataclass
class ItemSpec:
    name: str
    id: Optional[str] = None
    # If creating a new item and no group provided, the first group will be used
    group_id: Optional[str] = None


@dataclass
class ColumnSpec:
    """Describe a column to upsert and a value to set on the target item.

    Fields
    ------
    type: str
        monday column type (e.g., "text", "status", "date", "email",
        "people", "connect_boards"/"board_relation", "tags", "name").
    title: str
        Human title to use when creating a new column.
    column_id: Optional[str]
        Explicit column id if already known. Leave empty/None to auto-resolve by title or create.
    value: Any
        Value to set for the column for this item. For the implicit Name column,
        this becomes the item name.
    defaults: Optional[Mapping[str, Any]]
        Creation defaults for the column when it needs to be created (e.g.,
        status labels or connect boards allowed board ids).
    description: Optional[str]
        Optional column description when creating the column.
    """

    type: str
    title: str
    column_id: Optional[str] = None
    value: Any = None
    defaults: Optional[Mapping[str, Any]] = None
    description: Optional[str] = None
# ----------------------------------------------------------------------------
# Status color enums and helpers
# ----------------------------------------------------------------------------

# Mapping based on provided monday.com color enum table (1-based integers)
STATUS_COLOR_NAME_TO_ENUM: Dict[str, int] = {
    "grey": 1,
    "orange": 2,
    "green-shadow": 3,
    "red-shadow": 4,
    "blue-links": 5,
    "purple": 6,
    "grass-green": 7,
    "bright-blue": 8,
    "musterd": 9,
    "yellow": 10,
    "soft-black": 11,
    "dark-red": 12,
    "dark-pink": 13,
    "light-pink": 14,
    "dark-purple": 15,
    "lime-green": 16,
    "turquoise": 17,
    "trolley-grey": 18,
    "brown": 19,
    "dark-orange": 20,
    "sunset": 21,
    "bubble": 22,
    "peach": 23,
    "berry": 24,
    "winter": 25,
    "river": 26,
    "navy": 27,
    "australia": 28,
    "indigo": 29,
    "dark_indigo": 30,
    "pecan": 31,
    "light_magic": 32,
    "sky": 33,
    "cold_blue": 34,
    "kids": 35,
    "purple_gray": 36,
    "corona": 37,
    "sail": 38,
    "old_rose": 39,
    "eden": 40,
}

# Deterministic cycle of allowed color names (preserve insertion order) and enum codes.
STATUS_DEFAULT_COLOR_CYCLE_NAMES: List[str] = list(STATUS_COLOR_NAME_TO_ENUM.keys())
STATUS_DEFAULT_COLOR_CYCLE_ENUMS: List[int] = list(STATUS_COLOR_NAME_TO_ENUM.values())


@dataclass
class StatusOption:
    label: str
    color_name: str


@dataclass
class StatusDefaults:
    options: List[StatusOption]

    def to_dict(self) -> Dict[str, Any]:
        # Build array-of-objects with required color field (stringified enum).
        def _normalized_color_code(name: str | None, idx: int) -> str:
            n = (name or "").strip()
            if n in STATUS_COLOR_NAME_TO_ENUM:
                return str(int(STATUS_COLOR_NAME_TO_ENUM[n]))
            # deterministic fallback from the published cycle (use integer codes, stringified)
            return str(int(STATUS_DEFAULT_COLOR_CYCLE_ENUMS[idx % len(STATUS_DEFAULT_COLOR_CYCLE_ENUMS)]))

        labels: List[Dict[str, Any]] = []
        for idx, opt in enumerate(self.options):
            labels.append({
                "index": idx,
                "label": str(opt.label),
                "color": _normalized_color_code(getattr(opt, "color_name", None), idx),
            })
        return {"labels": labels}




# ----------------------------- Encoders --------------------------------


def _encode_value_for_type(column_type: str | None, value: Any) -> Any:
    """Encode Python values into monday mutation payloads per column type.

    Supported types include: text, status, date, email, people, board_relation
    (connect boards), tags, link, location, numbers.
    """
    t = (column_type or "").lower()
    if t in ("text",):
        if value is None:
            return ""
        return str(value)
    if t in ("numbers", "number"):
        return value
    if t in ("status",):
        if isinstance(value, dict):
            return value
        if isinstance(value, int):
            return {"index": value}
        return {"label": str(value)}
    if t in ("date",):
        if isinstance(value, datetime):
            return {"date": value.date().isoformat(), "time": value.strftime("%H:%M")}
        if isinstance(value, date):
            return {"date": value.isoformat()}
        return value
    if t in ("email",):
        # Accept str email or {email, text}
        if isinstance(value, str):
            return {"email": value}
        if isinstance(value, Mapping):
            out: Dict[str, Any] = {}
            if value.get("email"):
                out["email"] = value.get("email")
            if value.get("text"):
                out["text"] = value.get("text")
            return out
        return value
    if t in ("people", "person"):
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
        if value is None:
            return {"tag_ids": []}
        if isinstance(value, (list, tuple)):
            ids = [int(v) for v in value]
        else:
            ids = [int(value)]
        return {"tag_ids": ids}
    if t in ("link",):
        if isinstance(value, tuple) and len(value) == 2:
            return {"url": str(value[0]), "text": str(value[1])}
        if isinstance(value, str):
            return {"url": value}
        return value
    if t in ("location",):
        if value is None:
            return {}
        if isinstance(value, Mapping):
            out = dict(value)
            try:
                if out.get("lat") not in (None, ""):
                    out["lat"] = float(out["lat"])  # type: ignore[index]
                if out.get("lng") not in (None, ""):
                    out["lng"] = float(out["lng"])  # type: ignore[index]
            except Exception:
                pass
            return out
        if isinstance(value, str):
            return {"address": value}
        return value
    # default: passthrough
    return value


# --------------------------- Resolvers ----------------------------------


def _ensure_workspace(client: MondayClient, spec: WorkspaceSpec) -> str:
    """Return a valid workspace ID, creating as needed."""
    # Try by ID first
    if spec.id:
        try:
            ws = client.get_workspace(spec.id)
            return str(ws["id"])  # type: ignore[index]
        except WorkspaceNotFound:
            pass
        except MondayAPIError:
            pass

    # Try resolve by name
    try:
        for ws in client.iter_workspaces(page_size=100, fields=["id", "name"]):
            if ws.get("name") == spec.name:
                return str(ws.get("id"))
    except Exception:
        # Best-effort; if listing fails, proceed to create
        pass

    created = client.create_workspace(name=spec.name, kind=spec.kind, description=spec.description)
    return str(created.get("id"))


def _ensure_board(client: MondayClient, spec: BoardSpec, *, workspace_id: str) -> str:
    """Return a valid board ID under a workspace, creating as needed."""
    # Try by ID
    if spec.id:
        try:
            b = client.get_board(spec.id)
            return str(b["id"])  # type: ignore[index]
        except BoardNotFound:
            pass
        except MondayAPIError:
            pass

    # Try by name within workspace
    try:
        boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=["id", "name", "workspace_id"])
        for b in boards:
            if b.get("name") == spec.name:
                return str(b.get("id"))
    except Exception:
        pass

    created = client.create_board(name=spec.name, board_kind=spec.board_kind, workspace_id=workspace_id)
    return str(created.get("id"))


def _ensure_group(client: MondayClient, board_id: str, *, group_id: Optional[str] = None, group_name: Optional[str] = None) -> str:
    """Return a valid group id for the board, creating or picking a default if needed."""
    # If explicit id, verify
    if group_id:
        try:
            groups = client.list_groups(board_id)
            if any(g.get("id") == group_id for g in (groups or [])):
                return group_id
        except MondayAPIError:
            pass

    # Try by name
    if group_name:
        try:
            groups = client.list_groups(board_id)
            gid = next((g.get("id") for g in (groups or []) if g.get("title") == group_name), None)
            if gid:
                return str(gid)
        except MondayAPIError:
            pass

    # First existing group
    try:
        groups = client.list_groups(board_id)
        if groups:
            return str(groups[0].get("id"))
    except MondayAPIError:
        pass

    # Create a primary group as a last resort
    created = client.create_group(board_id, title=group_name or "grp1")
    return str(created.get("id"))


def _normalize_col_type(t: str) -> str:
    tt = (t or "").lower()
    if tt == "connect_boards":
        return "board_relation"
    return tt


def _resolve_or_create_columns(client: MondayClient, board_id: str, specs: Sequence[ColumnSpec]) -> Tuple[List[ColumnSpec], Dict[str, str]]:
    """Ensure columns exist; return updated specs with column_id filled and a title->id map.

    The special type "name" is mapped to the implicit Name column id "name" and is not created.
    """
    # Prefetch columns map to minimize calls
    try:
        existing = client.get_columns(board_id, fields=("id", "title", "type"))
    except MondayAPIError:
        existing = []
    title_to_id: Dict[str, str] = {str(c.get("title")): str(c.get("id")) for c in existing or []}

    updated_specs: List[ColumnSpec] = []
    for cs in specs:
        t = _normalize_col_type(cs.type)
        if t in ("name", "title"):
            # map to implicit name id
            updated_specs.append(ColumnSpec(type="name", title=cs.title or "Name", column_id="name", value=cs.value, defaults=cs.defaults, description=cs.description))
            continue

        # if id provided, validate; else resolve by title; else create
        cid: Optional[str] = None
        if cs.column_id:
            try:
                col = client.get_column(board_id, cs.column_id, fields=("id", "type", "title"))
                cid = str(col.get("id"))
            except (ColumnNotFound, MondayAPIError):
                cid = None

        if cid is None:
            cid = title_to_id.get(cs.title)

        if cid is None:
            # create with defaults when provided; normalize well-known schemas and try fallbacks for Status
            try:
                defaults_payload: Optional[Dict[str, Any]] = None
                if isinstance(cs.defaults, Mapping):
                    defaults_payload = dict(cs.defaults)
                # Status special: build normalized entries and try multiple schema variants
                if t == "status":
                    # Build entries from provided defaults (labels -> [{index,label,color}]) using robust coercion
                    lbls = (defaults_payload or {}).get("labels") if isinstance(defaults_payload, Mapping) else None
                    if lbls is None and isinstance(defaults_payload, Mapping):
                        try:
                            lc = defaults_payload.get("labels_colors", {})
                            if isinstance(lc, Mapping):
                                lbls = lc.get("labels")
                        except Exception:
                            pass

                    def _build_labels_list(m: Mapping[Any, Any]) -> List[Dict[str, Any]]:
                        items: List[Tuple[int, str]] = []
                        for k, v in m.items():
                            try:
                                idx = int(k)
                            except Exception:
                                continue
                            if isinstance(v, Mapping):
                                lbl = str(v.get("label") or v.get("name") or "")
                            else:
                                lbl = str(v)
                            items.append((idx, lbl))
                        items.sort(key=lambda x: x[0])
                        return [{"index": i, "label": l} for (i, l) in items]

                    def _ensure_label_colors(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                        out: List[Dict[str, Any]] = []
                        for pos, e in enumerate(entries):
                            idx_val = e.get("index")
                            try:
                                idx_int = int(idx_val) if idx_val is not None else pos
                            except Exception:
                                idx_int = pos
                            # Prefer explicit numeric color if present and valid
                            if isinstance(e.get("color"), int):
                                color_code = str(int(e.get("color")))
                            else:
                                # Accept explicit string name or numeric string from 'color' or 'color_name'
                                explicit_name: Optional[str] = None
                                if isinstance(e.get("color"), str) and e.get("color"):
                                    explicit_name = str(e.get("color"))
                                elif isinstance(e.get("color_name"), str) and e.get("color_name"):
                                    explicit_name = str(e.get("color_name"))

                                if explicit_name in STATUS_COLOR_NAME_TO_ENUM:
                                    color_code = str(int(STATUS_COLOR_NAME_TO_ENUM[explicit_name]))
                                elif explicit_name and explicit_name.isdigit():
                                    # Already a numeric string – pass through
                                    color_code = explicit_name
                                else:
                                    color_code = str(int(STATUS_DEFAULT_COLOR_CYCLE_ENUMS[idx_int % len(STATUS_DEFAULT_COLOR_CYCLE_ENUMS)]))

                            out.append({
                                **e,
                                "index": idx_int,
                                "label": str(e.get("label", "")),
                                "color": color_code,
                            })
                        return out

                    entries: List[Dict[str, Any]]
                    if isinstance(lbls, Mapping):
                        entries = _ensure_label_colors(_build_labels_list(lbls))
                    elif isinstance(lbls, list):
                        if lbls and all(isinstance(x, str) for x in lbls):
                            entries = _ensure_label_colors([{ "index": i, "label": str(x)} for i, x in enumerate(lbls)])
                        elif lbls and all(hasattr(x, "label") and hasattr(x, "color_name") for x in lbls):  # type: ignore[truthy-bool]
                            raw = [{"index": i, "label": str(getattr(x, "label")), "color_name": str(getattr(x, "color_name", ""))} for i, x in enumerate(lbls)]
                            entries = _ensure_label_colors(raw)
                        elif lbls and all(isinstance(e, Mapping) for e in lbls):
                            entries = _ensure_label_colors([dict(e) for e in lbls])
                        else:
                            entries = []
                    else:
                        entries = []

                    # Prepare candidate defaults in decreasing likelihood order
                    candidates: List[Dict[str, Any]] = []
                    # 1) labels as array of objects with color as canonical color name (most likely)
                    if entries:
                        try:
                            # Map enum codes back to color names
                            enum_to_name = {v: k for k, v in STATUS_COLOR_NAME_TO_ENUM.items()}
                            candidates.append({
                                "labels": [
                                    {
                                        "index": e["index"],
                                        "label": e["label"],
                                        "color": enum_to_name.get(int(str(e["color"])), "grey")
                                    }
                                    for e in entries
                                ]
                            })
                        except Exception:
                            pass
                        # 2) labels as array of objects with color as integer enum code
                        try:
                            candidates.append({"labels": [{"index": e["index"], "label": e["label"], "color": int(str(e["color"]))} for e in entries]})
                        except Exception:
                            pass
                        # 3) labels as array of objects with color as stringified enum code (fallback)
                        candidates.append({"labels": entries})
                        # 4) labels without color (let server assign colors)
                        candidates.append({"labels": [{"index": e["index"], "label": e["label"]} for e in entries]})
                        # 5) labels as array of strings
                        candidates.append({"labels": [e["label"] for e in entries]})
                    # Try candidates until one succeeds
                    last_exc: Optional[Exception] = None
                    for cand in candidates or [{}]:
                        try:
                            created = client.create_column(
                                board_id,
                                title=cs.title,
                                column_type=t,
                                defaults=cand if cand else None,
                                description=cs.description,
                            )
                            cid = str(created.get("id"))
                            title_to_id[cs.title] = cid
                            break
                        except MondayAPIError as exc:
                            last_exc = exc
                            continue
                    else:
                        # If all candidates failed, raise the last error
                        if last_exc:
                            raise last_exc
                        raise MondayAPIError("Failed to create status column with provided defaults")
                else:
                    # Non-status: straight pass-through
                    created = client.create_column(
                        board_id,
                        title=cs.title,
                        column_type=t,
                        defaults=defaults_payload,
                        description=cs.description,
                    )
                    cid = str(created.get("id"))
                    title_to_id[cs.title] = cid
            except MondayAPIError:
                # Surface the error – caller may retry after fixing prerequisites
                raise

        updated_specs.append(ColumnSpec(type=t, title=cs.title, column_id=cid, value=cs.value, defaults=cs.defaults, description=cs.description))

    return updated_specs, title_to_id


# ----------------------------- Orchestrator -----------------------------


def upsert_item(
    client: MondayClient,
    *,
    workspace: WorkspaceSpec,
    board: BoardSpec,
    item: ItemSpec,
    columns: Sequence[ColumnSpec],
    group_name: Optional[str] = None,
    safe_updates: bool = True,
) -> Dict[str, Any]:
    """Create or update an item and its surrounding structures.

    Behavior
    --------
    - Ensures the workspace and board exist (creates if missing).
    - Ensures all requested columns exist with provided defaults.
    - Creates a new item when item.id is absent; otherwise updates the existing item.
    - On missing-entity errors (workspace, board, column, item), re-resolves and retries once.

    Returns a dict including entity ids and the item metadata:
        { "workspace_id": str, "board_id": str, "item_id": str, "column_ids": {title: id}, "result": {...} }
    """

    def _execute_once() -> Dict[str, Any]:
        ws_id = _ensure_workspace(client, workspace)
        bd_id = _ensure_board(client, BoardSpec(name=board.name, id=board.id, board_kind=board.board_kind), workspace_id=ws_id)

        # Columns
        col_specs, title_map = _resolve_or_create_columns(client, bd_id, columns)

        # Build values payload and extract item name
        values: Dict[str, Any] = {}
        item_name: str = item.name
        for cs in col_specs:
            if cs.type == "name":
                if cs.value is not None:
                    item_name = str(cs.value)
                continue
            values[cs.column_id or ""] = _encode_value_for_type(cs.type, cs.value)
        # Drop empties just in case
        values = {k: v for k, v in values.items() if k}

        # Create or update item
        if item.id:
            # If updating, we need the board id – assume this bd_id
            if safe_updates:
                client.safe_update_item_values(bd_id, item.id, column_values=values)
            else:
                client.update_item_values(bd_id, item.id, column_values=values)
            result = client.get_item_values(item.id, include_board=True)
            iid = str(result.get("id"))
        else:
            gid = _ensure_group(client, bd_id, group_id=item.group_id, group_name=group_name)
            created = client.create_item(bd_id, group_id=gid, item_name=item_name, column_values=values)
            iid = str(created.get("id"))
            result = client.get_item_values(iid, include_board=True)

        return {
            "workspace_id": ws_id,
            "board_id": bd_id,
            "item_id": iid,
            "column_ids": {c.title: c.column_id for c in col_specs},
            "result": result,
        }

    # First attempt
    try:
        return _execute_once()
    except (WorkspaceNotFound, BoardNotFound, ColumnNotFound, ItemNotFound, MondayAPIError):
        # Recalibrate structures and retry once
        return _execute_once()


def upsert_item_from_dicts(
    client: MondayClient,
    *,
    workspace_name: str,
    board_name: str,
    columns_data: Sequence[Mapping[str, Any]],
    workspace_id: Optional[str] = None,
    board_id: Optional[str] = None,
    item_id: Optional[str] = None,
    item_name: Optional[str] = None,
    workspace_kind: str = "open",
    board_kind: str = "public",
    group_id: Optional[str] = None,
    group_name: Optional[str] = None,
    safe_updates: bool = True,
) -> Dict[str, Any]:
    """Convenience wrapper that accepts simple dicts for columns.

    Each entry in columns_data should have keys:
      - type (str), title (str), value (Any)
      - column_id (optional), defaults (optional mapping), description (optional)

    The item name can be provided either via item_name or a column spec with type="name".
    """
    ws = WorkspaceSpec(name=workspace_name, id=workspace_id, kind=workspace_kind)
    bd = BoardSpec(name=board_name, id=board_id, board_kind=board_kind)
    cols: List[ColumnSpec] = []
    inferred_name: Optional[str] = None
    for d in columns_data:
        ctype = str(d.get("type") or "").strip()
        title = str(d.get("title") or "").strip() or ("Name" if ctype.lower() in ("name", "title") else "")
        cid = d.get("column_id") or d.get("id")
        val = d.get("value")
        defs = d.get("defaults") if isinstance(d.get("defaults"), Mapping) else None
        desc = d.get("description") if isinstance(d.get("description"), str) else None
        if ctype.lower() in ("name", "title") and val is not None:
            inferred_name = str(val)
        cols.append(ColumnSpec(type=ctype, title=title, column_id=str(cid) if cid else None, value=val, defaults=defs, description=desc))

    it = ItemSpec(name=item_name or inferred_name or "", id=item_id, group_id=group_id)
    return upsert_item(client, workspace=ws, board=bd, item=it, columns=cols, group_name=group_name, safe_updates=safe_updates)


__all__ = [
    "WorkspaceSpec",
    "BoardSpec",
    "ItemSpec",
    "ColumnSpec",
    "upsert_item",
    "upsert_item_from_dicts",
]



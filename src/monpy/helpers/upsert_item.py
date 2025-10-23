from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Set

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


class StatusColor(Enum):
    """Enum representing monday.com status column color names (canonical enum values for the API)."""
    AMERICAN_GRAY = "american_gray"
    AQUAMARINE = "aquamarine"
    BERRY = "berry"
    BLACKISH = "blackish"
    BRIGHT_BLUE = "bright_blue"
    BRIGHT_GREEN = "bright_green"
    BROWN = "brown"
    BUBBLE = "bubble"
    CHILI_BLUE = "chili_blue"
    COFFEE = "coffee"
    DARK_BLUE = "dark_blue"
    DARK_INDIGO = "dark_indigo"
    DARK_ORANGE = "dark_orange"
    DARK_PURPLE = "dark_purple"
    DARK_RED = "dark_red"
    DONE_GREEN = "done_green"
    EGG_YOLK = "egg_yolk"
    EXPLOSIVE = "explosive"
    GRASS_GREEN = "grass_green"
    INDIGO = "indigo"
    LAVENDER = "lavender"
    LILAC = "lilac"
    LIPSTICK = "lipstick"
    NAVY = "navy"
    ORCHID = "orchid"
    PEACH = "peach"
    PECAN = "pecan"
    PURPLE = "purple"
    RIVER = "river"
    ROYAL = "royal"
    SALADISH = "saladish"
    SKY = "sky"
    SOFIA_PINK = "sofia_pink"
    STEEL = "steel"
    STUCK_RED = "stuck_red"
    SUNSET = "sunset"
    TAN = "tan"
    TEAL = "teal"
    WINTER = "winter"
    WORKING_ORANGE = "working_orange"


# It appears the API is highly inconsistent with color validation during creation.
# Use a small set of safe canonical color names that are most likely to be stable.
SAFE_STATUS_COLOR_NAMES: List[str] = [
    "stuck_red", "working_orange", "done_green", "sky", "navy", "purple", "indigo", "dark_blue",
]

# Full set of accepted canonical color names for validation
_ALL_STATUS_COLOR_NAMES: set[str] = {c.value for c in StatusColor}


@dataclass
class StatusOption:
    label: str
    color: StatusColor


@dataclass
class StatusDefaults:
    options: List[StatusOption]

    def to_dict(self) -> Dict[str, Any]:
        """Build the defaults payload for a status column.

        Note on colors
        --------------
        The monday.com API expects canonical color enum names (like "sky", "done_green", etc).
        When you provide a StatusOption with a specific color via the StatusColor enum,
        that color is used directly. If a color is missing or invalid, a deterministic
        fallback from SAFE_STATUS_COLOR_NAMES is applied.
        """
        labels: List[Dict[str, Any]] = []
        for idx, opt in enumerate(self.options):
            # Get the color value from the enum; it's now a string like "sky" or "done_green"
            color_value = opt.color.value if isinstance(opt.color, StatusColor) else str(opt.color)
            labels.append({
                "index": idx,
                "label": str(opt.label),
                "color": color_value,
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


def _resolve_or_create_columns(
    client: MondayClient,
    board_id: str,
    specs: Sequence[ColumnSpec],
    *,
    strict_resolution: bool = True,
    infer_connect_from_values: bool = True,
) -> Tuple[List[ColumnSpec], Dict[str, str]]:
    """Ensure columns exist; return updated specs with column_id filled and a title->id map.

    The special type "name" is mapped to the implicit Name column id "name" and is not created.

    strict_resolution: when True, resolves by (title, type) and validates provided ids by type.
    infer_connect_from_values: when True, attempts to infer connect boards defaults from item values.
    """
    # Prefetch columns metadata to minimize calls and enable compatibility checks
    try:
        existing = client.get_columns(board_id, fields=("id", "title", "type", "settings", "settings_str"))
    except MondayAPIError:
        existing = []

    # Build fast lookup structures
    by_title: Dict[str, List[Dict[str, Any]]] = {}
    for c in existing or []:
        by_title.setdefault(str(c.get("title")), []).append(c)

    title_to_id: Dict[str, str] = {str(c.get("title")): str(c.get("id")) for c in existing or []}

    def _settings_connected_ids(col: Dict[str, Any]) -> Set[str]:
        ids = col.get("connected_board_ids") or []
        try:
            return {str(x) for x in ids}
        except Exception:
            return set()

    def _extract_connect_default_ids(d: Optional[Mapping[str, Any]]) -> Set[str]:
        if not isinstance(d, Mapping):
            return set()
        for key in ("boardIds", "board_ids", "boardId", "board_id", "connected_boards"):
            val = d.get(key)
            if isinstance(val, (list, tuple)):
                try:
                    return {str(int(x)) for x in val}
                except Exception:
                    return {str(x) for x in val}
        return set()

    def _infer_board_ids_from_value(value: Any) -> Set[str]:
        ids: List[str] = []
        if value is None:
            return set()
        if isinstance(value, (list, tuple)):
            ids = [str(v) for v in value]
        else:
            ids = [str(value)]
        out: Set[str] = set()
        for iid in ids:
            try:
                itm = client.get_item_values(str(iid), include_board=True, parse_json_values=False)
                bd = itm.get("board") or {}
                if bd.get("id") is not None:
                    out.add(str(bd.get("id")))
            except Exception:
                # best-effort
                continue
        return out

    updated_specs: List[ColumnSpec] = []
    for cs in specs:
        t = _normalize_col_type(cs.type)
        if t in ("name", "title"):
            updated_specs.append(ColumnSpec(type="name", title=cs.title or "Name", column_id="name", value=cs.value, defaults=cs.defaults, description=cs.description))
            continue

        # Validate provided id by type when strict
        cid: Optional[str] = None
        if cs.column_id:
            try:
                col = client.get_column(board_id, cs.column_id, fields=("id", "type", "title", "settings", "settings_str"))
                col_type_norm = _normalize_col_type(str(col.get("type")))
                if not strict_resolution or col_type_norm == t:
                    cid = str(col.get("id"))
                else:
                    cid = None
            except (ColumnNotFound, MondayAPIError):
                cid = None

        # Resolve by (title, type) when strict; fallback to legacy title-only when not strict
        if cid is None:
            candidates = by_title.get(cs.title, [])
            chosen: Optional[Dict[str, Any]] = None
            if candidates:
                if strict_resolution:
                    # exact type match first
                    same_type = [c for c in candidates if _normalize_col_type(str(c.get("type"))) == t]
                    # For connect boards, prefer compatible settings
                    if t == "board_relation" and same_type:
                        wanted: Set[str] = _extract_connect_default_ids(cs.defaults)
                        if infer_connect_from_values and not wanted:
                            wanted = _infer_board_ids_from_value(cs.value)
                        if wanted:
                            for c in same_type:
                                have = _settings_connected_ids(c)
                                if not have or have.issuperset(wanted):
                                    chosen = c
                                    break
                        if chosen is None and same_type:
                            # no specific requirements; pick the first
                            chosen = same_type[0]
                    else:
                        chosen = same_type[0] if same_type else None
                if not strict_resolution and not chosen:
                    chosen = candidates[0]
            if chosen is not None:
                cid = str(chosen.get("id"))

        if cid is None:
            # create with defaults when provided; normalize well-known schemas and try fallbacks for Status
            try:
                defaults_payload: Optional[Dict[str, Any]] = None
                if isinstance(cs.defaults, Mapping):
                    defaults_payload = dict(cs.defaults)

                # Connect boards: infer defaults from values when not provided
                if t == "board_relation" and (not defaults_payload or not _extract_connect_default_ids(defaults_payload)):
                    if infer_connect_from_values:
                        inferred = _infer_board_ids_from_value(cs.value)
                        if inferred:
                            defaults_payload = dict(defaults_payload or {})
                            defaults_payload["boardIds"] = [int(x) if str(x).isdigit() else x for x in inferred]

                # Status special: build normalized entries and try schema variants
                if t == "status":
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
                            raw_color = (
                                e.get("color")
                                or e.get("color_name")
                                or e.get("colorName")
                            )
                            if isinstance(raw_color, StatusColor):
                                color_str = raw_color.value
                            elif raw_color is not None:
                                try:
                                    color_str = str(raw_color).strip().lower()
                                except Exception:
                                    color_str = ""
                            else:
                                color_str = ""
                            if color_str not in _ALL_STATUS_COLOR_NAMES:
                                color_str = SAFE_STATUS_COLOR_NAMES[idx_int % len(SAFE_STATUS_COLOR_NAMES)]
                            out.append({
                                **{k: v for k, v in e.items() if k not in ("color_name", "colorName")},
                                "index": idx_int,
                                "label": str(e.get("label", "")),
                                "color": color_str,
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

                    candidates: List[Dict[str, Any]] = []
                    if entries:
                        candidates.append({"labels": entries})
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
                        if last_exc:
                            raise last_exc
                        raise MondayAPIError("Failed to create status column with provided defaults")
                else:
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
    strict_resolution: bool = True,
    aggressive_safe_updates: bool = False,
    on_missing_item: str = "error",  # one of: "error", "create", "skip"
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
        # Determine operation and target board
        ws_id = _ensure_workspace(client, workspace)
        target_board_id: Optional[str] = None
        existing_item: Optional[Dict[str, Any]] = None

        if item.id:
            try:
                existing_item = client.get_item_values(item.id, include_board=True, parse_json_values=False)
                bd = existing_item.get("board") or {}
                if bd.get("id") is not None:
                    target_board_id = str(bd.get("id"))
            except ItemNotFound:
                if on_missing_item == "create":
                    existing_item = None
                    target_board_id = None
                elif on_missing_item == "skip":
                    # no-op, return resolution context
                    return {
                        "workspace_id": ws_id,
                        "board_id": _ensure_board(client, BoardSpec(name=board.name, id=board.id, board_kind=board.board_kind), workspace_id=ws_id),
                        "item_id": str(item.id),
                        "column_ids": {},
                        "result": {},
                    }
                else:
                    # propagate for retry/outer handler
                    raise

        if not target_board_id:
            # Ensure board where we will create or where columns reside for creation
            target_board_id = _ensure_board(client, BoardSpec(name=board.name, id=board.id, board_kind=board.board_kind), workspace_id=ws_id)

        # Ensure columns on the target board
        col_specs, title_map = _resolve_or_create_columns(
            client,
            target_board_id,
            columns,
            strict_resolution=strict_resolution,
            infer_connect_from_values=True,
        )

        # Build values payload and extract item name
        values: Dict[str, Any] = {}
        item_name: str = item.name
        for cs in col_specs:
            if cs.type == "name":
                if cs.value is not None:
                    item_name = str(cs.value)
                continue
            encoded_value = _encode_value_for_type(cs.type, cs.value)

            # Prefer label for status when index provided, using actual column settings if available
            try:
                if (cs.type or "").lower() == "status" and isinstance(cs.value, Mapping) and "index" in cs.value:
                    idx_wanted = int(cs.value.get("index"))
                    # 1) from provided defaults
                    label_from_defaults: Optional[str] = None
                    if isinstance(cs.defaults, Mapping):
                        lbls = cs.defaults.get("labels")
                        entries: List[Mapping[str, Any]] = []
                        if isinstance(lbls, list):
                            entries = [e for e in lbls if isinstance(e, Mapping)]
                        elif isinstance(lbls, Mapping):
                            tmp: List[Dict[str, Any]] = []
                            for k, v in lbls.items():
                                try:
                                    ii = int(k)
                                except Exception:
                                    continue
                                if isinstance(v, Mapping):
                                    tmp.append({"index": ii, "label": str(v.get("label") or v.get("name") or "")})
                                else:
                                    tmp.append({"index": ii, "label": str(v)})
                            entries = tmp
                        for ent in entries:
                            try:
                                if int(ent.get("index")) == idx_wanted:
                                    label_from_defaults = str(ent.get("label", "")) or None
                                    break
                            except Exception:
                                continue

                    # 2) from actual column settings when column_id known
                    label_from_col: Optional[str] = None
                    if not label_from_defaults and cs.column_id:
                        try:
                            meta = client.get_column(target_board_id, cs.column_id, fields=("id", "settings", "settings_str", "type"))
                            settings = meta.get("settings", {})
                            labels = settings.get("labels") or (settings.get("labels_colors", {}) or {}).get("labels")
                            if isinstance(labels, Mapping):
                                cand = labels.get(str(idx_wanted)) or labels.get(idx_wanted)  # type: ignore[index]
                                if isinstance(cand, Mapping):
                                    label_from_col = str(cand.get("label") or cand.get("name") or "") or None
                                elif isinstance(cand, str):
                                    label_from_col = cand or None
                        except Exception:
                            pass

                    chosen_label = label_from_defaults or label_from_col
                    if chosen_label:
                        encoded_value = {"label": chosen_label}
            except Exception:
                pass

            values[cs.column_id or ""] = encoded_value

        values = {k: v for k, v in values.items() if k}

        # Create or update item
        if existing_item and item.id:
            if safe_updates:
                try:
                    client.safe_update_item_values(target_board_id, item.id, column_values=values)
                except MondayAPIError as exc:
                    if not aggressive_safe_updates:
                        raise
                    # Aggressive path: strip any columns explicitly referenced in error_data
                    try:
                        errs = getattr(exc, "errors", []) or []
                        offending: Set[str] = set()
                        for e in errs:
                            data = (e.get("extensions") or {}).get("error_data") or {}
                            cid = data.get("column_id") or data.get("columnId")
                            if cid:
                                offending.add(str(cid))
                        filtered = {k: v for k, v in values.items() if k not in offending}
                        if filtered:
                            client.update_item_values(target_board_id, item.id, column_values=filtered)
                        else:
                            # nothing left to update; treat as success
                            pass
                    except Exception:
                        # if aggressive handling fails, bubble original
                        raise
            else:
                client.update_item_values(target_board_id, item.id, column_values=values)
            result = client.get_item_values(item.id, include_board=True)
            iid = str(result.get("id"))
        else:
            gid = _ensure_group(client, target_board_id, group_id=item.group_id, group_name=group_name)
            created = client.create_item(target_board_id, group_id=gid, item_name=item_name, column_values=values)
            iid = str(created.get("id"))
            result = client.get_item_values(iid, include_board=True)

        return {
            "workspace_id": ws_id,
            "board_id": target_board_id,
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


def batch_upsert_items(
    client: MondayClient,
    *,
    workspace: WorkspaceSpec,
    board: BoardSpec,
    items_with_columns: Sequence[Tuple[ItemSpec, Sequence[ColumnSpec]]],
    group_name: Optional[str] = None,
    safe_updates: bool = True,
    strict_resolution: bool = True,
    aggressive_safe_updates: bool = False,
    on_missing_item: str = "create",  # one of: "error", "create", "skip"
) -> List[Dict[str, Any]]:
    """Create or update multiple items and their surrounding structures in batch.

    Behavior
    --------
    - Ensures the workspace and board exist (creates if missing).
    - Ensures all requested columns for all items exist with provided defaults.
    - Items without an id are created in a batch operation.
    - Items with an id are updated individually.
    - On missing-entity errors (workspace, board, column, item), re-resolves and retries once.

    Returns a list of dicts including entity ids and the item metadata for each item:
        { "workspace_id": str, "board_id": str, "item_id": str, "column_ids": {title: id}, "result": {...} }
    """

    def _execute_once() -> List[Dict[str, Any]]:
        ws_id = _ensure_workspace(client, workspace)
        board_id = _ensure_board(client, board, workspace_id=ws_id)

        all_column_specs = [cs for _, columns in items_with_columns for cs in columns]
        # Deduplicate column specs by title to avoid creating same column multiple times
        unique_column_specs: Dict[str, ColumnSpec] = {}
        for cs in all_column_specs:
            if cs.title not in unique_column_specs:
                unique_column_specs[cs.title] = cs
        
        resolved_cols, title_map = _resolve_or_create_columns(
            client,
            board_id,
            list(unique_column_specs.values()),
            strict_resolution=strict_resolution
        )
        resolved_cols_map = {c.title: c for c in resolved_cols}

        items_to_create = []
        items_to_update = []

        for item_spec, column_specs in items_with_columns:
            if item_spec.id:
                try:
                    # check if item exists
                    client.get_item_values(item_spec.id)
                    items_to_update.append((item_spec, column_specs))
                except ItemNotFound:
                    if on_missing_item == "create":
                        item_spec.id = None # Treat as new item
                        items_to_create.append((item_spec, column_specs))
                    elif on_missing_item == "skip":
                        continue
                    else:
                        raise
            else:
                items_to_create.append((item_spec, column_specs))

        all_results = []

        # Batch Create Items
        if items_to_create:
            group_id = _ensure_group(client, board_id, group_name=group_name)
            create_payloads = []
            for item_spec, column_specs in items_to_create:
                values = {}
                item_name = item_spec.name
                for cs in column_specs:
                    resolved_cs = resolved_cols_map.get(cs.title)
                    if not resolved_cs or not resolved_cs.column_id:
                        continue
                    
                    if resolved_cs.type == "name":
                        if cs.value is not None:
                            item_name = str(cs.value)
                        continue

                    values[resolved_cs.column_id] = _encode_value_for_type(resolved_cs.type, cs.value)
                create_payloads.append({"name": item_name, "values": values})

            created_items = client.create_items(board_id, group_id=group_id, items=create_payloads, return_fields=["id", "name", "column_values { id text }"])
            for item_data in created_items:
                all_results.append({
                    "workspace_id": ws_id,
                    "board_id": board_id,
                    "item_id": item_data["id"],
                    "column_ids": title_map,
                    "result": item_data,
                })

        # Individually Update Items
        for item_spec, column_specs in items_to_update:
            values = {}
            # Handle name update: name from ItemSpec is the fallback, ColumnSpec with type 'name' takes precedence.
            name_to_set = item_spec.name
            other_columns = []
            for cs in column_specs:
                if cs.type == 'name':
                    if cs.value is not None:
                        name_to_set = str(cs.value)
                else:
                    other_columns.append(cs)

            if name_to_set:
                values["name"] = name_to_set
            
            for cs in other_columns:
                resolved_cs = resolved_cols_map.get(cs.title)
                if not resolved_cs or not resolved_cs.column_id:
                    continue
                values[resolved_cs.column_id] = _encode_value_for_type(resolved_cs.type, cs.value)

            if not values:
                item_data = client.get_item_values(item_spec.id)
                all_results.append({
                    "workspace_id": ws_id,
                    "board_id": board_id,
                    "item_id": item_spec.id,
                    "column_ids": title_map,
                    "result": item_data,
                })
                continue

            if safe_updates:
                try:
                    client.safe_update_item_values(board_id, item_spec.id, column_values=values)
                except MondayAPIError as exc:
                    if not aggressive_safe_updates:
                        raise
                    
                    errs = getattr(exc, "errors", []) or []
                    offending: Set[str] = set()
                    for e in errs:
                        data = (e.get("extensions") or {}).get("error_data") or {}
                        cid = data.get("column_id") or data.get("columnId")
                        if cid:
                            offending.add(str(cid))
                    filtered = {k: v for k, v in values.items() if k not in offending}
                    if filtered:
                        client.update_item_values(board_id, item_spec.id, column_values=filtered)

            else:
                client.update_item_values(board_id, item_spec.id, column_values=values)

            item_data = client.get_item_values(item_spec.id)
            all_results.append({
                "workspace_id": ws_id,
                "board_id": board_id,
                "item_id": item_spec.id,
                "column_ids": title_map,
                "result": item_data,
            })

        return all_results

    try:
        return _execute_once()
    except (WorkspaceNotFound, BoardNotFound, ColumnNotFound, ItemNotFound, MondayAPIError):
        # Recalibrate structures and retry once
        return _execute_once()


def batch_upsert_items_from_dicts(
    client: MondayClient,
    *,
    workspace_name: str,
    board_name: str,
    items_data: Sequence[Mapping[str, Any]],
    workspace_id: Optional[str] = None,
    board_id: Optional[str] = None,
    workspace_kind: str = "open",
    board_kind: str = "public",
    group_name: Optional[str] = None,
    safe_updates: bool = True,
) -> List[Dict[str, Any]]:
    """Convenience wrapper for batch_upsert_items that accepts simple dicts.
    
    Each entry in items_data should have keys:
      - item_name (str) or a column spec with type="name"
      - columns (list of dicts), each with type, title, value
      - item_id (optional), group_id (optional)
    """
    ws = WorkspaceSpec(name=workspace_name, id=workspace_id, kind=workspace_kind)
    bd = BoardSpec(name=board_name, id=board_id, board_kind=board_kind)
    
    items_with_columns: List[Tuple[ItemSpec, List[ColumnSpec]]] = []

    for item_d in items_data:
        columns_data = item_d.get("columns", [])
        if not isinstance(columns_data, list):
            columns_data = []

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

        item_name = item_d.get("item_name") or inferred_name or ""
        item_id = item_d.get("item_id")
        group_id = item_d.get("group_id")
        it = ItemSpec(name=str(item_name), id=str(item_id) if item_id else None, group_id=str(group_id) if group_id else None)
        items_with_columns.append((it, cols))

    return batch_upsert_items(
        client,
        workspace=ws,
        board=bd,
        items_with_columns=items_with_columns,
        group_name=group_name,
        safe_updates=safe_updates,
    )


__all__ = [
    "WorkspaceSpec",
    "BoardSpec",
    "ItemSpec",
    "ColumnSpec",
    "upsert_item",
    "upsert_item_from_dicts",
    "batch_upsert_items",
    "batch_upsert_items_from_dicts",
]



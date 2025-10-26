from __future__ import annotations
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Set, Mapping

from ..client import MondayClient
from ..exceptions import (
    BoardNotFound,
    ColumnNotFound,
    ItemNotFound,
    MondayAPIError,
    SubItemNotFound,
)
from .upsert_item import (
    ColumnSpec,
    _encode_value_for_type,
    _resolve_or_create_columns,
)


@dataclass
class ParentItemSpec:
    """Specify the parent item for a subitem upsert operation."""
    id: str


@dataclass
class SubitemSpec:
    """Describe a subitem to upsert."""
    name: str
    id: Optional[str] = None


def upsert_subitem(
    client: MondayClient,
    *,
    parent_item: ParentItemSpec,
    subitem: SubitemSpec,
    columns: Sequence[ColumnSpec],
    safe_updates: bool = True,
    strict_resolution: bool = True,
    on_missing_subitem: str = "create",  # one of: "error", "create", "skip"
) -> Dict[str, Any]:
    """Create or update a subitem.

    Robust flow that does not assume a pre-existing "Subitems" column on the
    parent board. For new subitems we first create the subitem to let monday
    provision the hidden subitems board, then resolve that board id and update
    values.

    Returns a dict including entity ids and the subitem metadata:
        { "parent_item_id": str, "subitem_board_id": str, "subitem_id": str, "column_ids": {title: id}, "result": {...} }
    """

    def _execute_once() -> Dict[str, Any]:
        # Resolve existing vs new
        target_subitem_id: Optional[str] = subitem.id
        existing_subitem: Optional[Dict[str, Any]] = None
        subitem_board_id: Optional[str] = None

        # Determine desired name (column spec with type=name overrides SubitemSpec.name)
        desired_name: str = subitem.name
        for cs in columns:
            if (cs.type or "").lower() in ("name", "title") and cs.value is not None:
                desired_name = str(cs.value)
                break

        if target_subitem_id:
            try:
                existing_subitem = client.get_subitem_values(target_subitem_id, include_board=True)
                b = existing_subitem.get("board") or {}
                subitem_board_id = str(b.get("id")) if b.get("id") is not None else None
            except SubItemNotFound:
                if on_missing_subitem == "create":
                    existing_subitem = None
                    target_subitem_id = None
                elif on_missing_subitem == "skip":
                    return {
                        "parent_item_id": parent_item.id,
                        "subitem_board_id": "",
                        "subitem_id": subitem.id,
                        "column_ids": {},
                        "result": {},
                    }
                else:
                    raise
        else:
            # Try to upsert by name if a subitem with same name exists under the parent
            try:
                subs = client.list_subitems(parent_item.id, fields=["id", "name", "board { id }"])
                for si in subs or []:
                    if si.get("name") == desired_name:
                        target_subitem_id = str(si.get("id"))
                        existing_subitem = client.get_subitem_values(target_subitem_id, include_board=True)
                        b = existing_subitem.get("board") or {}
                        subitem_board_id = str(b.get("id")) if b.get("id") is not None else None
                        break
            except Exception:
                pass

        # If still no subitem id, create a new subitem first (without values)
        if not target_subitem_id:
            created = client.create_subitem(parent_item.id, item_name=desired_name)
            target_subitem_id = str(created.get("id"))
            # Resolve board id for the subitem
            fresh = client.get_subitem_values(target_subitem_id, include_board=True)
            b = fresh.get("board") or {}
            subitem_board_id = str(b.get("id")) if b.get("id") is not None else None
            existing_subitem = None

        if not subitem_board_id:
            # As a fallback, resolve via internal helper
            try:
                subitem_board_id = client._get_board_id_for_subitem(target_subitem_id)  # type: ignore[arg-type]
            except Exception:
                subitem_board_id = None
        if not subitem_board_id:
            raise BoardNotFound("Could not resolve subitem board id")

        # Ensure columns on the subitems board
        col_specs, title_map = _resolve_or_create_columns(
            client,
            subitem_board_id,
            columns,
            strict_resolution=strict_resolution,
            infer_connect_from_values=True,
        )

        # Prepare potential name update via column value
        name_to_set: Optional[str] = None
        for cs in col_specs:
            if (cs.type or "").lower() in ("name", "title") and cs.value is not None:
                name_to_set = str(cs.value)
                break

        # Build payload
        values: Dict[str, Any] = {}
        if name_to_set:
            values["name"] = name_to_set

        for cs in col_specs:
            tnorm = (cs.type or "").lower()
            if tnorm in ("name", "title"):
                continue
            encoded_value = _encode_value_for_type(cs.type, cs.value)

            # Normalize status index -> label to avoid index drift
            try:
                if tnorm == "status" and isinstance(cs.value, Mapping) and "index" in cs.value:
                    idx_wanted = int(cs.value.get("index"))
                    # 1) try provided defaults
                    label_from_defaults: Optional[str] = None
                    if isinstance(cs.defaults, Mapping):
                        lbls = cs.defaults.get("labels")
                        entries: list[Mapping[str, Any]] = []
                        if isinstance(lbls, list):
                            if lbls and all(isinstance(x, str) for x in lbls):
                                entries = [{"index": i, "label": str(x)} for i, x in enumerate(lbls)]
                            else:
                                entries = [e for e in lbls if isinstance(e, Mapping)]
                        elif isinstance(lbls, Mapping):
                            tmp: list[dict[str, Any]] = []
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
                    # 2) fall back to actual column labels
                    label_from_col: Optional[str] = None
                    if not label_from_defaults and cs.column_id:
                        try:
                            meta = client.get_column(subitem_board_id, cs.column_id, fields=("id", "settings", "settings_str", "type"))
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

            if cs.column_id:
                values[cs.column_id] = encoded_value
        values = {k: v for k, v in values.items() if k}

        # Update values when any provided
        if values:
            client.update_subitem_values(target_subitem_id, board_id=subitem_board_id, column_values=values)  # type: ignore[arg-type]

        # Return final state
        result = client.get_subitem_values(target_subitem_id, include_board=True)  # type: ignore[arg-type]
        return {
            "parent_item_id": parent_item.id,
            "subitem_board_id": subitem_board_id,
            "subitem_id": target_subitem_id,
            "column_ids": {c.title: c.column_id for c in col_specs},
            "result": result,
        }

    try:
        return _execute_once()
    except (BoardNotFound, ColumnNotFound, ItemNotFound, SubItemNotFound, MondayAPIError):
        return _execute_once()

__all__ = [
    "ParentItemSpec",
    "SubitemSpec",
    "upsert_subitem",
]

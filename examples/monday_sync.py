from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from datetime import date

from monpy.client import MondayClient
from monpy.oo import Session
from monpy.oo.utils import to_attr
from monpy.oo.columns.values import _encode_value  # internal encoder, used for examples


class SyncRuleset:
    pass


def upsert_items_one_post(
    client: MondayClient,
    *,
    board_id: str,
    group_id: str,
    new_items: Sequence[Dict[str, Any]],
    updates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Perform a single GraphQL mutation containing any mix of:
      - create_item calls (for new items)
      - change_multiple_column_values calls (for existing items)

    Parameters
    ----------
    client: MondayClient
        Low-level client used to issue one mutation.
    board_id, group_id: str
        Target board/group for new items. Updates can override board per item via spec.
    new_items: Sequence[dict]
        Each: { "name": str, "values": dict[str, Any] } – values are by column_id.
    updates: Sequence[dict]
        Each: { "item_id": str, "values": dict[str, Any], "board_id"?: str }

    Returns
    -------
    dict
        Raw GraphQL data keyed by alias (e.g. {"c1": {"id": ...}, "u1": {"id": ...}}).
    """
    parts: List[str] = []
    var_decls: List[str] = []
    vars_payload: Dict[str, Any] = {}

    # --- creates -------------------------------------------------------
    for idx, spec in enumerate(new_items or [], start=1):
        alias = f"c{idx}"
        nb, ng, nn, nv = f"nb{idx}", f"ng{idx}", f"nn{idx}", f"nv{idx}"
        parts.append(
            f"{alias}: create_item(board_id:${nb}, group_id:${ng}, item_name:${nn}, column_values:${nv}){{ id }}"
        )
        var_decls.extend([f"${nb}: ID!", f"${ng}: String!", f"${nn}: String!", f"${nv}: JSON"])
        vals: Dict[str, Any] = dict(spec.get("values") or {})
        # Align with client helpers: coerce text-typed columns to str when possible
        try:
            client._coerce_text_values(board_id, vals)  # type: ignore[attr-defined]
        except Exception:
            pass
        vars_payload[nb] = spec.get("board_id") or board_id
        vars_payload[ng] = spec.get("group_id") or group_id
        vars_payload[nn] = spec.get("name") or ""
        vars_payload[nv] = json.dumps(vals)

    # --- updates -------------------------------------------------------
    for idx, spec in enumerate(updates or [], start=1):
        alias = f"u{idx}"
        ub, ui, uv = f"ub{idx}", f"ui{idx}", f"uv{idx}"
        parts.append(
            f"{alias}: change_multiple_column_values(board_id:${ub}, item_id:${ui}, column_values:${uv}){{ id }}"
        )
        var_decls.extend([f"${ub}: ID!", f"${ui}: ID!", f"${uv}: JSON!"])
        vals: Dict[str, Any] = dict(spec.get("values") or {})
        bid = spec.get("board_id") or board_id
        try:
            client._coerce_text_values(bid, vals)  # type: ignore[attr-defined]
        except Exception:
            pass
        vars_payload[ub] = bid
        vars_payload[ui] = str(spec["item_id"])  # ensure ID-like
        vars_payload[uv] = json.dumps(vals)

    if not parts:
        return {}

    mutation = f"mutation({', '.join(var_decls)}) {{ {' '.join(parts)} }}"
    return client.mutation(mutation, vars_payload)


def batch_update_with_transaction(
    session: Session,
    updates: Sequence[Dict[str, Any]],
) -> None:
    """
    OO approach: batch updates to many items into ONE request using a transaction.

    Each update must include: { "item_id": str, "board_id": str, "values": dict[str, Any] }
    Values are by column_id. On commit, compatible updates are sent in one mutation.
    """
    if not updates:
        return
    with session.transaction():
        for spec in updates:
            bid = str(spec["board_id"])
            iid = str(spec["item_id"])
            vals = dict(spec.get("values") or {})
            # Schedule for batched flush on commit
            session._schedule_item_update(board_id=bid, item_id=iid, column_values=vals)  # noqa: SLF001


@dataclass
class NewItemByAttr:
    name: str
    attrs: Dict[str, Any]
    board_id: Optional[str] = None
    group_id: Optional[str] = None


@dataclass
class UpdateItemByAttr:
    item_id: str
    attrs: Dict[str, Any]
    board_id: Optional[str] = None


def _encode_values_by_attr(session: Session, board_id: str, attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Translate attribute names to column IDs and JSON-encode values appropriately."""
    if not attrs:
        return {}
    board = session.board(board_id)
    out: Dict[str, Any] = {}
    for raw_attr, value in attrs.items():
        norm = to_attr(raw_attr)
        try:
            col = board.columns.by_attr(norm)
        except KeyError:
            # best-effort refresh if columns changed recently
            board.refresh()
            col = board.columns.by_attr(norm)
        out[col.id] = _encode_value(col.type, value)
    return out


def upsert_items_one_post_by_attr(
    session: Session,
    *,
    board_id: str,
    group_id: str,
    new_items: Sequence[NewItemByAttr],
    updates: Sequence[UpdateItemByAttr],
) -> Dict[str, Any]:
    """
    One-POST upsert using attribute names instead of raw column IDs.
    Internally maps attrs -> column_ids and encodes values with the OO layer.
    """
    # Map to raw payloads expected by upsert_items_one_post
    new_payload: List[Dict[str, Any]] = []
    for spec in new_items or []:
        b_id = spec.board_id or board_id
        g_id = spec.group_id or group_id
        values = _encode_values_by_attr(session, b_id, spec.attrs)
        new_payload.append({
            "name": spec.name,
            "board_id": b_id,
            "group_id": g_id,
            "values": values,
        })

    upd_payload: List[Dict[str, Any]] = []
    for spec in updates or []:
        b_id = spec.board_id or board_id
        values = _encode_values_by_attr(session, b_id, spec.attrs)
        upd_payload.append({
            "item_id": spec.item_id,
            "board_id": b_id,
            "values": values,
        })

    return upsert_items_one_post(
        session.client,
        board_id=board_id,
        group_id=group_id,
        new_items=new_payload,
        updates=upd_payload,
    )


def example_usage() -> None:
    """
    Sketch of how you might call the helpers.
    Not executed by default; fill in your token/ids and run manually.
    """
    # from os import environ
    # token = environ["MONDAY_TOKEN"]
    # client = MondayClient(token)
    # session = Session(client)
    #
    # board_id = "123456789"
    # group_id = "topics"
    #
    # new_items = [
    #     {"name": "New A", "values": {"status": {"index": 1}}},
    #     {"name": "New B", "values": {"text": "hello"}},
    # ]
    # existing = [
    #     {"item_id": "987654321", "board_id": board_id, "values": {"status": {"index": 2}}},
    # ]
    #
    # # Option 1: truly one POST mixing creates and updates (IDs)
    # resp = upsert_items_one_post(client, board_id=board_id, group_id=group_id, new_items=new_items, updates=existing)
    # print(resp)
    #
    # # Option 2: only updates, via OO transaction (one POST on commit)
    # batch_update_with_transaction(session, existing)
    #
    # # Option 3: one POST upsert but using attribute names (more OO-friendly)
    # new_by_attr = [
    #     NewItemByAttr(name="New C", attrs={"status": "Done", "due_date": date(2025, 1, 1)}),
    # ]
    # upd_by_attr = [
    #     UpdateItemByAttr(item_id="987654321", attrs={"status": {"index": 2}}),
    # ]
    # resp2 = upsert_items_one_post_by_attr(session, board_id=board_id, group_id=group_id, new_items=new_by_attr, updates=upd_by_attr)
    # print(resp2)


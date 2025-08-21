from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import json

from monpy.client import MondayClient


class Transaction:
    def __init__(self, session: "Session", *, safe: bool = False) -> None:
        self._session = session
        self._ops: List[Callable[[], None]] = []
        self._committed: bool = False
        self._safe: bool = safe

    def add(self, op: Callable[[], None]) -> None:
        self._ops.append(op)

    def commit(self) -> None:
        if self._committed:
            return
        self._session._flush_ops(self._ops)
        self._committed = True

    def __enter__(self) -> "Transaction":
        self._session._active_tx = self
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if exc is None:
                self.commit()
        finally:
            self._session._active_tx = None


class Session:
    """Unit-of-Work facade over the low-level client.

    Provides identity mapping of loaded entities and a transaction/flush API.
    """

    def __init__(self, client: MondayClient, *, values_cache_ttl: Optional[float] = None) -> None:
        self.client = client
        self._identity: Dict[Tuple[str, str], Any] = {}
        self._active_tx: Optional[Transaction] = None
        # Optional TTL (seconds) for column values read caching at the item level
        self.values_cache_ttl: Optional[float] = values_cache_ttl

    # --- transactions --------------------------------------------------
    def transaction(self, *, safe: bool = False) -> Transaction:
        return Transaction(self, safe=safe)

    # --- op flushing (placeholder – will batch compatible ops) ---------
    def _flush_ops(self, ops: List[Callable[[], None]]) -> None:
        # If current transaction is marked safe, perform serial safe updates
        if getattr(self, "_active_tx", None) is not None and getattr(self._active_tx, "_safe", False):
            for op in ops:
                if isinstance(op, _UpdateItemValuesOp):
                    # Use safe update to skip invalid columns automatically
                    self.client.safe_update_item_values(op.board_id, op.item_id, column_values=op.column_values)
                else:
                    op()
            return

        # Otherwise, attempt to batch compatible update_item_values ops
        batch: List[tuple[str, str, Dict[str, Any]]] = []
        serial: List[Callable[[], None]] = []

        for op in ops:
            if isinstance(op, _UpdateItemValuesOp):
                batch.append((op.board_id, op.item_id, op.column_values))
            else:
                serial.append(op)

        if batch:
            self._execute_batched_item_updates(batch)
        for op in serial:
            op()

    def _execute_batched_item_updates(self, updates: List[tuple[str, str, Dict[str, Any]]]) -> None:
        # Build one mutation with aliases
        parts: List[str] = []
        var_decls: List[str] = []
        vars_payload: Dict[str, Any] = {}
        for idx, (board_id, item_id, values) in enumerate(updates, start=1):
            parts.append(
                f"u{idx}: change_multiple_column_values(board_id:$b{idx}, item_id:$i{idx}, column_values:$v{idx}){{ id }}"
            )
            var_decls.extend([f"$b{idx}: ID!", f"$i{idx}: ID!", f"$v{idx}: JSON!"])
            vars_payload[f"b{idx}"] = board_id
            vars_payload[f"i{idx}"] = item_id
            vars_payload[f"v{idx}"] = json.dumps(values)

        mutation = f"mutation({', '.join(var_decls)}) {{ {' '.join(parts)} }}"
        self.client.mutation(mutation, vars_payload)

    # --- factories (lazy loads) ---------------------------------------
    def workspace(self, workspace_id: str):
        from .workspace import Workspace
        key = ("workspace", workspace_id)
        ws = self._identity.get(key)
        if ws is None:
            raw = self.client.get_workspace(workspace_id)
            ws = Workspace(
                id=str(raw["id"]),
                name=raw.get("name"),
                kind=raw.get("kind"),
                description=raw.get("description"),
            )
            ws._session = self
            self._identity[key] = ws
        return ws

    def board(self, board_id: str):
        from .board import Board
        key = ("board", board_id)
        bd = self._identity.get(key)
        if bd is None:
            raw = self.client.get_board(board_id)
            bd = Board(
                id=str(raw["id"]),
                name=raw.get("name"),
                board_kind=raw.get("board_kind"),
                state=raw.get("state"),
                workspace_id=str(raw.get("workspace_id")),
                updated_at=raw.get("updated_at"),
            )
            bd._session = self
            self._identity[key] = bd
        return bd

    # --- creation helpers ---------------------------------------------
    def create_board(self, *, workspace_id: str, name: str, board_kind: str = "public") -> "Board":
        """Create a board and return an OO Board bound to this session."""
        raw = self.client.create_board(name=name, board_kind=board_kind, workspace_id=workspace_id)
        # Eagerly cache and return the OO wrapper
        from .board import Board
        bd = Board(
            id=str(raw["id"]),
            name=raw.get("name"),
            board_kind=raw.get("board_kind"),
            state=raw.get("state"),
            workspace_id=str(raw.get("workspace_id")),
            updated_at=raw.get("updated_at"),
        )
        bd._session = self
        self._identity[("board", bd.id)] = bd
        return bd

    def item(self, item_id: str, *, board_id: Optional[str] = None):
        from .item import Item
        from .subitem import SubItem
        key = ("item", item_id)
        it = self._identity.get(key)
        if it is None:
            raw = self.client.get_item_values(item_id)
            b_id = board_id or str(raw.get("board", {}).get("id") if raw.get("board") else "")
            # Heuristic: if the item has a parent_item in API schema, treat via SubItem loader (not available in get_item_values); fallback stays Item.
            # We provide explicit subitem(session, id) below for correctness.
            it = Item(
                    id=str(raw["id"]),
                    name=raw.get("name"),
                    state=raw.get("state"),
                    updated_at=raw.get("updated_at"),
                    board_id=str(b_id),
                )
            it._session = self
            self._identity[key] = it
        return it

    def subitem(self, subitem_id: str):
        from .subitem import SubItem
        key = ("subitem", subitem_id)
        si = self._identity.get(key)
        if si is None:
            raw = self.client.get_subitem_values(subitem_id, include_board=True)
            b_id = str(raw.get("board", {}).get("id") if raw.get("board") else "")
            si = SubItem(
                id=str(raw["id"]),
                name=raw.get("name"),
                state=raw.get("state"),
                updated_at=raw.get("updated_at"),
                board_id=b_id,
            )
            si._session = self
            self._identity[key] = si
        return si

    # --- scheduling helpers -------------------------------------------
    def _schedule_item_update(self, *, board_id: str, item_id: str, column_values: Dict[str, Any]) -> None:
        if self._active_tx is not None:
            self._active_tx.add(_UpdateItemValuesOp(session=self, board_id=board_id, item_id=item_id, column_values=column_values))
        else:
            self.client.update_item_values(board_id, item_id, column_values=column_values)


class _UpdateItemValuesOp:
    def __init__(self, *, session: Session, board_id: str, item_id: str, column_values: Dict[str, Any]) -> None:
        self._session = session
        self.board_id = board_id
        self.item_id = item_id
        self.column_values = column_values

    def __call__(self) -> None:
        self._session.client.update_item_values(self.board_id, self.item_id, column_values=self.column_values)



from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient, Session, build_workspace_board_item_tree  # noqa: E402
from inventory_usage import _load_config, _build_client_from_config


from typing import Optional
from monpy.oo import Item
from monpy.oo import Board
from monpy.oo.enums import BoardKind
from monpy.oo import Column
from monpy.oo.enums import ColumnType


def move_item_to_board(sess: Session, *, item_id: str, dest_board_id: str, dest_group_id: Optional[str] = None) -> Item:
    """
    Move an item to another board using the OO API and return the moved Item
    bound to the destination board.

    - If dest_group_id is provided, the item is placed in that group; otherwise,
      Monday will use its default group for the destination board.
    """
    # Use a lightweight OO wrapper to avoid an unnecessary read
    it = Item(id=str(item_id)).bind(sess)
    res = it.move_to_board(str(dest_board_id), group_id=(str(dest_group_id) if dest_group_id is not None else None))
    new_id = str(res["id"])
    # Return an OO Item bound to the same session for immediate use
    return sess.item(new_id, board_id=str(dest_board_id))


def create_board_in_workspace(
    session: Session,
    *,
    workspace_id: str,
    name: str,
    board_kind: BoardKind = BoardKind.PUBLIC,
) -> Board:
    return session.create_board(workspace_id=workspace_id, name=name, board_kind=board_kind.value)


def create_column_on_board(
    client: MondayClient,
    *,
    board_id: str,
    title: str,
    column_type: ColumnType,
    defaults: dict | None = None,
    description: str | None = None,
) -> Column:
    sess = Session(client)
    board = sess.board(board_id)
    return board.create_column(
        title=title,
        column_type=column_type.value,
        defaults=defaults,
        description=description,
    )


def main() -> int:
    client = _build_client_from_config()
    session = Session(client)  # type: ignore[arg-type]
    tree = build_workspace_board_item_tree(session)

    for ws in tree:
        print(f"Workspace: {ws.name or ''} ({ws.id})")
        boards = getattr(ws, "boards", [])
        for b in boards:
            items = getattr(b, "items", [])
            print(f"  - Board: {b.name or ''} ({b.id}) items={len(items)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

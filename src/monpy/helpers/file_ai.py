from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from ..oo import Session
from ..oo.utils import to_attr


@dataclass
class WorkArea:
    """Resolved workspace/board and target column attributes.

    This structure captures the identifiers and normalized attribute names needed
    to perform file upload and AI text extraction polling on a specific board.
    """

    workspace_id: str
    board_id: str
    text_attr: str
    files_attr: str


def resolve_work_area(
    session: Session,
    *,
    workspace_name: str,
    board_name: str,
    text_column_title: str,
    files_column_title: str,
) -> WorkArea:
    """Resolve workspace, board and column attributes for the workflow.

    - Looks up the workspace by exact name, the board by name within the workspace,
      and normalizes the provided column titles into attribute names used by the OO layer.
    - Raises ``SystemExit`` if the workspace/board are not found, matching existing examples' behavior.
    """

    client = session.client

    # Workspace by name
    workspaces = client.list_workspaces(limit=100, fields=("id", "name"))
    ws = next((w for w in workspaces if w.get("name") == workspace_name), None)
    if not ws:
        raise SystemExit(f'Workspace "{workspace_name}" not found')
    workspace_id = str(ws["id"])  # type: ignore[index]

    # Board by name within workspace
    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name"))
    b = next((x for x in boards if x.get("name") == board_name), None)
    if not b:
        raise SystemExit(f'Board "{board_name}" not found in workspace "{workspace_name}"')
    board_id = str(b["id"])  # type: ignore[index]

    # Normalize titles to attribute names and validate they exist
    bd = session.board(board_id)
    cols = bd.columns
    text_attr = to_attr(text_column_title)
    files_attr = to_attr(files_column_title)
    _ = cols.by_attr(text_attr)
    _ = cols.by_attr(files_attr)

    return WorkArea(workspace_id=workspace_id, board_id=board_id, text_attr=text_attr, files_attr=files_attr)


def _default_group_id(session: Session, board_id: str) -> str:
    groups = session.client.list_groups(board_id)
    if not groups:
        # Fallback to common default id used by monday for the first group
        return "topics"
    return str(groups[0]["id"])  # type: ignore[index]


def upload_file_to_board_for_ai(
    session: Session,
    *,
    work: WorkArea,
    file_path: Path,
) -> Tuple[str, str]:
    """Create an item and upload a file to the Files column.

    Returns a tuple ``(item_id, board_id)``.
    """

    bd = session.board(work.board_id)
    group_id = _default_group_id(session, bd.id)
    item = bd.create_item(group_id=group_id, item_name=file_path.name)
    with open(file_path, "rb") as f:
        item.upload_file(column_attr=work.files_attr, file_obj=f, filename=file_path.name)
    return item.id, bd.id


def poll_text_from_item(
    session: Session,
    *,
    item_id: str,
    board_id: str,
    text_attr: str,
    timeout_seconds: float = 300.0,
    interval_seconds: float = 5.0,
) -> Optional[str]:
    """Poll the given text column until it has a non-empty value or timeout.

    Returns the text when available; otherwise ``None`` on timeout.
    """

    start = time.time()
    item = session.item(item_id, board_id=board_id)

    while True:
        try:
            val = getattr(item.values, text_attr)
        except AttributeError:
            # Column not found by attr; refresh board columns once and retry
            bd = session.board(board_id)
            bd.refresh()
            val = getattr(item.values, text_attr)

        if isinstance(val, str) and val.strip():
            return val

        if (time.time() - start) >= float(timeout_seconds):
            return None

        time.sleep(float(interval_seconds))


__all__ = [
    "WorkArea",
    "resolve_work_area",
    "upload_file_to_board_for_ai",
    "poll_text_from_item",
]



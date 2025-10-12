from __future__ import annotations

import io
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient, Session  # noqa: E402


# Hardcoded lookup targets
WORKSPACE_NAME = "_sys-workspace-backend"
BOARD_NAME = "CV Extractor"
TEXT_COL_TITLE = "Extract from file"
FILES_COL_TITLE = "Files"


@dataclass
class WorkArea:
    workspace_id: str
    board_id: str
    text_attr: str
    files_attr: str


def _resolve_board_and_columns(sess: Session, workspace_name: str, board_name: str, text_title: str, files_title: str) -> WorkArea:
    client = sess.client

    # Find workspace by exact name
    workspaces = client.list_workspaces(limit=100, fields=("id", "name"))
    ws = next((w for w in workspaces if w.get("name") == workspace_name), None)
    if not ws:
        raise SystemExit(f'Workspace "{workspace_name}" not found')
    workspace_id = str(ws["id"])

    # Find board by exact name within the workspace
    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name"))
    b = next((x for x in boards if x.get("name") == board_name), None)
    if not b:
        raise SystemExit(f'Board "{board_name}" not found in workspace "{workspace_name}"')
    board_id = str(b["id"])

    # Resolve column attribute names using OO column normalization
    bd = sess.board(board_id)
    cols = bd.columns
    # The OO layer normalizes titles to attribute names via to_attr()
    from monpy.oo.utils import to_attr  # local import to avoid global dependency at module import

    text_attr = to_attr(text_title)
    files_attr = to_attr(files_title)

    # Access to ensure they exist; will raise if missing
    _ = cols.by_attr(text_attr)
    _ = cols.by_attr(files_attr)

    return WorkArea(workspace_id=workspace_id, board_id=board_id, text_attr=text_attr, files_attr=files_attr)


def get_work_area(sess: Session) -> WorkArea:
    """Find the workspace, board and target columns.

    - Workspace name: "_sys-workspace-backend"
    - Board name: "CV Extractor"
    - Text column title: "Extract from file"
    - Files column title: "Files"
    """
    return _resolve_board_and_columns(
        sess,
        WORKSPACE_NAME,
        BOARD_NAME,
        TEXT_COL_TITLE,
        FILES_COL_TITLE,
    )


def _default_group_id(sess: Session, board_id: str) -> str:
    groups = sess.client.list_groups(board_id)
    if not groups:
        # Fallback to common default id used by monday for the first group
        return "topics"
    # Prefer the first group
    return str(groups[0]["id"])


def upload_cv_for_parsing(sess: Session, *, work: WorkArea, file_path: Path) -> Tuple[str, str]:
    """Create an item on the board and upload the CV into the Files column.

    Returns (item_id, board_id).
    """
    bd = sess.board(work.board_id)
    group_id = _default_group_id(sess, bd.id)
    item = bd.create_item(group_id=group_id, item_name=file_path.name)

    # Upload file content to the Files column using OO helper
    with open(file_path, "rb") as f:
        # Item.upload_file expects the column attribute name
        item.upload_file(column_attr=work.files_attr, file_obj=f, filename=file_path.name)

    return item.id, bd.id


def check_on_text(sess: Session, *, item_id: str, board_id: str, text_attr: str, timeout_seconds: float = 300.0, interval_seconds: float = 5.0) -> Optional[str]:
    """Poll the item's text column until it becomes non-empty or timeout.

    Returns the string value when available, or None on timeout.
    """
    start = time.time()
    item = sess.item(item_id, board_id=board_id)

    while True:
        try:
            val = getattr(item.values, text_attr)
        except AttributeError:
            # Column not found by attr; refresh board columns once and retry
            bd = sess.board(board_id)
            bd.refresh()
            val = getattr(item.values, text_attr)

        if isinstance(val, str) and val.strip():
            return val

        if (time.time() - start) >= float(timeout_seconds):
            return None

        time.sleep(float(interval_seconds))


def _load_config() -> dict:
    """Load config from tests/config.json file."""
    cfg = Path(__file__).resolve().parents[1] / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _build_client_from_config() -> MondayClient:
    """Build MondayClient using API token from tests/config.json."""
    config = _load_config()
    token = config.get("MONDAY_API_TOKEN") or config.get("token")
    if not token:
        raise SystemExit("Live tests require tests/config.json with MONDAY_API_TOKEN or token")
    client = MondayClient(token=token)
    # Optional: allow a few retries on 403 edge cases if the caller configures it via config
    try:
        client.retries = int(config.get("RETRIES", "0"))
    except Exception:
        pass
    return client


def main() -> int:
    # Hardcoded file path relative to this script
    rel = Path(__file__).with_name("sample_cv.pdf")
    file_path = rel if rel.exists() else Path("sample_cv.pdf")
    if not file_path.exists():
        raise SystemExit(f"Sample file not found: {file_path} (place a file named 'sample_cv.pdf' next to this script)")

    client = _build_client_from_config()
    sess = Session(client, values_cache_ttl=2.0)

    work = get_work_area(sess)
    item_id, board_id = upload_cv_for_parsing(sess, work=work, file_path=file_path)

    text = check_on_text(sess, item_id=item_id, board_id=board_id, text_attr=work.text_attr)
    if text is None:
        print("Timed out waiting for extracted text.")
        return 2

    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from monpy.client import MondayClient
from monpy.oo import Session


def _load_config() -> Dict[str, Any]:
    """Load config from tests/config.json file (ignored by git)."""
    cfg = Path(__file__).resolve().parents[1] / "tests" / "config.json"
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def _build_client_from_config() -> MondayClient | None:
    """Build MondayClient using API token from tests/config.json. Returns None if unavailable."""
    config = _load_config()
    token = config.get("MONDAY_API_TOKEN") or config.get("token")
    if not token:
        return None
    return MondayClient(token=token)


def get_file_ids_from_item(session: Session, item_id: str, board_id: str, file_column_name: str):
    """Get the list of file IDs in a field of an item."""
    board = session.board(board_id)
    item = board.item(item_id)
    files = item.list_files(column_attr=file_column_name)
    print(f"Found {len(files)} file(s) in column '{file_column_name}' for item {item_id}:")
    for file_info in files:
        print(f"  - Asset ID: {file_info.get('asset_id')}, Name: {file_info.get('name')}")
    return [f.get("asset_id") for f in files]


def upload_file_to_item(session: Session, item_id: str, board_id: str, file_column_name: str, file_path: str | Path) -> str | None:
    """Upload a file to a file field and return the new asset ID."""
    p = Path(file_path)
    if not p.exists():
        print(f"File not found: {file_path}")
        return None

    board = session.board(board_id)
    item = board.item(item_id)

    print(f"Uploading '{p.name}' to column '{file_column_name}' for item {item_id}...")
    with open(p, "rb") as f:
        uploaded_file_data = item.upload_file(column_attr=file_column_name, file_obj=f, filename=p.name)
    
    asset_id = uploaded_file_data.get("id")
    if asset_id:
        print(f"Successfully uploaded file. New Asset ID: {asset_id}")
    else:
        print("Failed to upload file.")

    return asset_id


def example_call():
    """Minimal example for manual runs."""
    client = _build_client_from_config()
    if not client:
        print("No tests/config.json token found; skipping live call.")
        return

    session = Session(client)

    # --- Configuration ---
    # Please replace these values with your actual board, item, and column details.
    # You can create a dummy board for testing this script.
    BOARD_ID = "1234567890"  # IMPORTANT: Replace with your board ID
    ITEM_ID = "1234567890"   # IMPORTANT: Replace with your item ID
    FILE_COLUMN_NAME = "Files"  # IMPORTANT: Replace with your file column's name
    
    # Create a dummy file to upload
    dummy_file_path = Path("sample_upload.txt")
    dummy_file_path.write_text("This is a test file for the monday.com API.")


    print("--- 1. Listing existing files ---")
    get_file_ids_from_item(session, item_id=ITEM_ID, board_id=BOARD_ID, file_column_name=FILE_COLUMN_NAME)

    print("\n--- 2. Uploading a new file ---")
    upload_file_to_item(session, item_id=ITEM_ID, board_id=BOARD_ID, file_column_name=FILE_COLUMN_NAME, file_path=dummy_file_path)

    print("\n--- 3. Verifying file upload by listing files again ---")
    get_file_ids_from_item(session, item_id=ITEM_ID, board_id=BOARD_ID, file_column_name=FILE_COLUMN_NAME)

    # Clean up the dummy file
    dummy_file_path.unlink()


if __name__ == "__main__":
    example_call()

import json
import os
from pathlib import Path
from typing import Dict, Any

from monpy import MondayClient
from monpy.oo import Session
from monpy.helpers import fetch_board_data, enable_graphql_trace


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


config = _load_config()
token = config.get("MONDAY_API_TOKEN") or config.get("token")


def _as_bool(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    return s in {"1", "true", "yes", "on", "y"}


# DEBUG can be set via env (preferred) or tests/config.json
DEBUG = _as_bool(os.getenv("DEBUG", config.get("DEBUG")))

client = MondayClient(token=token, dev_mode=DEBUG, max_retries=6, backoff=1.5)

# Optional: set TRACE_GRAPHQL=1 to print every GraphQL call (noisy)
if DEBUG and _as_bool(os.getenv("TRACE_GRAPHQL", "0")):
    enable_graphql_trace(client, print_success=False)

sess = Session(client, values_cache_ttl=2.0)

rows = fetch_board_data(
    sess,
    workspace_name="People & Talent Ops",
    board_name="People",
    columns={
        "First Name": "text",
        "Last Name": "text",
        "Phone": "phone",                # text value
        "Email": "email",                # text value
        "Candidate Category": "status",  # label text
        "GER": "status",
        "ENG": "status",
        "BUL": "status",
        "HUN": "status",
        "GDPR Date": "date",            # ISO date string
        "Gender": "status",
    },
    state="active",
    include_subitems=False,
    batch_size=100,
    max_retries=6,
    debug=DEBUG,
    logger=(print if DEBUG else None),
)

if DEBUG:
    for row in rows:
        print(row)
    print(len(rows))

# Sanity check: count top-level items directly via iterator
if DEBUG:
    workspaces = client.list_workspaces(limit=100, fields=("id", "name"))
    ws = next((w for w in workspaces if w.get("name") == "People & Talent Ops"), None)
    if ws:
        boards = client.list_boards(limit=500, workspace_id=str(ws.get("id")), fields=("id", "name"))
        bd = next((b for b in boards if b.get("name") == "People"), None)
        if bd:
            board_id = str(bd.get("id"))
            count = 0
            for _ in client.iter_items(board_id, page_size=200, state="active", fields=["id"]):
                count += 1
            print("Top-level active items (iterator):", count)

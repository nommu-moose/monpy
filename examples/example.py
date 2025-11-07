import json
from pathlib import Path
from typing import Dict, Any

from monpy import MondayClient
from monpy.oo import Session
from monpy.helpers import fetch_board_data


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
client = MondayClient(token=token, dev_mode=True, max_retries=6, backoff=1.5)
sess = Session(client, values_cache_ttl=2.0)

rows = fetch_board_data(
    sess,
    workspace_name="People & Talent Ops",
    board_name="People",
    columns={
        "First Name": "text",
        "Last Name": "text",
        "Phone": "phone",               # text value
        "Email": "email",               # text value
        "Candidate Category": "status", # label text
        "GER": "status",
        "ENG": "status",
        "BUL": "status",
        "HUN": "status",
        "GDPR Date": "date",            # ISO date string
        "Gender": "status",
    },
    # state="active",
    # limit=500,
)

for row in rows:
    print(row)

print(len(rows))

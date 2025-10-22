from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union


# Ensure repository "src" is importable when running this script directly
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from monpy import MondayClient  # noqa: E402
from monpy.helpers import (  # noqa: E402
    BoardSpec,
    ColumnSpec,
    ItemSpec,
    StatusColor,
    WorkspaceSpec,
    upsert_item,
)


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


def _to_id_list(v: Optional[Union[str, int, Sequence[Union[str, int]]]]) -> Optional[List[int]]:
    """Normalize a variety of id inputs to a list of ints.

    None -> None; ""/[] -> []; scalar -> [int]; sequence -> [int(x) if coercible].
    """
    if v is None:
        return None
    if isinstance(v, (str, int)):
        s = str(v).strip()
        if not s:
            return []
        try:
            return [int(s)]
        except Exception:
            return []
    out: List[int] = []
    for x in list(v):
        try:
            s = str(x).strip()
            if s:
                out.append(int(s))
        except Exception:
            continue
    return out


def upsert_job_item(
    monday_client: MondayClient,
    *,
    workspace_name: str,
    board_name: str,
    # Optional entity identifiers – can be None
    workspace_id: Optional[str] = None,
    board_id: Optional[str] = None,
    item_id: Optional[str] = None,
    # Item fields (all optional; empty/None creates the column and sets empty where applicable)
    name: Optional[str] = None,  # Opening → text
    teid: Optional[str] = None,  # TEID → text
    mode: Optional[int] = None,  # Mode → status (index)
    hours: Optional[int] = None,  # Hours → status (index)
    profession: Optional[Sequence[Union[str, int]]] = None,  # Prof. Field → tags
    skills: Optional[str] = None,  # Skills → text
    client: Optional[Sequence[Union[str, int]]] = None,  # Client → connect boards; if None skip
    candidates: Optional[Sequence[Union[str, int]]] = None,  # Candidates → connect boards; if None skip
    locations: Optional[str] = None,  # Locations → text
    langs: Optional[str] = None,  # Lang → text
    # Connect Boards configuration – if None, skip creating/updating connect columns entirely
    connect_board_ids: Optional[Sequence[Union[str, int]]] = None,
    # Additional knobs
    group_name: Optional[str] = None,
    safe_updates: bool = True,
) -> Dict[str, Any]:
    """
    Upsert a "Jobs Board" item with the required columns.

    Notes:
    - Client/Candidates (connect boards):
      - If connect_board_ids is None → do not create or change these columns
      - If the corresponding value is None → do not set that column
      - If the corresponding value is [] → set the column to empty
    - Tags (profession): expects a list of strings representing tag IDs; non-numeric entries are ignored.
    - Returns column IDs keyed by "<param>_col_id" for the columns that were created/updated,
      plus entity ids: workspace_id, board_id, item_id.
    """

    # Build defaults for status palettes
    mode_defaults = {
        "labels": [
            {"index": 0, "label": "Onsite", "color": StatusColor.STUCK_RED},
            {"index": 1, "label": "Hybrid", "color": StatusColor.WORKING_ORANGE},
            {"index": 2, "label": "Remote", "color": StatusColor.DONE_GREEN},
            {"index": 3, "label": "Unclarified", "color": StatusColor.STEEL},
        ]
    }
    hours_defaults = {
        "labels": [
            {"index": 0, "label": "Full time", "color": StatusColor.BRIGHT_BLUE},
            {"index": 1, "label": "part time", "color": StatusColor.WORKING_ORANGE},
            {"index": 2, "label": "Minijob", "color": StatusColor.STUCK_RED},
            {"index": 3, "label": "Flexible", "color": StatusColor.DONE_GREEN},
            {"index": 4, "label": "Unclarified", "color": StatusColor.STEEL},
        ]
    }

    # Build typed specs
    ws = WorkspaceSpec(name=workspace_name, id=workspace_id)
    bd = BoardSpec(name=board_name, id=board_id)
    it = ItemSpec(name=name or "", id=item_id)

    columns: List[ColumnSpec] = []

    if name is not None:
        columns.append(ColumnSpec(type="text", title="Opening", value=name))
    if teid is not None:
        columns.append(ColumnSpec(type="text", title="TEID", value=teid))
    if skills is not None:
        columns.append(ColumnSpec(type="text", title="Skills", value=skills))
    if locations is not None:
        columns.append(ColumnSpec(type="text", title="Locations", value=locations))
    if langs is not None:
        columns.append(ColumnSpec(type="text", title="Lang", value=langs))
    if mode is not None:
        columns.append(ColumnSpec(type="status", title="Mode", value={"index": int(mode)}, defaults=mode_defaults))
    if hours is not None:
        columns.append(ColumnSpec(type="status", title="Hours", value={"index": int(hours)}, defaults=hours_defaults))
    if profession is not None:
        columns.append(ColumnSpec(type="tags", title="Prof. Field", value=_to_id_list(profession)))

    # Connect boards
    allowed_cb_ids = _to_id_list(connect_board_ids) or []
    if connect_board_ids is not None and client is not None:
        columns.append(
            ColumnSpec(
                type="connect_boards",
                title="Client",
                value=_to_id_list(client),
                defaults={"boardIds": allowed_cb_ids},
            )
        )
    if connect_board_ids is not None and candidates is not None:
        columns.append(
            ColumnSpec(
                type="connect_boards",
                title="Candidates",
                value=_to_id_list(candidates),
                defaults={"boardIds": allowed_cb_ids},
            )
        )

    res = upsert_item(
        monday_client,
        workspace=ws,
        board=bd,
        item=it,
        columns=columns,
        group_name=group_name,
        safe_updates=safe_updates,
    )

    col_ids_by_title: Dict[str, str] = res.get("column_ids", {})
    returned: Dict[str, Any] = {
        "workspace_id": res.get("workspace_id"),
        "board_id": res.get("board_id"),
        "item_id": res.get("item_id"),
    }

    mapping = [
        ("name", "Opening"),
        ("teid", "TEID"),
        ("mode", "Mode"),
        ("hours", "Hours"),
        ("profession", "Prof. Field"),
        ("skills", "Skills"),
        ("locations", "Locations"),
        ("langs", "Lang"),
    ]
    for param, title in mapping:
        if locals().get(param) is not None:
            cid = col_ids_by_title.get(title)
            if cid:
                returned[f"{param}_col_id"] = cid

    if connect_board_ids is not None and client is not None:
        cid = col_ids_by_title.get("Client")
        if cid:
            returned["client_col_id"] = cid
    if connect_board_ids is not None and candidates is not None:
        cid = col_ids_by_title.get("Candidates")
        if cid:
            returned["candidates_col_id"] = cid

    return returned


def main() -> int:
    client = _build_client_from_config()
    if client is None:
        print("No tests/config.json token found. Please add your MONDAY_API_TOKEN to run this example.")
        return 1

    result = upsert_job_item(
        client,
        workspace_name="Recruiting",
        board_name="Jobs Board",
        # entity ids optional; pass None for discovery/creation by name
        workspace_id=None,
        board_id=None,
        item_id=None,
        # item fields
        name="Senior Backend Engineer",
        teid="TE-2025-0001",
        mode=2,   # Remote
        hours=0,  # Full time
        profession=["101", "205"],  # tag ids as strings
        skills="Python, FastAPI, PostgreSQL",
        client=["123456789"],
        candidates=[],  # clears to empty
        locations="Berlin, Remote EU",
        langs="English, German",
        # connect boards configuration (IDs of boards allowed for the connect columns)
        connect_board_ids=["123456789", "987654321"],
        group_name="Open Roles",
        safe_updates=True,
    )

    print("Upsert completed. IDs:")
    for k, v in result.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



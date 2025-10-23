from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union
import json
import sys
from pathlib import Path

from monpy.client import MondayClient
from monpy.helpers import (
    BoardSpec,
    ColumnSpec,
    ItemSpec,
    StatusColor,
    StatusDefaults,
    StatusOption,
    WorkspaceSpec,
    upsert_item,
)
from monpy.oo import Session
from monpy.oo.enums import WebhookEventType


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


def _build_people_status_defaults() -> Mapping[str, Any]:
    """Status defaults for the People board main pipeline.

    Labels (index order):
      0 Unclarified (grey)
      1 Applied (gold-ish)
      2 Prospect (yellow)
      3 Qualified (light purple)
      4 CV Sent (purple)
      5 Shortlisted (deep purple)
      6 Interview (light blue)
      7 Offered (teal)
      8 Accepted (green)
      9 Hired (dark green)
     10 Rejected (red)
    """
    opts: List[StatusOption] = [
        StatusOption(label="Unclarified", color=StatusColor.STEEL),
        # Closest to gold in canonical palette
        StatusOption(label="Applied", color=StatusColor.SUNSET),
        StatusOption(label="Prospect", color=StatusColor.EGG_YOLK),
        StatusOption(label="Qualified", color=StatusColor.LILAC),
        StatusOption(label="CV Sent", color=StatusColor.PURPLE),
        StatusOption(label="Shortlisted", color=StatusColor.DARK_PURPLE),
        StatusOption(label="Interview", color=StatusColor.SKY),
        StatusOption(label="Offered", color=StatusColor.TEAL),
        StatusOption(label="Accepted", color=StatusColor.GRASS_GREEN),
        StatusOption(label="Hired", color=StatusColor.BRIGHT_GREEN),
        StatusOption(label="Rejected", color=StatusColor.STUCK_RED),
    ]
    return StatusDefaults(options=opts).to_dict()


def _build_candidate_category_defaults() -> Mapping[str, Any]:
    """Status defaults for Candidate Category.

    Labels (index order): Keyselling, Unclarified, Reselling, Good, Acceptable, Poor
    """
    opts: List[StatusOption] = [
        StatusOption(label="Keyselling", color=StatusColor.DONE_GREEN),
        StatusOption(label="Unclarified", color=StatusColor.STEEL),
        StatusOption(label="Reselling", color=StatusColor.PURPLE),
        StatusOption(label="Good", color=StatusColor.BRIGHT_BLUE),
        StatusOption(label="Acceptable", color=StatusColor.WORKING_ORANGE),
        StatusOption(label="Poor", color=StatusColor.STUCK_RED),
    ]
    return StatusDefaults(options=opts).to_dict()


def _to_id_list(v: Optional[Union[str, int, Sequence[Union[str, int]]]]) -> Optional[List[int]]:
    """Normalize a variety of id inputs to a list of ints.

    Rules:
      - None -> None (skip modification)
      - "" or [] -> [] (explicitly clear)
      - str/int -> [int(value)]
      - sequence -> [int(x) for x in sequence if coercible]
    """
    if v is None:
        return None
    # Single scalar
    if isinstance(v, (str, int)):
        s = str(v).strip()
        if not s:
            return []
        try:
            return [int(s)]
        except Exception:
            return []
    # Sequence
    out: List[int] = []
    for x in list(v):
        try:
            s = str(x).strip()
            if s:
                out.append(int(s))
        except Exception:
            continue
    return out


def upsert_person(
    client: MondayClient,
    *,
    workspace_name: str,
    board_name: str,
    # Optional IDs – pass None to allow creation/auto-resolution
    workspace_id: Optional[str] = None,
    board_id: Optional[str] = None,
    item_id: Optional[str] = None,
    # Optional group selection by name (created if missing when creating a new item)
    group_name: Optional[str] = None,
    # People board params
    name: Optional[str] = None,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    locations: Optional[str] = None,
    assigned: Optional[Sequence[str]] = None,
    status: Optional[int] = None,
    link: Optional[str] = None,
    teid: Optional[str] = None,
    gdpr: Optional[date | datetime] = None,
    profession: Optional[Sequence[str]] = None,
    skills: Optional[str] = None,
    candcat: Optional[int] = None,
    jobcontact: Optional[str | Sequence[str]] = None,
    orgcontact: Optional[str | Sequence[str]] = None,
    langs: Optional[str] = None,
    # Connect-boards prerequisites (required to create JobContact/OrgContact columns)
    connect_board_ids: Optional[Sequence[str | int]] = None,
    # Update behavior
    safe_updates: bool = True,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Wrapper for item upsert on a People board.

    Notes
    -----
    - If `workspace_id`, `board_id`, or `item_id` is None, they will be created/resolved as needed.
    - For all non-connect fields, columns are ensured to exist and values are set.
    - Connect fields (JobContact, OrgContact) are only created if `connect_board_ids` is provided.
      If the corresponding value param is None, the column is not modified; if it is an empty
      list, existing links are cleared; if it is a single string, it is treated as one item id.
    - Files and Last Updated columns are ensured to exist but are not modified.
    - Webhooks: if webhook_url is provided, a webhook for column changes will
      be registered on the board. Note that running this multiple times with a
      different URL will create multiple webhooks.
    - Returns a dict with `workspace_id`, `board_id`, `item_id`, and `{param}_col_id` entries.
    """

    # Build defaults for both status columns
    people_status_defs = _build_people_status_defaults()
    candcat_defs = _build_candidate_category_defaults()

    # Prepare specs
    ws = WorkspaceSpec(name=workspace_name, id=workspace_id)
    bd = BoardSpec(name=board_name, id=board_id)
    it = ItemSpec(name=name or "", id=item_id)

    columns: List[ColumnSpec] = []

    if name is not None:
        columns.append(ColumnSpec(type="text", title="Person", value=name))
    if phone is not None:
        columns.append(ColumnSpec(type="text", title="Phone", value=phone))
    if email is not None:
        columns.append(ColumnSpec(type="email", title="Email", value=email))
    if locations is not None:
        columns.append(ColumnSpec(type="text", title="Locations", value=locations))
    if assigned is not None:
        columns.append(ColumnSpec(type="people", title="Assigned", value=_to_id_list(list(assigned))))
    if status is not None:
        columns.append(ColumnSpec(type="status", title="Status", value={"index": int(status)}, defaults=people_status_defs))
    if link is not None:
        columns.append(ColumnSpec(type="link", title="Link", value=link))
    if teid is not None:
        columns.append(ColumnSpec(type="text", title="TEID", value=teid))
    if gdpr is not None:
        columns.append(ColumnSpec(type="date", title="GDPR Date", value=gdpr))
    if profession is not None:
        columns.append(ColumnSpec(type="tags", title="Prof. Field", value=_to_id_list(list(profession))))
    if skills is not None:
        columns.append(ColumnSpec(type="text", title="Skills", value=skills))
    if candcat is not None:
        columns.append(ColumnSpec(type="status", title="Candidate Category", value={"index": int(candcat)}, defaults=candcat_defs))
    if langs is not None:
        columns.append(ColumnSpec(type="text", title="Lang", value=langs))

    # Connect boards (in-spec management): only when board ids config is provided and a value is given
    allowed_cb_ids = _to_id_list(list(connect_board_ids) if connect_board_ids is not None else None) or []
    if connect_board_ids is not None and jobcontact is not None:
        columns.append(
            ColumnSpec(
                type="connect_boards",
                title="JobContact",
                value=_to_id_list(jobcontact),
                defaults={"boardIds": allowed_cb_ids, "allowMultipleItems": True},
            )
        )
    if connect_board_ids is not None and orgcontact is not None:
        columns.append(
            ColumnSpec(
                type="connect_boards",
                title="OrgContact",
                value=_to_id_list(orgcontact),
                defaults={"boardIds": allowed_cb_ids, "allowMultipleItems": True},
            )
        )

    out = upsert_item(
        client,
        workspace=ws,
        board=bd,
        item=it,
        columns=columns,
        group_name=group_name,
        safe_updates=safe_updates,
    )

    # Compose return dict with *_col_id for provided params
    col_ids: Mapping[str, str] = out.get("column_ids", {})
    result: Dict[str, Any] = {
        "workspace_id": out.get("workspace_id"),
        "board_id": out.get("board_id"),
        "item_id": out.get("item_id"),
    }

    board_id = out.get("board_id")
    if board_id and webhook_url:
        session = Session(client)
        board = session.board(board_id)
        hook_data = board.register_webhook(url=webhook_url, event=WebhookEventType.COLUMN_CHANGE)
        if hook_data and "id" in hook_data:
            result["webhook_id"] = str(hook_data["id"])

    param_to_title: List[tuple[str, str]] = [
        ("name", "Person"),
        ("phone", "Phone"),
        ("email", "Email"),
        ("locations", "Locations"),
        ("assigned", "Assigned"),
        ("status", "Status"),
        ("link", "Link"),
        ("teid", "TEID"),
        ("gdpr", "GDPR Date"),
        ("profession", "Prof. Field"),
        ("skills", "Skills"),
        ("candcat", "Candidate Category"),
        ("langs", "Lang"),
    ]

    for param, title in param_to_title:
        if locals().get(param) is not None:
            cid = col_ids.get(title)
            if cid:
                result[f"{param}_col_id"] = cid

    # Connects: only include when both config and value were provided
    if connect_board_ids is not None and jobcontact is not None:
        cid = col_ids.get("JobContact")
        if cid:
            result["jobcontact_col_id"] = cid
    if connect_board_ids is not None and orgcontact is not None:
        cid = col_ids.get("OrgContact")
        if cid:
            result["orgcontact_col_id"] = cid

    return result


def example_call() -> None:
    """Minimal example for manual runs.

    Set MONDAY_TOKEN in your environment before running, then:
        python -m examples.upsert_person_example
    """
    client = _build_client_from_config()
    if not client:
        print("No tests/config.json token found; skipping live call.")
        return

    config = _load_config()
    webhook_url_base = (config.get("live_env") or {}).get("webhook_url_base")
    webhook_url = None
    if webhook_url_base:
        import uuid

        webhook_url = f"{webhook_url_base}/person/{uuid.uuid4()}"
    else:
        print("No webhook_url_base found in config; skipping webhook registration.")

    attrs = upsert_person(
        client,
        workspace_name="Recruiting",
        board_name="People Board",
        # Optionally pin existing entities; None => create if needed
        workspace_id=None,
        board_id=None,
        item_id=None,
        group_name="Candidates",
        # People board values (feel free to adjust)
        name="Jane Doe",
        phone="+1 555 0100",
        email="jane@example.com",
        locations="London, UK",
        assigned=["12345678"],
        status=2,  # Prospect
        link="https://example.com/profile/jane",
        teid="TE-001",
        gdpr=date.today(),
        profession=["101", "205"],  # tag ids
        skills="Python, GTM, Outreach",
        candcat=0,  # Keyselling
        jobcontact=[],  # explicitly clear
        orgcontact=None,  # do not touch
        langs="EN, FR",
        connect_board_ids=None,  # set e.g. ["987654321"] to enable Job/Org contacts
        safe_updates=True,
        webhook_url=webhook_url,
    )

    # Print returned IDs for quick inspection
    for k in sorted(attrs.keys()):
        print(f"{k} = {attrs[k]}")


if __name__ == "__main__":
    example_call()



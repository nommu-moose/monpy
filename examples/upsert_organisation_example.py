from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union
import sys


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
    StatusDefaults,
    StatusOption,
    WorkspaceSpec,
    upsert_item,
)
from inventory_usage import _build_client_from_config, _load_config  # noqa: E402
from monpy.oo import Session
from monpy.oo.enums import WebhookEventType


def _organisation_status_defaults() -> Mapping[str, Any]:
    """Status defaults for the Organisations board "Type" column.

    Options:
      - Prospective::purple
      - Client::green
      - Client and Partner::baby blue
      - Partner::orange
      - Internal::dark blue
      - Unclarified::grey
      - Unsuccessful::red
    """
    options: List[StatusOption] = [
        StatusOption(label="Prospective", color=StatusColor.PURPLE),
        StatusOption(label="Client", color=StatusColor.DONE_GREEN),
        StatusOption(label="Client and Partner", color=StatusColor.SKY),
        StatusOption(label="Partner", color=StatusColor.WORKING_ORANGE),
        StatusOption(label="Internal", color=StatusColor.DARK_BLUE),
        StatusOption(label="Unclarified", color=StatusColor.AMERICAN_GRAY),
        StatusOption(label="Unsuccessful", color=StatusColor.STUCK_RED),
    ]
    return StatusDefaults(options=options).to_dict()


def _to_id_list(v: Optional[Union[str, int, Sequence[Union[str, int]]]]) -> Optional[List[int]]:
    """Normalize ids to a list of ints.

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


def upsert_organisation_item(
    client: MondayClient,
    *,
    workspace_name: str,
    board_name: str,
    # Optional identifiers – may be None (will resolve or create)
    workspace_id: Optional[str] = None,
    board_id: Optional[str] = None,
    item_id: Optional[str] = None,
    # Item values
    name: Optional[str] = None,  # maps to text column "Organisation"
    org_type: Optional[Union[int, str]] = None,  # maps to status column "Type"
    locations: Optional[str] = None,  # maps to text column "Locations"
    assigned: Optional[Sequence[Union[int, str]]] = None,  # maps to people column "Assigned"
    contacts: Optional[Sequence[Union[int, str]]] = None,  # maps to connect boards column "Contacts"
    teid: Optional[str] = None,  # maps to text column "TEID"
    # Connect boards setup (required to create/resolve the Contacts column)
    contacts_board_ids: Optional[Sequence[Union[int, str]]] = None,
    # Optional placement/config
    workspace_kind: str = "open",
    board_kind: str = "public",
    group_id: Optional[str] = None,
    group_name: Optional[str] = None,
    safe_updates: bool = True,
    webhook_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Upsert an Organisation item and return IDs including column ids per provided params.

    Behavior for special fields:
      - contacts: if None, the field is not changed (and the column is not created). If an empty
        list is provided and contacts_board_ids are given, the column is ensured and set empty.
      - assigned: if None, not changed; if provided (including empty list), it is set.
      - workspace_id/board_id/item_id can be None; missing entities will be created.
      - Webhooks: if webhook_url is provided, a webhook for column changes will
        be registered on the board. Note that running this multiple times with a
        different URL will create multiple webhooks.
    """
    # Specs for workspace and board
    ws = WorkspaceSpec(name=workspace_name, id=workspace_id, kind=workspace_kind)
    bd = BoardSpec(name=board_name, id=board_id, board_kind=board_kind)

    # Collect requested columns corresponding to provided params only
    columns: List[ColumnSpec] = []

    if name is not None:
        columns.append(ColumnSpec(type="text", title="Organisation", value=name))

    if org_type is not None:
        status_value: Union[str, Mapping[str, Any]]
        if isinstance(org_type, int):
            status_value = {"index": org_type}
        else:
            status_value = str(org_type)
        columns.append(
            ColumnSpec(
                type="status",
                title="Type",
                value=status_value,
                defaults=_organisation_status_defaults(),
            )
        )

    if locations is not None:
        columns.append(ColumnSpec(type="text", title="Locations", value=locations))

    if assigned is not None:
        columns.append(ColumnSpec(type="people", title="Assigned", value=_to_id_list(assigned)))

    # Contacts: only create/update when the board ids are provided to define the relation
    if contacts_board_ids is not None and contacts is not None:
        allowed_ids = _to_id_list(contacts_board_ids) or []
        columns.append(
            ColumnSpec(
                type="connect_boards",
                title="Contacts",
                defaults={"boardIds": allowed_ids, "allowMultipleItems": True},
                value=_to_id_list(contacts),  # empty list clears the relation
            )
        )

    if teid is not None:
        columns.append(ColumnSpec(type="text", title="TEID", value=teid))

    # Build the item spec – use the organisation name for the item name when available
    item_name = name or ""
    it = ItemSpec(name=item_name, id=item_id, group_id=group_id)

    # Execute upsert
    out = upsert_item(
        client,
        workspace=ws,
        board=bd,
        item=it,
        columns=columns,
        group_name=group_name,
        safe_updates=safe_updates,
    )

    # Compose the return object with *_col_id keys for provided params
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

    # Map input param names to their column titles
    param_to_title: List[Tuple[str, str]] = [
        ("name", "Organisation"),
        ("org_type", "Type"),
        ("locations", "Locations"),
        ("assigned", "Assigned"),
        ("contacts", "Contacts"),
        ("teid", "TEID"),
    ]

    for param, title in param_to_title:
        if param == "contacts":
            # Only include contacts_col_id if contacts was provided and column potentially updated/ensured
            if contacts_board_ids is not None and contacts is not None:
                cid = col_ids.get(title)
                if cid:
                    result[f"{param}_col_id"] = cid
            continue

        # Include when the parameter was provided (not None)
        if locals().get(param) is not None:
            cid = col_ids.get(title)
            if cid:
                result[f"{param}_col_id"] = cid

    return result


def example_call() -> int:
    """Minimal runnable example that calls the wrapper and prints IDs."""
    client = _build_client_from_config()
    if client is None:
        print("No tests/config.json token found; skipping live call.")
        return 0

    config = _load_config()
    webhook_url_base = (config.get("live_env") or {}).get("webhook_url_base")
    webhook_url = None
    if webhook_url_base:
        import uuid

        webhook_url = f"{webhook_url_base}/org/{uuid.uuid4()}"
    else:
        print("No webhook_url_base found in config; skipping webhook registration.")

    # Adjust names as desired; if the workspace/board do not exist, they will be created
    out = upsert_organisation_item(
        client,
        workspace_name="Monpy Examples",
        board_name="Organisations",
        # IDs can be provided or left None
        workspace_id=None,
        board_id=None,
        item_id=None,
        # Values
        name="ACME Corp",
        org_type="Prospective",
        locations="London, Berlin",
        assigned=[],
        # Provide the related People board id(s) to enable the Contacts relation, else leave None
        contacts_board_ids=None,
        contacts=None,
        teid="ORG-123",
        group_name="grp1",
        webhook_url=webhook_url,
    )

    print("workspace_id:", out.get("workspace_id"))
    print("board_id:", out.get("board_id"))
    print("item_id:", out.get("item_id"))
    # Print available *_col_id keys
    for k, v in out.items():
        if k.endswith("_col_id"):
            print(f"{k}: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(example_call())



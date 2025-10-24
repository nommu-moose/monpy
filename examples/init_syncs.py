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
from monpy.oo import BoardKind
from monpy.oo import Column
from monpy.oo import ColumnType


from typing import Iterable, Optional
from monpy.client import MondayClient
from monpy.exceptions import MondayAPIError, FeatureNotSupported
from monpy.oo.session import Session


def delete_all_columns_on_board(board_id: str, *, token: str, skip_ids: Optional[Iterable[str]] = None) -> list[str]:
    """
    Delete all deletable columns on a board, skipping the primary name column by default.

    - board_id: monday.com board ID
    - token: monday.com user API token
    - skip_ids: optional iterable of column IDs to never delete (default includes 'name')

    Returns list of deleted column IDs.
    """
    client = MondayClient(token=token)
    session = Session(client)

    # Resolve and cache the board in the OO session (so we can invalidate its column cache after)
    board = session.board(board_id)

    # Always skip the primary item name column
    skip: set[str] = {"name"}
    if skip_ids:
        skip |= set(skip_ids)

    # Minimal fields; we only need IDs
    cols = client.get_columns(board_id, fields=("id", "type"))
    deleted: list[str] = []

    for c in cols:
        cid = str(c.get("id") or "")
        if not cid or cid in skip:
            continue
        try:
            session.client.mutation(
                "mutation ($b:ID!, $c:String!){ delete_column(board_id:$b, column_id:$c){ id } }",
                {"b": board_id, "c": cid},
            )
            deleted.append(cid)
        except FeatureNotSupported:
            # Column deletion not available on this account/API; skip gracefully
            continue
        except MondayAPIError:
            # Best-effort: continue deleting remaining columns
            continue

    # Invalidate OO column cache so subsequent board.columns reflects deletions
    try:
        board._columns_cache = None  # noqa: SLF001 (internal cache invalidation mirrors other OO helpers)
    except Exception:
        pass

    return deleted


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


def setup_board():
    """
    board_id
    fields: [{"field_key": str, "field_title": str, "field_type": pkg oo enum, <other info if needed per-field>:}, ...]

    takes the list of fields and create them on the board with correct configuration

    return a list of dicts for each key in the dict of fields passed to it
    the dicts should have the same field_key: key with field_id: generated on monday.com too, for future reference
    """
    pass


def create_item():
    pass


def delete_item():
    pass


def update_item():
    pass


def batch_upsert_items():
    pass


def delete_item_by_id(session: Session, item_id: str | int) -> None:
    """
    Permanently delete an item by ID using the OO layer.

    Raises:
        monpy.MondayAPIError: if the API call fails.
    """
    session.item(str(item_id)).delete()


if __name__ == "__main__":
    raise SystemExit(main())

"""
Please output a wrapper for the upsert item helper function
it should take a set of params representing an item
params and monday output should follow this structure:

workspace_id (str), board_id(str), and item_id(str) should all be optional and possible to be passed None

if none is passed, please ensure that the field is still passed/created and just empty if it doesn't exist

### People Board

- Person ("name" param, str, mapping to text field on monday)
- Phone ("phone" param, str, mapping to text field on monday)
- Email ("email" param, str, mapping to email field on monday)
- Locations ("locations" param, str, mapping to text field on monday)
- Assigned ("assigned" param, list of strings representing IDs of accounts on Monday, mapping to people column on monday)
- Status ("status" param, integer index, mapping to status field with options: Unclarified::grey, Applied::gold, Prospect::yellow, Qualified::light purple, CV Sent::purple, Shortlisted::deep purple, Interview::light blue, Offered::teal, Accepted::green, Hired::dark green, Rejected::red)
- Link ("link" param, str, mapping to a clickable link field in monday)
- TEID ("teid" param, str, mapping to text field in monday)
- GDPR Date ("gdpr" param, date or datetime in python, mapping to date field in monday)
- Prof. Field ("profession" param, list of strings, mapping to tags field in monday)
- Skills ("skills" param, str, mapping to text field in monday)
- Candidate Category ("candcat" param, integer index mapping to status field with options: Keyselling::green, Unclarified::grey, Reselling::purple, Good::blue, Acceptable::orange, Poor::red)
- JobContact ("jobcontact" param, str representing job item ID, mapping to connect field, if empty list then set it as empty, but if None don't set the field)
- OrgContact ("orgcontact" param, str representing org item ID, mapping to connect field, if empty list then set it as empty, but if None don't set the field)
- Lang ("langs" param, str, mapping to text field on monday)
- Files (no data passed to upsert, just must ensure this column exists)
- Last Updated (no data passed to upsert, just must ensure this column exists)

please make it return an object with the same attr names as params that were passed + the suffix _col_id, the attrs then being the column IDs... also give it workspace_id, item_id, and board_id

it should also be given a list of the board IDs required for connect boards, otherwise if None, it will just ignore the creation of that column, plus make no changes to that column at all

add it to an upsert_person_example.py inside the examples folder, so I can use it myself and ensure it works, and include an additional calling function passing the params to it and getting the attrs back to print them





Please output a wrapper for the upsert item helper function
it should take a set of params representing an item
params and monday output should follow this structure:

workspace_id (str), board_id(str), and item_id(str) should all be optional and possible to be passed None

if none is passed, please ensure that the field is still passed/created and just empty if it doesn't exist

### Organisations Board

- Organisation ("name" param, str, mapping to text field on monday)
- Type (status field with options: Prospective::purple, Client::green, Client and Partner::baby blue, Partner::orange, Internal::dark blue, Unclarified::grey, Unsuccessful::red)
- Locations ("locations" param, str, mapping to text field on monday)
- Assigned ("assigned" param, list of strings representing IDs of accounts on Monday, mapping to people column on monday)
- Contacts ("contacts" param, list of strings representing person item IDs, mapping to connect field, if empty list then set it as empty, but if None don't set the field)
- TEID ("teid" param, str, mapping to text field in monday)

please make it return an object with the same attr names as params that were passed + the suffix _col_id, the attrs then being the column IDs... also give it workspace_id, item_id, and board_id

it should also be given a list of the board IDs required for connect boards, otherwise if None, it will just ignore the creation of that column, plus make no changes to that column at all

add it to an upsert_organisation_example.py inside the examples folder, so I can use it myself and ensure it works, and include an additional calling function passing the params to it and getting the attrs back to print them




Please output a wrapper for the upsert item helper function
it should take a set of params representing an item
params and monday output should follow this structure:

workspace_id (str), board_id(str), and item_id(str) should all be optional and possible to be passed None

if none is passed, please ensure that the field is still passed/created and just empty if it doesn't exist

### Jobs Board

- Opening ("name" param, str, mapping to text field on monday)
- TEID ("teid" param, str, mapping to text field in monday)
- Mode ("mode" param, integer index, mapping to status field with options: Onsite::red, Hybrid::orange, Remote::green, Unclarified::grey)
- Hours ("hours" param, integer index, mapping to status field with options: Full time::blue, part time::orange, Minijob::red, Flexible::green, Unclarified::grey)
- Prof. Field ("profession" param, list of strings, mapping to tags field in monday)
- Skills ("skills" param, str, mapping to text field in monday)
- Client ("client" param, list of strings representing org item IDs, mapping to connect field, if empty list then set it as empty, but if None don't set the field)
- Candidates ("candidates" param, list of strings representing person item IDs, mapping to connect field, if empty list then set it as empty, but if None don't set the field)
- Locations ("locations" param, str, mapping to text field on monday)
- Lang ("langs" param, str, mapping to text field on monday)

please make it return an object with the same attr names as params that were passed + the suffix _col_id, the attrs then being the column IDs... also give it workspace_id, item_id, and board_id

it should also be given a list of the board IDs required for connect boards, otherwise if None, it will just ignore the creation of that column, plus make no changes to that column at all

add it to an upsert_job_example.py inside the examples folder, so I can use it myself and ensure it works, and include an additional calling function passing the params to it and getting the attrs back to print them


### Pipelines Subitems on People Board
- Pipeline ("name" param, str, mapping to text field on monday)
- Status ("status" param, integer index, mapping to status field with options: Unclarified::grey, Applied::gold, Prospect::yellow, Qualified::light purple, CV Sent::purple, Shortlisted::deep purple, Interview::light blue, Offered::teal, Accepted::green, Hired::dark green, Rejected::red)
- Skills ("skills" param, str, mapping to text field in monday)
- Notes ("notes" param, str, mapping to text field on monday)
- Files (no data passed to upsert, just must ensure this column exists)
"""

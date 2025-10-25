from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Union
import json
from pathlib import Path

from monpy.client import MondayClient
from monpy.helpers.users import fetch_all_account_users


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


def _normalize_id_list(values: Optional[Sequence[Union[str, int]]]) -> List[int]:
    """Normalize a list of possible id representations to a list of ints.

    Rules:
      - None -> []
      - skips blanks and non-coercible entries
    """
    if not values:
        return []
    out: List[int] = []
    for v in list(values):
        try:
            s = str(v).strip()
            if not s:
                continue
            out.append(int(s))
        except Exception:
            continue
    return out


def ensure_board_subscribers(
    client: MondayClient,
    *,
    board_id: str,
    desired_user_ids: Sequence[Union[str, int]],
    kind: str = "subscriber",
    preserve_owners: bool = True,
    dry_run: bool = False,
) -> Mapping[str, Any]:
    """Ensure that a board's subscribers match a desired set of user IDs.

    Behavior
    --------
    - Fetches all monday users in the environment and prunes requested IDs not present.
    - Compares the board's current subscribers to the pruned desired list.
    - Subscribes missing users and unsubscribes extra users to match the desired set.
    - When preserve_owners=True, owners are never unsubscribed even if not in the desired list.

    Parameters
    ----------
    client
        MondayClient instance with a valid token.
    board_id
        Target board to manage memberships for.
    desired_user_ids
        Iterable of monday account IDs (str or int). Unknown IDs are ignored via pruning.
    kind
        Role to add for new subscribers: one of monday BoardSubscriberKind values
        (e.g. "subscriber", "viewer", "owner"). Default: "subscriber".
    preserve_owners
        If True, existing owners are never removed from the board. Default: True.
    dry_run
        If True, compute and return the changes without performing any mutations.

    Returns
    -------
    Mapping[str, Any]
        Summary of the operation including pruned desired IDs, add/remove lists, and flags.
    """

    # Normalize and prune desired ids against environment users
    normalized_desired: List[int] = _normalize_id_list(desired_user_ids)

    account_users = fetch_all_account_users(client)
    valid_user_id_set: Set[int] = {int(u.account_id) for u in account_users if u and u.account_id}

    desired_pruned: List[int] = [uid for uid in normalized_desired if uid in valid_user_id_set]
    desired_set: Set[int] = set(desired_pruned)
    invalid_requested: List[int] = [uid for uid in normalized_desired if uid not in valid_user_id_set]

    # Gather current subscribers/owners
    members = client.list_board_members_by_role(board_id)
    current_subscribers_set: Set[int] = {int(u.get("id")) for u in (members.get("subscribers") or []) if u and u.get("id") is not None}
    owners_set: Set[int] = {int(u.get("id")) for u in (members.get("owners") or []) if u and u.get("id") is not None}

    # Compute delta
    to_add: List[int] = sorted(desired_set - current_subscribers_set)
    extras = current_subscribers_set - desired_set
    if preserve_owners and extras:
        extras = {uid for uid in extras if uid not in owners_set}
    to_remove: List[int] = sorted(extras)

    summary: Dict[str, Any] = {
        "board_id": board_id,
        "kind": kind,
        "preserve_owners": bool(preserve_owners),
        "dry_run": bool(dry_run),
        "requested_count": len(normalized_desired),
        "invalid_requested": invalid_requested,
        "desired_ids_pruned": desired_pruned,
        "before": {
            "subscribers_count": len(current_subscribers_set),
            "owners_count": len(owners_set),
        },
        "to_add": to_add,
        "to_remove": to_remove,
    }

    if dry_run:
        return summary

    # Apply mutations
    if to_add:
        client.add_board_subscribers(board_id, to_add, kind=kind)
    if to_remove:
        client.remove_board_subscribers(board_id, to_remove)

    # Optionally re-fetch to reflect current state after changes
    final_members = client.list_board_members_by_role(board_id)
    final_subscribers_set: Set[int] = {int(u.get("id")) for u in (final_members.get("subscribers") or []) if u and u.get("id") is not None}
    final_owners_set: Set[int] = {int(u.get("id")) for u in (final_members.get("owners") or []) if u and u.get("id") is not None}

    summary["after"] = {
        "subscribers_count": len(final_subscribers_set),
        "owners_count": len(final_owners_set),
    }

    return summary


def example_call() -> None:
    """Minimal manual run helper.

    Set MONDAY_API_TOKEN/token inside tests/config.json, then run:
        python -m examples.ensure_board_subscribers <BOARD_ID> <ID1> <ID2> ...
    """
    import sys

    client = _build_client_from_config()
    if not client:
        print("No tests/config.json token found; skipping live call.")
        return

    if len(sys.argv) < 3:
        print("Usage: python -m examples.ensure_board_subscribers <BOARD_ID> <USER_ID> [<USER_ID> ...]")
        return

    board_id = sys.argv[1]
    desired_ids = sys.argv[2:]

    result = ensure_board_subscribers(
        client,
        board_id=board_id,
        desired_user_ids=desired_ids,
        kind="subscriber",
        preserve_owners=True,
        dry_run=False,
    )

    # Pretty-print summary
    for k in sorted(result.keys()):
        print(f"{k} = {result[k]}")


if __name__ == "__main__":
    example_call()



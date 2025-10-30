from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union, List, Set

from ..client import MondayClient
from ..helpers import WorkspaceSpec, BoardSpec, fetch_all_account_users
# Reuse the existing resolver logic from helpers to avoid duplication
from ..helpers.upsert_item import _ensure_workspace, _ensure_board


@dataclass
class TypicalSetupResult:
    """IDs for the ensured workspace and boards.

    This is a lightweight result container for consumers that need deterministic
    identifiers to proceed with later operations (e.g., upserts).
    """

    workspace_id: str
    person_board_id: str
    job_board_id: str
    organisation_board_id: str


def ensure_workspace_and_boards(
    api_token: str,
    ws_name: str,
    person_board_name: str,
    job_board_name: str,
    organisation_board_name: str,
    *,
    ws_id: Optional[str] = None,
    person_board_id: Optional[str] = None,
    job_board_id: Optional[str] = None,
    organisation_board_id: Optional[str] = None,
    workspace_kind: str = "open",
    board_kind: str = "public",
    subscribers: Optional[Sequence[Union[str, int]]] = None,
) -> TypicalSetupResult:
    """Ensure a workspace and three boards (person, job, organisation).

    Parameters
    ----------
    api_token
        monday.com API token for the user.
    ws_name, person_board_name, job_board_name, organisation_board_name
        Human-readable names used to resolve or create the workspace and boards.
    ws_id, person_board_id, job_board_id, organisation_board_id
        Optional explicit IDs. When provided, they take precedence over names
        and avoid collisions due to renames. If an ID is invalid/missing, the
        function falls back to name-based resolution and creation.
    workspace_kind
        Kind for new workspaces ("open", "closed", "private").
    board_kind
        Kind for new boards ("public", "private", "share").

    subscribers
        Optional list of monday account user IDs to subscribe to each board.
        IDs are normalized to integers, pruned against account users, current
        subscribers are inspected first, and only missing users are added. No
        removals are performed.

    Returns
    -------
    TypicalSetupResult
        Dataclass containing the resolved workspace and board IDs.
    """

    client = MondayClient(token=api_token)

    # 1) Ensure workspace exists (ID overrides name; create if missing)
    ws_spec = WorkspaceSpec(name=ws_name, id=ws_id, kind=workspace_kind)
    workspace_id_resolved = _ensure_workspace(client, ws_spec)

    # 2) Ensure each board exists within the workspace (ID overrides name)
    person_spec = BoardSpec(name=person_board_name, id=person_board_id, board_kind=board_kind)
    job_spec = BoardSpec(name=job_board_name, id=job_board_id, board_kind=board_kind)
    organisation_spec = BoardSpec(name=organisation_board_name, id=organisation_board_id, board_kind=board_kind)

    person_id_resolved = _ensure_board(client, person_spec, workspace_id=workspace_id_resolved)
    job_id_resolved = _ensure_board(client, job_spec, workspace_id=workspace_id_resolved)
    organisation_id_resolved = _ensure_board(client, organisation_spec, workspace_id=workspace_id_resolved)

    # 3) Optionally ensure subscribers on each board (add-only)
    if subscribers:
        # Normalize and prune IDs
        normalized: List[int] = []
        for v in list(subscribers):
            try:
                s = str(v).strip()
                if not s:
                    continue
                normalized.append(int(s))
            except Exception:
                continue
        if normalized:
            valid_user_ids: Set[int] = {int(u.account_id) for u in fetch_all_account_users(client) if u and u.account_id}
            desired: List[int] = [uid for uid in normalized if uid in valid_user_ids]

            def _add_missing(board_id: str, wanted_ids: List[int]) -> None:
                if not wanted_ids:
                    return
                members = client.list_board_members_by_role(board_id)
                current_subs: Set[int] = {int(u.get("id")) for u in (members.get("subscribers") or []) if u and u.get("id") is not None}
                to_add = sorted(set(wanted_ids) - current_subs)
                if to_add:
                    client.add_board_subscribers(board_id, to_add, kind="subscriber")

            _add_missing(person_id_resolved, desired)
            _add_missing(job_id_resolved, desired)
            _add_missing(organisation_id_resolved, desired)

    return TypicalSetupResult(
        workspace_id=workspace_id_resolved,
        person_board_id=person_id_resolved,
        job_board_id=job_id_resolved,
        organisation_board_id=organisation_id_resolved,
    )


__all__ = [
    "TypicalSetupResult",
    "ensure_workspace_and_boards",
]



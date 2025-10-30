from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..client import MondayClient
from ..exceptions import GraphQLError, HTTPError


@dataclass
class AccountUser:
    """Represents a monday.com account user with key attributes.
    
    Attributes
    ----------
    account_id : str
        Unique user identifier
    email : str
        User email address
    first_name : str
        User's first name (extracted from full name)
    last_name : str
        User's last name (extracted from full name)
    phone_number : str
        User's phone number
    teams : List[str]
        List of team names the user belongs to
    status : str
        User status: "active", "inactive", or "pending"
    department : Optional[str]
        User's department (not exposed via GraphQL; use SCIM API for this)
    user_role : str
        User's role: "admin", "guest", "view_only", or "member"
    """
    account_id: str
    email: str
    first_name: str
    last_name: str
    phone_number: str
    teams: List[str]
    status: str
    department: Optional[str]
    user_role: str


def _split_name(full_name: str) -> tuple[str, str]:
    """Split a full name into first and last name."""
    parts = (full_name or "").strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def _infer_role(user: Dict[str, Any]) -> str:
    """Infer user role from available flags."""
    if user.get("is_admin"):
        return "admin"
    if user.get("is_guest"):
        return "guest"
    if user.get("is_view_only"):
        return "view_only"
    return "member"


def _infer_status(user: Dict[str, Any]) -> str:
    """Infer user status from available fields."""
    if user.get("is_pending"):
        return "pending"
    if "enabled" in user:
        return "active" if user.get("enabled") else "inactive"
    return ""


def _map_user(raw_user: Dict[str, Any]) -> AccountUser:
    """Map raw GraphQL user data to AccountUser object."""
    first, last = _split_name(str(raw_user.get("name") or ""))
    phone = str(raw_user.get("phone") or raw_user.get("mobile_phone") or "")
    team_names = [
        str(t.get("name") or "")
        for t in (raw_user.get("teams") or [])
        if isinstance(t, dict)
    ]
    return AccountUser(
        account_id=str(raw_user.get("id") or ""),
        email=str(raw_user.get("email") or ""),
        first_name=first,
        last_name=last,
        phone_number=phone,
        teams=[t for t in team_names if t],
        status=_infer_status(raw_user),
        department=None,  # Not exposed via GraphQL; use SCIM if needed
        user_role=_infer_role(raw_user),
    )


def fetch_all_account_users(client: MondayClient) -> List[AccountUser]:
    """Fetch all users from the account and return as AccountUser objects.
    
    Attempts to fetch users with extended fields (teams, role flags, etc.),
    gracefully falling back to basic fields if the account doesn't support them.
    
    Parameters
    ----------
    client : MondayClient
        Authenticated monday.com API client
    
    Returns
    -------
    List[AccountUser]
        List of all users on the account
    
    Raises
    ------
    GraphQLError or HTTPError
        If all fallback attempts fail
    """
    candidate_field_sets: List[List[str]] = [
        [
            "id",
            "name",
            "email",
            "enabled",
            "is_pending",
            "is_admin",
            "is_guest",
            "is_view_only",
            "phone",
            "mobile_phone",
            "teams { id name }",
        ],
        [
            "id",
            "name",
            "email",
            "enabled",
            "is_pending",
            "is_admin",
            "is_guest",
            "is_view_only",
            "phone",
        ],
        [
            "id",
            "name",
            "email",
        ],
    ]

    last_err: Optional[Exception] = None
    for fields in candidate_field_sets:
        try:
            raw = client.get_all_users(fields=fields)
            return [_map_user(u) for u in raw]
        except (GraphQLError, HTTPError) as e:
            last_err = e
            continue

    if last_err:
        raise last_err
    return []


def fetch_all_account_users_from_token(token: str) -> List[AccountUser]:
    """Convenience wrapper that builds a client from a token and fetches users.

    Parameters
    ----------
    token : str
        monday.com API token with the necessary permissions.

    Returns
    -------
    List[AccountUser]
        List of all users on the account, identical to ``fetch_all_account_users``.

    Raises
    ------
    GraphQLError or HTTPError
        Propagated from the underlying client request if fetching fails.
    """

    client = MondayClient(token=token)
    return fetch_all_account_users(client)
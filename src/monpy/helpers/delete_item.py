from __future__ import annotations

from ..client import MondayClient


def delete_item_from_token(token: str, item_id: str) -> None:
    """
    Permanently delete a monday.com item using only an API token.

    Parameters
    ----------
    token
        monday.com user API token.
    item_id
        Target item ID to delete.

    Returns
    -------
    None
    """
    client = MondayClient(token)
    client.delete_item(item_id)


__all__ = [
    "delete_item_from_token",
]




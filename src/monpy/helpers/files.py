from __future__ import annotations

from pathlib import Path
import mimetypes
from typing import Dict

from ..client import MondayClient
from ..oo import Session
from ..oo.file_asset import upload_to_file_column


def upload_file_to_column_from_token(
    item_id: str,
    column_id: str,
    token: str,
    file_path: str | Path,
) -> Dict[str, str]:
    """
    Upload a local file to a monday.com File column using only primitives.

    Parameters
    ----------
    item_id
        Target item ID.
    column_id
        ID of the File column on the item.
    token
        monday.com user API token.
    file_path
        Path to the local file to upload.

    Returns
    -------
    dict
        Metadata for the created asset, typically ``{"id", "url", "public_url"}``.
    """

    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"No such file: {p}")

    client = MondayClient(token)
    session = Session(client)

    mime_type = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
    with p.open("rb") as f:
        return upload_to_file_column(
            session,
            item_id=item_id,
            column_id=column_id,
            file_obj=f,
            filename=p.name,
            mime_type=mime_type,
        )


__all__ = [
    "upload_file_to_column_from_token",
]



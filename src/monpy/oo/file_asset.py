from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from .base import BaseModel


@dataclass
class FileAsset(BaseModel):
    # Holds only metadata if needed
    pass


def upload_to_file_column(session, *, item_id: str, column_id: str, file_obj, filename: str | None = None, mime_type: str = "application/octet-stream") -> dict:
    return session.client.upload_file_to_column(item_id, column_id=column_id, file_obj=file_obj, filename=filename, mime_type=mime_type)


def list_files_from_column(session, *, item_id: str, column_id: str) -> list[dict]:
    return session.client.list_files_from_column(item_id, column_id)


def download_files_from_column(session, *, item_id: str, column_id: str) -> list[bytes]:
    return session.client.download_files_from_column(item_id, column_id)



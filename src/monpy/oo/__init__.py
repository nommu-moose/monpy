"""
Object-oriented, linter-friendly layer over the low-level Monday client.

Public entry points:
- Session: unit-of-work, context-managed transactions
- Workspace, Board, Item, Column: typed entity wrappers
"""

from .session import Session
from .base import BaseModel
from .workspace import Workspace
from .board import Board
from .item import Item
from .subitem import SubItem
from .column import Column, ColumnCollection
from .doc import Doc
from .file_asset import FileAsset
from .binding import bind_session
from .enums import (
    BoardKind,
    BoardState,
    ColumnType,
    ItemState,
    WebhookEventType,
    WorkspaceKind,
)
from .webhooks import (
    parse_webhook,
    verify_signature,
)

__all__ = [
    "Session",
    "BaseModel",
    "Workspace",
    "Board",
    "Item",
    "SubItem",
    "Column",
    "ColumnCollection",
    "Doc",
    "FileAsset",
    "bind_session",
    # enums
    "BoardKind",
    "BoardState",
    "ColumnType",
    "ItemState",
    "WebhookEventType",
    "WorkspaceKind",
    # webhooks
    "parse_webhook",
    "verify_signature",
]



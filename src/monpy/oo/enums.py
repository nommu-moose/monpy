from __future__ import annotations

from enum import Enum


class WorkspaceKind(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    PRIVATE = "private"


class BoardKind(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    SHARE = "share"


class BoardState(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ItemState(str, Enum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    DELETED = "deleted"


class ColumnType(str, Enum):
    TEXT = "text"
    STATUS = "status"
    DATE = "date"
    PERSON = "person"
    PEOPLE = "people"
    NUMBER = "numbers"
    BOARD_RELATION = "board_relation"
    CONNECT_BOARDS = "connect_boards"
    MIRROR = "mirror"
    FILES = "file"
    LINK = "link"
    DOC = "doc"


# Webhook events exposed by monday.com's GraphQL API (WebhookEventType)
# The list is not exhaustive; names map to official enum values where known.
class WebhookEventType(str, Enum):
    UNKNOWN = "unknown"

    # Item-level changes
    ITEM_CREATED = "create_item"
    ITEM_DELETED = "delete_item"
    ITEM_ARCHIVED = "archive_item"
    ITEM_RESTORED = "unarchive_item"
    ITEM_NAME_CHANGE = "change_name"
    ITEM_MOVED = "move_item_to_group"

    # Column changes (any column or specific via config, e.g., Status)
    COLUMN_CHANGE = "change_column_value"
    ANY_COLUMN_CHANGES = "change_column_value"
    STATUS_CHANGE = "change_column_value"  # filter with config {"columnId": "status"}
    COLUMN_CREATED = "create_column"

    # Updates (item communication)
    NEW_UPDATE = "create_update"
    UPDATE_CHANGE = "change_update"
    UPDATE_DELETE = "delete_update"

    # Subitem events (parity with items where supported)
    SUBITEM_CREATED = "create_subitem"
    SUBITEM_DELETED = "delete_subitem"
    SUBITEM_ARCHIVED = "archive_subitem"
    SUBITEM_RESTORED = "unarchive_subitem"
    SUBITEM_MOVED = "move_subitem_to_group"
    SUBITEM_COLUMN_CHANGE = "change_subitem_column_value"


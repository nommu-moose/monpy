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
    LOCATION = "location"


# Webhook events exposed by monday.com's GraphQL API (WebhookEventType)
# The list is not exhaustive; names map to official enum values where known.
class WebhookEventType(Enum):
    UNKNOWN = "unknown"

    # Item-level changes
    ITEM_CREATED = "create_item"
    ITEM_DELETED = "item_deleted"
    ITEM_ARCHIVED = "item_archived"
    ITEM_RESTORED = "item_restored"
    ITEM_NAME_CHANGE = "item_name_changed"
    ITEM_MOVED = "item_moved_to_group"

    # Column changes (any column or specific via config, e.g., Status)
    COLUMN_CHANGE = "change_column_value"
    ANY_COLUMN_CHANGES = "change_column_value"
    STATUS_CHANGE = "change_column_value"  # filter with config {"columnId": "status"}
    COLUMN_CREATED = "create_column"

    # Updates (item communication)
    NEW_UPDATE = "update_created"
    UPDATE_CHANGE = "edit_update"  # modern name for change_update
    UPDATE_DELETE = "update_deleted"

    # Subitem events (parity with items where supported)
    SUBITEM_CREATED = "subitem_created"
    SUBITEM_DELETED = "subitem_deleted"
    SUBITEM_ARCHIVED = "subitem_archived"
    SUBITEM_RESTORED = "subitem_restored"
    SUBITEM_MOVED = "subitem_moved_to_group"
    SUBITEM_COLUMN_CHANGE = "subitem_column_value_changed"


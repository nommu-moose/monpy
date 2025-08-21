from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from ..enums import WebhookEventType


@dataclass
class WebhookEvent:
    """
    Base webhook event object for monday.com callbacks.

    Attributes are normalized to snake_case and IDs are represented as strings
    where possible for consistency with the OO layer.
    """

    type: WebhookEventType
    board_id: Optional[str] = None
    group_id: Optional[str] = None
    item_id: Optional[str] = None
    item_name: Optional[str] = None
    user_id: Optional[str] = None
    trigger_time: Optional[str] = None
    subscription_id: Optional[str] = None
    trigger_uuid: Optional[str] = None
    app: Optional[str] = None

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)


@dataclass
class ItemCreatedEvent(WebhookEvent):
    pass


@dataclass
class ItemDeletedEvent(WebhookEvent):
    pass


@dataclass
class ItemArchivedEvent(WebhookEvent):
    pass


@dataclass
class ItemRestoredEvent(WebhookEvent):
    pass


@dataclass
class ItemMovedEvent(WebhookEvent):
    target_group_id: Optional[str] = None


@dataclass
class ColumnChangeEvent(WebhookEvent):
    column_id: Optional[str] = None
    column_type: Optional[str] = None
    column_title: Optional[str] = None
    value: Any = None
    previous_value: Any = None


@dataclass
class UpdateCreatedEvent(WebhookEvent):
    update_id: Optional[str] = None


@dataclass
class UpdateChangedEvent(WebhookEvent):
    update_id: Optional[str] = None


@dataclass
class UpdateDeletedEvent(WebhookEvent):
    update_id: Optional[str] = None


# Mapping from enum to concrete OO event type
EVENT_CLASS_BY_TYPE: dict[WebhookEventType, type[WebhookEvent]] = {
    WebhookEventType.ITEM_CREATED: ItemCreatedEvent,
    WebhookEventType.ITEM_DELETED: ItemDeletedEvent,
    WebhookEventType.ITEM_ARCHIVED: ItemArchivedEvent,
    WebhookEventType.ITEM_RESTORED: ItemRestoredEvent,
    WebhookEventType.ITEM_MOVED: ItemMovedEvent,
    WebhookEventType.COLUMN_CHANGE: ColumnChangeEvent,
    WebhookEventType.NEW_UPDATE: UpdateCreatedEvent,
    WebhookEventType.UPDATE_CHANGE: UpdateChangedEvent,
    WebhookEventType.UPDATE_DELETE: UpdateDeletedEvent,
}



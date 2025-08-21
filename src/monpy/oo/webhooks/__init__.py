from __future__ import annotations

"""
Typed, OO-style webhook parsing utilities for monday.com callbacks.

Public entry points:
- parse_webhook: parse raw JSON (str/bytes/dict) into a typed WebhookEvent
- WebhookEvent and concrete subclasses for common event types
- verify_signature: optional HMAC helper for validating requests
"""

from .events import (
    WebhookEvent,
    ItemCreatedEvent,
    ItemDeletedEvent,
    ItemArchivedEvent,
    ItemRestoredEvent,
    ItemMovedEvent,
    ColumnChangeEvent,
    UpdateCreatedEvent,
    UpdateChangedEvent,
    UpdateDeletedEvent,
)
from .parser import parse_webhook
from .signature import verify_signature

__all__ = [
    "WebhookEvent",
    "ItemCreatedEvent",
    "ItemDeletedEvent",
    "ItemArchivedEvent",
    "ItemRestoredEvent",
    "ItemMovedEvent",
    "ColumnChangeEvent",
    "UpdateCreatedEvent",
    "UpdateChangedEvent",
    "UpdateDeletedEvent",
    "parse_webhook",
    "verify_signature",
]



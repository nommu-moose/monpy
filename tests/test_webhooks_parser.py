from __future__ import annotations

import json
import hmac
import hashlib

from monpy.oo import parse_webhook
from monpy.oo.webhooks.events import (
    WebhookEvent,
    ItemCreatedEvent,
    ItemDeletedEvent,
    ItemArchivedEvent,
    ItemRestoredEvent,
    ItemMovedEvent,
    ColumnChangeEvent,
    ColumnCreatedEvent,
    UpdateCreatedEvent,
    UpdateChangedEvent,
    UpdateDeletedEvent,
    ItemNameChangedEvent,
    SubitemCreatedEvent,
    SubitemColumnChangeEvent,
)
from monpy.oo.webhooks.signature import verify_signature
from monpy.oo.enums import WebhookEventType


def test_parse_create_item_event():
    body = {
        "event": {
            "userId": 12345,
            "boardId": 111,
            "pulseId": 222,
            "pulseName": "New item",
            "groupId": "topics",
            "groupName": "Topics",
            "type": "create_item",
            "triggerTime": "2025-01-01T00:00:00.000Z",
            "subscriptionId": 999,
            "triggerUuid": "abc-def",
        }
    }

    ev = parse_webhook(body)
    assert isinstance(ev, ItemCreatedEvent)
    assert ev.type == WebhookEventType.ITEM_CREATED
    assert ev.board_id == "111"
    assert ev.item_id == "222"
    assert ev.item_name == "New item"
    assert ev.group_id == "topics"
    assert ev.user_id == "12345"


def test_parse_column_change_event():
    body = {
        "event": {
            "userId": 123,
            "boardId": 42,
            "pulseId": 7,
            "type": "change_column_value",
            "columnId": "status",
            "columnType": "status",
            "columnTitle": "Status",
            "value": {"label": "Done"},
            "previousValue": {"label": "Working on it"},
        }
    }

    ev = parse_webhook(json.dumps(body))
    assert isinstance(ev, ColumnChangeEvent)
    assert ev.type == WebhookEventType.COLUMN_CHANGE
    assert ev.column_id == "status"
    assert ev.value == {"label": "Done"}
    assert ev.previous_value == {"label": "Working on it"}


def test_parse_item_deleted_event():
    body = {
        "event": {
            "type": "delete_item",
            "boardId": 1,
            "pulseId": 2,
            "userId": 3,
        }
    }
    ev = parse_webhook(body)
    assert isinstance(ev, ItemDeletedEvent)
    assert ev.type == WebhookEventType.ITEM_DELETED
    assert ev.board_id == "1" and ev.item_id == "2" and ev.user_id == "3"


def test_parse_item_archived_and_restored_events():
    archived = {"event": {"type": "archive_item", "boardId": 10, "pulseId": 20}}
    restored = {"event": {"type": "unarchive_item", "boardId": 11, "pulseId": 21}}

    ev_a = parse_webhook(archived)
    ev_r = parse_webhook(restored)

    assert isinstance(ev_a, ItemArchivedEvent)
    assert ev_a.type == WebhookEventType.ITEM_ARCHIVED and ev_a.board_id == "10" and ev_a.item_id == "20"
    assert isinstance(ev_r, ItemRestoredEvent)
    assert ev_r.type == WebhookEventType.ITEM_RESTORED and ev_r.board_id == "11" and ev_r.item_id == "21"


def test_parse_item_moved_event():
    body = {
        "event": {
            "type": "move_item_to_group",
            "boardId": 5,
            "pulseId": 6,
            "toGroupId": "new_group",
        }
    }
    ev = parse_webhook(body)
    assert isinstance(ev, ItemMovedEvent)
    assert ev.type == WebhookEventType.ITEM_MOVED
    assert ev.board_id == "5" and ev.item_id == "6" and ev.target_group_id == "new_group"


def test_parse_update_events_created_changed_deleted():
    created = {"event": {"type": "create_update", "boardId": 1, "pulseId": 2, "updateId": 100}}
    changed = {"event": {"type": "change_update", "boardId": 1, "pulseId": 2, "updateId": 101}}
    deleted = {"event": {"type": "delete_update", "boardId": 1, "pulseId": 2, "updateId": 102}}

    ev_c = parse_webhook(created)
    ev_u = parse_webhook(changed)
    ev_d = parse_webhook(deleted)

    assert isinstance(ev_c, UpdateCreatedEvent) and ev_c.type == WebhookEventType.NEW_UPDATE and ev_c.update_id == "100"
    assert isinstance(ev_u, UpdateChangedEvent) and ev_u.type == WebhookEventType.UPDATE_CHANGE and ev_u.update_id == "101"
    assert isinstance(ev_d, UpdateDeletedEvent) and ev_d.type == WebhookEventType.UPDATE_DELETE and ev_d.update_id == "102"


def test_alias_and_fallbacks_for_known_types():
    # Known alias: create_pulse → create_item
    body = {"event": {"type": "create_pulse", "boardId": 1, "pulseId": 2}}
    ev = parse_webhook(body)
    assert isinstance(ev, ItemCreatedEvent)
    assert ev.type == WebhookEventType.ITEM_CREATED

    # Known alias: change_column_values → change_column_value
    body2 = {"event": {"type": "change_column_values", "boardId": 3, "pulseId": 4, "columnId": "status"}}
    ev2 = parse_webhook(body2)
    assert isinstance(ev2, ColumnChangeEvent)
    assert ev2.type == WebhookEventType.COLUMN_CHANGE and ev2.column_id == "status"


def test_parse_item_name_change_event():
    body = {"event": {"type": "change_name", "boardId": 123, "pulseId": 456, "itemName": "Renamed"}}
    ev = parse_webhook(body)
    assert isinstance(ev, ItemNameChangedEvent)
    assert ev.type == WebhookEventType.ITEM_NAME_CHANGE
    assert ev.board_id == "123" and ev.item_id == "456" and ev.item_name == "Renamed"


def test_parse_column_created_event():
    body = {"event": {"type": "create_column", "boardId": 9, "userId": 8, "columnId": "status", "columnType": "status", "columnTitle": "Status"}}
    ev = parse_webhook(body)
    assert isinstance(ev, ColumnCreatedEvent)
    assert ev.type == WebhookEventType.COLUMN_CREATED
    assert ev.board_id == "9" and ev.user_id == "8" and ev.column_id == "status"


def test_parse_subitem_events_created_and_column_change():
    # subitem created uses entityId in some payloads
    created = {"event": {"type": "create_subitem", "boardId": 1, "entityId": 222}}
    ev_c = parse_webhook(created)
    assert isinstance(ev_c, SubitemCreatedEvent)
    assert ev_c.type == WebhookEventType.SUBITEM_CREATED and ev_c.item_id == "222"

    # subitem column change also maps to base event — just ensure type detection
    chg = {"event": {"type": "change_subitem_column_value", "boardId": 2, "entityId": 333, "columnId": "status", "columnType": "status"}}
    ev_s = parse_webhook(chg)
    assert isinstance(ev_s, SubitemColumnChangeEvent)
    assert ev_s.type == WebhookEventType.SUBITEM_COLUMN_CHANGE and ev_s.item_id == "333" and ev_s.column_id == "status"


def test_parse_unknown_event():
    body = {"event": {"type": "some_new_event", "boardId": 1}}
    ev = parse_webhook(body)
    assert isinstance(ev, WebhookEvent)
    assert ev.type == WebhookEventType.UNKNOWN
    assert ev.board_id == "1"


def test_verify_signature():
    secret = "topsecret"
    body = json.dumps({"hello": "world"}).encode("utf-8")
    mac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    assert verify_signature(secret=secret, body=body, header_signature=mac) is True
    assert verify_signature(secret=secret, body=body, header_signature="deadbeef") is False
    assert verify_signature(secret=secret, body=body, header_signature=None) is False



from __future__ import annotations

import json
import hmac
import hashlib

from monpy.oo import parse_webhook
from monpy.oo.webhooks.events import (
    WebhookEvent,
    ItemCreatedEvent,
    ColumnChangeEvent,
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



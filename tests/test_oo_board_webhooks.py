from __future__ import annotations

import uuid
from typing import Any

import pytest

from monpy.oo.enums import WebhookEventType


@pytest.fixture(scope="module")
def board(live_env: dict[str, Any]):
    return live_env["bd1"]


@pytest.mark.live
def test_board_webhook_management(board: Any, live_env: dict[str, Any]):
    """
    Test webhook registration, listing, and unregistration on a board.
    """
    # A unique URL for each test run to avoid collisions
    webhook_url = f"{live_env['webhook_url_base']}/hooks/{uuid.uuid4()}/"

    # 1. Start with a clean slate (optional, but good practice)
    for hook in board.list_webhooks():
        board.unregister_webhook(hook.id)

    # 2. Register a new webhook
    event_type = WebhookEventType.ITEM_CREATED
    created_hook_data = board.register_webhook(url=webhook_url, event=event_type)
    assert "id" in created_hook_data
    webhook_id = str(created_hook_data["id"])

    # 3. List webhooks and find the one we created
    all_webhooks = board.list_webhooks()
    found_hook = next((h for h in all_webhooks if h.id == webhook_id), None)

    assert found_hook is not None
    assert found_hook.event == event_type.value
    assert found_hook.board_id == board.id

    # 4. Unregister the webhook
    board.unregister_webhook(webhook_id)

    # 5. Verify it's gone
    webhooks_after_delete = board.list_webhooks()
    assert webhook_id not in [h.id for h in webhooks_after_delete]

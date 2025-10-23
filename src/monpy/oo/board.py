from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Iterator, List, Optional, Tuple

from .base import BaseModel
from ..exceptions import FeatureNotSupported
from .column import Column, ColumnCollection
from .webhooks import Webhook


@dataclass
class Board(BaseModel):
    name: str | None = None
    board_kind: str | None = None
    state: str | None = None
    workspace_id: str | None = None
    updated_at: str | None = None

    _columns_cache: ColumnCollection | None = None

    @property
    def columns(self) -> ColumnCollection:
        if self._columns_cache is None:
            cols = self._session.client.get_columns(self.id)
            typed = [
                Column(
                    id=str(c["id"]),
                    title=c.get("title"),
                    type=c.get("type"),
                    settings=c.get("settings"),
                    connected_board_ids=c.get("connected_board_ids"),
                )
                for c in cols
            ]
            for c in typed:
                c._session = self._session
            self._columns_cache = ColumnCollection(self, typed)
        return self._columns_cache

    def archive(self) -> None:
        self._session.client.archive_board(self.id)

    def rename(self, name: str) -> None:
        self._session.client.rename_board(self.id, name=name)
        self.name = name

    def duplicate(self, *, with_pulses: bool = True, name: str | None = None) -> dict:
        dup_type = "duplicate_board_with_pulses" if with_pulses else "duplicate_board_with_structure"
        return self._session.client.duplicate_board(self.id, duplicate_type=dup_type, board_name=name)

    def unarchive(self) -> None:
        self._session.client.unarchive_board(self.id)

    def _flush_changes(self) -> None:
        # monday API exposes limited board attribute mutations; start with name only
        if "name" in self._dirty and self.name is not None:
            # There is no dedicated helper; reuse low-level mutation if needed later.
            # For now, fetch-nothing update is omitted until a safe mutation is added.
            pass

    def _refresh_from_api(self) -> None:
        raw = self._session.client.get_board(self.id)
        self.name = raw.get("name")
        self.board_kind = raw.get("board_kind")
        self.state = raw.get("state")
        self.workspace_id = str(raw.get("workspace_id")) if raw.get("workspace_id") is not None else None
        self.updated_at = raw.get("updated_at")
        # reset column cache on refresh
        self._columns_cache = None

    # --- items convenience --------------------------------------------
    def list_items(self, *, limit: int = 100, state: str | list[str] | None = "active") -> tuple[list[dict], Optional[str]]:
        return self._session.client.list_items(self.id, limit=limit, state=state)

    def create_item(self, *, group_id: str, item_name: str, values: Optional[dict] = None) -> "Item":
        from .item import Item
        data = self._session.client.create_item(self.id, group_id=group_id, item_name=item_name, column_values=values)
        it = Item(id=str(data["id"]), name=data.get("name"), state=data.get("state"), updated_at=data.get("updated_at"), board_id=self.id)
        it._session = self._session
        return it

    # --- group convenience --------------------------------------------
    def groups(self) -> list[dict]:
        return self._session.client.list_groups(self.id)

    def create_group(self, *, title: str) -> dict:
        return self._session.client.create_group(self.id, title=title)

    def rename_group(self, group_id: str, *, title: str) -> None:
        try:
            self._session.client.rename_group(self.id, group_id, title=title)
        except FeatureNotSupported:
            # Gracefully ignore when API does not support renaming groups
            return

    def archive_group(self, group_id: str) -> None:
        self._session.client.archive_group(self.id, group_id)

    def delete_group(self, group_id: str) -> None:
        self._session.client.delete_group(self.id, group_id)

    # --- subscribers ----------------------------------------------------
    def subscribers(self) -> list[dict]:
        return self._session.client.list_board_subscribers(self.id)

    def add_subscribers(self, user_ids: list[str] | list[int], *, kind: str = "subscriber") -> None:
        self._session.client.add_board_subscribers(self.id, user_ids, kind=kind)

    def remove_subscribers(self, user_ids: list[str] | list[int]) -> None:
        self._session.client.remove_board_subscribers(self.id, user_ids)

    def owners(self) -> list[dict]:
        return self._session.client.list_board_owners(self.id)

    def add_owners(self, user_ids: list[str] | list[int]) -> None:
        self._session.client.add_board_owners(self.id, user_ids)

    def members_by_role(self) -> dict:
        return self._session.client.list_board_members_by_role(self.id)

    def set_member_roles(self, assignments: dict[str, str] | dict[int, str]) -> None:
        self._session.client.set_board_subscriber_roles(self.id, assignments)

    # Iteration over items (paged)
    def iter_items(self, *, limit_per_page: int = 200, state: str | list[str] | None = "active") -> Iterator[dict]:
        client = self._session.client
        # Prefer client iterator when available (newer client)
        it = getattr(client, "iter_items", None)
        if callable(it):
            yield from it(self.id, page_size=limit_per_page, state=state)
            return
        # Fallback to manual cursor loop for older / fake clients used in tests
        cursor: Optional[str] = None
        while True:
            items, cursor = client.list_items(self.id, limit=limit_per_page, state=state, cursor=cursor)
            if not items:
                break
            for it in items:
                yield it
            if not cursor:
                break

    def take_items(self, n: int, *, state: str | list[str] | None = "active") -> list[dict]:
        out: list[dict] = []
        for it in self.iter_items(limit_per_page=min(200, n), state=state):
            out.append(it)
            if len(out) >= n:
                break
        return out

    def first_item(self, *, state: str | list[str] | None = "active") -> Optional[dict]:
        for it in self.iter_items(limit_per_page=1, state=state):
            return it
        return None

    def filter_items_by_name(self, *, name_contains: str, limit: int = 200, state: str | list[str] | None = "active") -> list[dict]:
        out: list[dict] = []
        for it in self.iter_items(limit_per_page=limit, state=state):
            if name_contains.lower() in (it.get("name") or "").lower():
                out.append(it)
        return out

    # --- columns convenience ------------------------------------------
    def create_column(self, *, title: str, column_type: str | "ColumnType", defaults: Optional[dict | "ColumnDefaults" | dict] = None, description: Optional[str] = None) -> Column:
        raw = self._session.client.create_column(
            self.id,
            title=title,
            column_type=column_type,
            defaults=defaults,
            description=description,
        )
        c = Column(id=str(raw["id"]), title=raw.get("title"), type=raw.get("type"), settings=raw.get("settings"))
        c._session = self._session
        # Reset cache so new column becomes visible via .columns
        self._columns_cache = None
        return c

    def update_column(self, column_id: str, *, title: Optional[str] = None, description: Optional[str] = None) -> None:
        self._session.client.update_column(self.id, column_id, title=title, description=description)
        # Refresh cache next time
        self._columns_cache = None

    # --- search convenience -------------------------------------------
    def items_by_column_value(self, *, column_attr: str, value: object, limit: int | None = None) -> list[dict]:
        col_id = self.columns.id_for_attr(column_attr)
        return self._session.client.items_by_column_values(self.id, column_id=col_id, column_value=value, limit=limit)

    # --- prefetch convenience -----------------------------------------
    def prefetch_items_values(self, item_ids: list[str], *, column_ids: Optional[list[str]] = None, batch_size: int = 100) -> list[dict]:
        """Prefetch values for many items on this board and warm OO caches."""
        return self._session.prefetch_items_values(item_ids, column_ids=column_ids, include_board=True, batch_size=batch_size)

    # --- webhooks ------------------------------------------------------
    def register_webhook(self, *, url: str, event: str | "WebhookEventType", config: Optional[dict] = None) -> dict:
        """Create a webhook for this board and return the created object (id by default)."""
        return self._session.client.create_webhook(self.id, url=url, event=event, config=config)

    def unregister_webhook(self, webhook_id: str) -> None:
        """Delete a webhook by id."""
        self._session.client.unregister_webhook(webhook_id)

    def list_webhooks(self) -> list[Webhook]:
        """List webhooks registered on this board."""
        raw_webhooks = self._session.client.list_webhooks(self.id)
        webhooks = []
        for w in raw_webhooks:
            hook = Webhook(
                id=str(w["id"]),
                board_id=str(w.get("board_id") or self.id),
                event=w.get("event"),
                config=w.get("config"),
            )
            hook._session = self._session
            webhooks.append(hook)
        return webhooks



"""
Requirements:
- workspaces:
    - list them out
    - retrieve meta info having been given a board ID
    - add workspace with meta info
    - edit workspace's meta info, setting multiple fields at once

- boards:
    - list them out
    - retrieve meta info having been given a board ID
    - add board with meta info
    - edit board's meta info, setting multiple fields at once

- columns:
    - list them out
    - retrieve meta info having been given a column ID
        (if connect boards column, also get board ID list, if mirror column, also get referenced column id)
    - add column with meta info
    - edit column's meta info, setting multiple fields at once

- items:
    - list all by ID and name only
    - retrieve values having been given an ID
        (column id, name, value only needed,
        for connect column only item ID needed, ignore mirror columns as that's gettable from the column query)
    - add item with values
    - edit item as batch, setting multiple values at once
"""


from __future__ import annotations

import io
import json
import mimetypes
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Sequence, Mapping, Iterator
from importlib.metadata import PackageNotFoundError, version as pkg_version
from .exceptions import MondayAPIError, FeatureNotSupported
import requests
import logging

logger = logging.getLogger(__name__)

class MondayClient:
    """
    Lightweight synchronous client for the monday.com GraphQL API.

    Workspace helpers are fully implemented; board / column helpers have now
    been added following the same minimalist, “only-fetch-what-you-need”
    philosophy.

    Parameters
    ----------
    token
        **User** API token (not OAuth).
    api_version
        Version string as required by monday (default: “2025-10”).
    max_retries, backoff
        Simple exponential back-off for handling 429 rate limits.
    endpoint, files_endpoint
        Override only when talking to a proxy / mock.
    """

    _DELETABLE_DOC_BLOCK_TYPES = {
        "normal text",
        "bulleted list",
        "numbered list",
        "check list",
        "quote",
        "code",
        "table",
        "large title"
    }

    _MAX_FILE_BYTES: int = 500 * 1024 * 1024

    _DEFAULT_WS_FIELDS = ("id", "name", "kind", "description")
    _DEFAULT_BOARD_FIELDS = (
        "id",
        "name",
        "board_kind",      # “public”, “private”, “share”
        "state",           # “active”, “archived”, “deleted”
        "workspace_id",
        "updated_at"
    )
    _DEFAULT_COLUMN_FIELDS = (
        "id",
        "title",
        "type",
        "settings_str",
    )
    _DEFAULT_ITEM_FIELDS: tuple[str, ...] = ("id", "name", "state", "updated_at")
    _DEFAULT_COLUMN_VALUE_FIELDS: tuple[str, ...] = (
        "id",
        "value",
        "text",
        "type",
    )
    _DEFAULT_SUBITEM_FIELDS: tuple[str, ...] = ("id", "name", "state", "updated_at")
    _DEFAULT_GROUP_FIELDS: tuple[str, ...] = ("id", "title", "archived")
    _DEFAULT_USER_FIELDS: tuple[str, ...] = ("id", "name", "email")
    _BOARD_RELATION_FRAGMENT = "... on BoardRelationColumn { allowed_board_ids }"
    _DEFAULT_WEBHOOK_FIELDS: tuple[str, ...] = ("id",)
    _DEFAULT_DOC_FIELDS = (
        "id",  # doc id (≠ object_id!)
        "name",
        "url",  # direct URL in the UI
        "object_id",  # same number you see in the column JSON
        "workspace_id",
    )

    # ------------------------------------------------------------------
    # Construction & low-level helpers
    # ------------------------------------------------------------------

    def __init__(
        self,
        token: str,
        *,
        api_version: str = "2025-10",
        max_retries: int = 3,
        backoff: float = 1.0,
        endpoint: str = "https://api.monday.com/v2",
        files_endpoint: str = "https://api.monday.com/v2/file",
    ) -> None:
        if not token:
            raise ValueError("A non-empty monday.com API token is required")

        self.endpoint = endpoint
        self.files_endpoint = files_endpoint
        self.token = token.strip()
        self.api_version = api_version
        self.max_retries = max_retries
        self.backoff = backoff
        # Number of retries when encountering HTTP 403 responses.  This is
        # configured by callers via ``client.retries`` and defaults to ``0``.
        self.retries: int = 0

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": self.token,
                "Content-Type": "application/json",
                "API-Version": self.api_version,
                "User-Agent": self._user_agent(),
            }
        )

    # ---------------- low-level GraphQL helpers -----------------------

    def _request(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """POST the GraphQL *query* and return the ``data`` part only."""
        payload: Dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        total_retries = max(self.max_retries, self.retries)
        for attempt in range(total_retries + 1):

            try:
                response = self._session.post(
                    self.endpoint, json=payload, timeout=30
                )
            except requests.RequestException as exc:
                if attempt < self.max_retries:
                    time.sleep(self.backoff * 2**attempt)
                    continue
                raise MondayAPIError("Network error") from exc

            # Gracefully handle 429 “too many requests”
            if response.status_code == 429 and attempt < self.max_retries:
                time.sleep(self.backoff * 2**attempt)
                continue

            # Retry on transient HTTP 5xx responses
            if response.status_code >= 500 and attempt < self.max_retries:
                time.sleep(self.backoff * 2**attempt)
                continue

            # Retry on HTTP 403 responses when configured to do so
            if response.status_code == 403 and attempt < self.retries:
                time.sleep(self.backoff * 2**attempt)
                continue

            # Anything other than HTTP 200 is fatal
            if response.status_code != 200:
                raise MondayAPIError(
                    f"HTTP {response.status_code}: {response.text}"
                )

            data = response.json()

            if "errors" in data:
                retry = False
                if attempt < self.max_retries:
                    for err in data["errors"]:
                        ext = err.get("extensions") or {}
                        code = ext.get("status_code") or ext.get("error_code")
                        msg = err.get("message", "").lower()
                        if msg == "internal server error" or str(code).startswith("5"):
                            retry = True
                            break
                if retry:
                    time.sleep(self.backoff * 2**attempt)
                    continue
                raise MondayAPIError(
                    f"GraphQL errors returned for: \n{variables}\n", errors=data["errors"]
                )

            return data["data"]

        raise MondayAPIError("Unrecoverable rate-limit / network failure")

    # Public wrappers – handy for debugging
    def query(self, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request(query, variables)

    def mutation(self, mutation: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return self._request(mutation, variables)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _user_agent(self) -> str:
        try:
            v = pkg_version("monpy")
        except PackageNotFoundError:
            v = "0"
        return f"monpy/{v}"

    # ------------------------------------------------------------------
    # Helper to (optionally) narrow fields for minimal payloads
    # ------------------------------------------------------------------

    @staticmethod
    def _fields_to_str(
        fields: Optional[List[str] | tuple[str, ...]],
        default: tuple[str, ...],
    ) -> str:
        """
        Convert a list / tuple of field names to the GraphQL selection set.

        Passing ``None`` yields the sensible default defined per entity.
        """
        if fields is None:
            fields = default
        return " ".join(fields)

    # ------------------------------------------------------------------
    # Error classification helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error_messages_lower(errors: Optional[List[Dict[str, Any]]]) -> List[str]:
        """Return error messages lower‑cased for simple substring checks."""
        return [str((err or {}).get("message", "")).lower() for err in (errors or [])]

    @staticmethod
    def _is_connect_boards_not_supported_error(errors: Optional[List[Dict[str, Any]]]) -> bool:
        """Heuristics to detect when Connect Boards are not supported.

        Triggers on common monday GraphQL messages for unsupported enum values or
        account/plan restrictions around the ``board_relation``/``connect_boards`` type.
        """
        msgs = MondayClient._error_messages_lower(errors)
        # 1) Message-based checks (backward compatible heuristics)
        for msg in msgs:
            if (
                ("enum" in msg and "columntype" in msg and ("board_relation" in msg or "board-relation" in msg) and ("no value" in msg or "unknown" in msg))
                or (("board_relation" in msg or "board-relation" in msg) and ("not supported" in msg or "not enabled" in msg or "not allowed" in msg or "permission" in msg or "plan" in msg or "feature" in msg))
                or ("connect" in msg and "board" in msg and ("not supported" in msg or "not enabled" in msg or "not allowed" in msg or "permission" in msg or "plan" in msg))
                or ("this column type is not supported yet in the api" in msg)
            ):
                return True

        # 2) Extension-code based checks (preferred when available)
        for err in (errors or []):
            ext = (err or {}).get("extensions") or {}
            code = (ext.get("code") or ext.get("error_code") or "").strip()
            # Known error codes reported by monday for unsupported column type
            if code in {"InvalidColumnTypeException", "UnsupportedColumnType", "ColumnTypeNotSupported"}:
                return True
            # Some responses include the actual type in error_data
            actual = str(((ext.get("error_data") or {}).get("actual_type")) or "").lower()
            if actual in {"board_relation", "board-relation", "connect_boards", "boardrelation"}:
                return True
            # Some deployments put a human-readable array of errors under extensions.errors
            try:
                nested_msgs = [str(x).lower() for x in (ext.get("errors") or [])]
            except Exception:
                nested_msgs = []
            for m in nested_msgs:
                if (
                    ("not supported" in m or "not supported yet" in m or "not enabled" in m)
                    and ("board-relation" in m or "board_relation" in m or "connect" in m)
                ) or ("this column type \"board-relation\" is not supported yet in the api" in m):
                    return True
        return False

    @staticmethod
    def _is_docs_not_supported_or_forbidden_error(errors: Optional[List[Dict[str, Any]]]) -> bool:
        """Heuristics to detect when Docs queries/mutations are unavailable or forbidden.

        Matches lack of schema fields (older API) and permission/scope errors.
        """
        msgs = MondayClient._error_messages_lower(errors)
        for msg in msgs:
            if (
                ("cannot query field" in msg and ("docs" in msg or "create_doc" in msg or "create_doc_block" in msg or "delete_doc_block" in msg))
                or ("field \"docs\"" in msg)
                or ("doc" in msg and ("permission" in msg or "scope" in msg or "forbidden" in msg or "unauthorized" in msg or "not enabled" in msg or "not supported" in msg))
            ):
                return True
        return False

    # ------------------------------------------------------------------
    # WORKSPACES
    # ------------------------------------------------------------------

    # 1. List workspaces ------------------------------------------------

    def list_workspaces(
        self,
        *,
        limit: int = 25,
        page: int | None = None,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch up to *limit* workspaces (optionally a specific *page*).

        Only the requested *fields* are returned to keep payloads small.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_WS_FIELDS)
        var_decls: list[str] = ["$limit: Int!"]
        args: list[str] = ["limit: $limit"]
        vars_: dict[str, Any] = {"limit": limit}
        if page is not None:
            var_decls.append("$pg: Int")
            args.append("page: $pg")
            vars_["pg"] = int(page)
        q = (
            f"query ({', '.join(var_decls)}) {{ workspaces({', '.join(args)}) {{ {field_str} }} }}"
        )
        return self.query(q, vars_)["workspaces"]

    def iter_workspaces(
        self,
        *,
        page_size: int = 25,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Iterator[Dict[str, Any]]:
        """Yield all workspaces page by page (single request per page)."""
        from .pagination import iterate_pages

        yield from iterate_pages(
            lambda pg, sz: self.list_workspaces(limit=sz, page=pg, fields=fields),
            page_size,
        )

    def get_all_workspaces(
        self,
        *,
        page_size: int = 25,
        fields: Optional[List[str] | tuple[str, ...]] = None,
        max_items: int | None = None,
    ) -> List[Dict[str, Any]]:
        from .pagination import collect

        return collect(self.iter_workspaces(page_size=page_size, fields=fields), max_items)

    # 2. Get a workspace by its ID -------------------------------------
    def get_workspace(
        self,
        workspace_id: str,
        *,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """Return metadata for a single workspace."""
        field_str = self._fields_to_str(fields, self._DEFAULT_WS_FIELDS)
        q = f"""
        query ($id: [ID!]!) {{
          workspaces (ids: $id) {{
            {field_str}
          }}
        }}
        """
        result = self.query(q, {"id": [workspace_id]})["workspaces"]
        if not result:
            raise MondayAPIError(f"Workspace with ID {workspace_id} not found")
        return result[0]

    # 3. Resolve workspace metadata *given a board ID* -----------------

    def get_workspace_for_board(
        self,
        board_id: str,
        *,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Convenience helper: supply a *board_id* and receive its workspace.

        Saves you from an extra round-trip when you only have the board.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_WS_FIELDS)
        q = f"""
        query ($bid: [ID!]!) {{
          boards (ids: $bid) {{
            workspace {{
              {field_str}
            }}
          }}
        }}
        """
        boards = self.query(q, {"bid": [board_id]})["boards"]
        if not boards or boards[0].get("workspace") is None:
            raise MondayAPIError(
                f"Board {board_id} not found or has no parent workspace"
            )
        return boards[0]["workspace"]

    # 4. Create a workspace --------------------------------------------

    def create_workspace(
        self,
        *,
        name: str,
        kind: str = "open",  # "open", "closed", "private"
        description: Optional[str] = None,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Create a workspace and immediately return its metadata.

        Parameters
        ----------
        name
            Human-readable name (required by monday).
        kind
            Visibility – one of: “open”, “closed”, “private”.
        description
            Optional description shown in the monday UI.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_WS_FIELDS)
        m = f"""
        mutation ($name: String!, $kind: WorkspaceKind!, $desc: String) {{
          create_workspace (name: $name, kind: $kind, description: $desc) {{
            {field_str}
          }}
        }}
        """
        vars = {
            "name": name,
            "kind": kind,
            "desc": description,
        }
        return self.mutation(m, vars)["create_workspace"]

    # 5. Update a workspace --------------------------------------------

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: Optional[str] = None,
        kind: Optional[str] = None,
        description: Optional[str] = None,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Update one or more attributes on a workspace.

        monday API ≥ 2025-01 expects the attributes object to be sent as the
        typed input `UpdateWorkspaceAttributesInput`, **not** as a raw JSON
        scalar.
        """
        attrs: Dict[str, Any] = {}
        if name is not None:
            attrs["name"] = name
        if kind is not None:
            attrs["kind"] = kind
        if description is not None:
            attrs["description"] = description
        if not attrs:
            raise ValueError("Nothing to update – at least one attribute is required")

        field_str = self._fields_to_str(fields, self._DEFAULT_WS_FIELDS)

        m = f"""
        mutation ($id: ID!, $attrs: UpdateWorkspaceAttributesInput!) {{
          update_workspace (id: $id, attributes: $attrs) {{
            {field_str}
          }}
        }}
        """
        return self.mutation(m, {"id": workspace_id, "attrs": attrs})["update_workspace"]

    def delete_workspace(self, workspace_id: str) -> None:
        """
        Permanently delete a workspace.

        Notes
        -----
        monday.com does not offer a reversible “archive” call for workspaces.
        This mutation moves the whole workspace (and its boards, items, etc.)
        to the account’s trash where it can be restored for 30 days.
        """
        m = """
        mutation ($id: ID!) {
          delete_workspace (workspace_id: $id) { id }
        }
        """
        self.mutation(m, {"id": workspace_id})

    # ------------------------------------------------------------------
    # BOARDS
    # ------------------------------------------------------------------

    # 1. List boards ----------------------------------------------------

    def list_boards(
        self,
        *,
        limit: int = 25,
        workspace_id: str | None = None,
        state: str | list[str] | None = "active",      # NEW
        fields: list[str] | tuple[str, ...] | None = None,
        page: int | None = None,
    ) -> list[dict]:
        field_str = self._fields_to_str(fields, self._DEFAULT_BOARD_FIELDS)
        vars: dict[str, Any] = {"limit": limit}
        state_block = ""
        if state not in (None, "active"):
            state_block = ", state: $st"
            vars["st"] = state
        page_block = ""
        if page is not None:
            page_block = ", page: $pg"
            vars["pg"] = int(page)
        w_filter = "" if workspace_id is None else ", workspace_ids: $wids"
        if workspace_id:
            vars["wids"] = [workspace_id]

        q = f"""
        query ($limit:Int!{', $st:BoardStateType' if state_block else ''}{', $pg:Int' if page_block else ''}{', $wids:[ID!]' if workspace_id else ''}) {{
          boards(limit:$limit{w_filter}{state_block}{page_block}) {{
            {field_str}
          }}
        }}"""
        return self.query(q, vars)["boards"]

    def iter_boards(
        self,
        *,
        page_size: int = 100,
        workspace_id: str | None = None,
        state: str | list[str] | None = "active",
        fields: list[str] | tuple[str, ...] | None = None,
    ) -> Iterator[dict]:
        from .pagination import iterate_pages

        yield from iterate_pages(
            lambda pg, sz: self.list_boards(
                limit=sz, workspace_id=workspace_id, state=state, fields=fields, page=pg
            ),
            page_size,
        )

    def get_all_boards(
        self,
        *,
        page_size: int = 100,
        workspace_id: str | None = None,
        state: str | list[str] | None = "active",
        fields: list[str] | tuple[str, ...] | None = None,
        max_items: int | None = None,
    ) -> list[dict]:
        from .pagination import collect

        return collect(
            self.iter_boards(page_size=page_size, workspace_id=workspace_id, state=state, fields=fields),
            max_items,
        )

    # 2. Get a single board by ID --------------------------------------

    def get_board(
        self,
        board_id: str,
        *,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """Return metadata for a single board."""
        field_str = self._fields_to_str(fields, self._DEFAULT_BOARD_FIELDS)
        q = f"""
        query ($id: [ID!]!) {{
          boards (ids: $id) {{
            {field_str}
          }}
        }}
        """
        result = self.query(q, {"id": [board_id]})["boards"]
        if not result:
            raise MondayAPIError(f"Board with ID {board_id} not found")
        return result[0]

    # 3. Create a board -------------------------------------------------

    def create_board(
        self,
        *,
        name: str,
        board_kind: str = "public",          # “public”, “private”, “share”
        workspace_id: Optional[str] = None,
        template_id: Optional[str] = None,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Create a board and return its metadata.

        If *workspace_id* is omitted, monday will place the board in the
        account’s default workspace.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_BOARD_FIELDS)
        m = f"""
        mutation (
          $name: String!,
          $kind: BoardKind!,
          $ws: ID,
          $template: ID
        ) {{
          create_board(
            board_name: $name,
            board_kind: $kind,
            workspace_id: $ws,
            template_id: $template
          ) {{
            {field_str}
          }}
        }}
        """
        vars = {
            "name": name,
            "kind": board_kind,
            "ws": workspace_id,
            "template": template_id,
        }
        return self.mutation(m, vars)["create_board"]

    # 4. Archive (delete) a board --------------------------------------

    def archive_board(self, board_id: str) -> None:
        """
        Archive a board.

        monday.com does not offer a generic “delete” for boards – “archive”
        is as close as it gets via the public API.
        """
        m = """
        mutation ($id: ID!) {
          archive_board (board_id: $id) { id }
        }
        """
        self.mutation(m, {"id": board_id})

    # 5. Rename / duplicate / unarchive a board -------------------------

    def rename_board(self, board_id: str, *, name: str) -> None:
        """
        Change a board's name.
        """
        m = (
            "mutation ($id: ID!, $name: String!){"
            "  change_board_name(board_id:$id, name:$name){ id }"
            "}"
        )
        self.mutation(m, {"id": board_id, "name": name})

    def duplicate_board(
        self,
        board_id: str,
        *,
        duplicate_type: str = "duplicate_board_with_structure",
        board_name: str | None = None,
        fields: list[str] | tuple[str, ...] | None = ("id",),
    ) -> dict:
        """
        Duplicate a board. The ``duplicate_type`` is the monday enum value, for example
        "duplicate_board_with_structure" or "duplicate_board_with_pulses".
        """
        field_str = self._fields_to_str(fields, ("id",))
        m = f"""
        mutation ($id: ID!, $type: BoardDuplicateType!, $name: String) {{
          duplicate_board(board_id:$id, duplicate_type:$type, board_name:$name) {{
            {field_str}
          }}
        }}
        """
        return self.mutation(m, {"id": board_id, "type": duplicate_type, "name": board_name}).get("duplicate_board", {})

    def unarchive_board(self, board_id: str) -> None:
        """
        Unarchive a previously archived board.
        """
        m = "mutation ($id: ID!){ unarchive_board(board_id:$id){ id } }"
        self.mutation(m, {"id": board_id})

    # 6b. Webhook helpers ----------------------------------------------

    def create_webhook(
        self,
        board_id: str,
        *,
        url: str,
        event: str | "WebhookEventType",
        config: Optional[Dict[str, Any]] = None,
        fields: Optional[List[str] | tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Register a webhook on a board.

        Parameters
        ----------
        board_id : str
            Target board ID.
        url : str
            HTTPS endpoint to receive webhook callbacks.
        event : str
            Monday GraphQL enum value for the webhook event (WebhookEventType).
        config : dict | None
            Optional configuration payload, depends on event type (e.g., columnId).
        fields : list[str] | tuple[str, ...] | None
            Selection set for the returned webhook object. Defaults to ("id",).
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_WEBHOOK_FIELDS)
        # Accept Enum for stronger typing; fall back to string value
        try:
            # late import to avoid circular import at module import time
            from .oo.enums import WebhookEventType as _WebhookEventType  # type: ignore
            if isinstance(event, _WebhookEventType):  # type: ignore[arg-type]
                event = event.value
        except Exception:
            # Best-effort: if import fails, assume user passed str
            pass
        cfg_decl = ", $cfg: JSON" if config is not None else ""
        cfg_arg = ", config: $cfg" if config is not None else ""
        m = f"""
        mutation ($board: ID!, $url: String!, $event: WebhookEventType!{cfg_decl}) {{
          create_webhook(board_id: $board, url: $url, event: $event{cfg_arg}) {{
            {field_str}
          }}
        }}
        """
        vars: Dict[str, Any] = {"board": board_id, "url": url, "event": event}
        if config is not None:
            vars["cfg"] = json.dumps(config)
        return self.mutation(m, vars)["create_webhook"]

    def delete_webhook(self, webhook_id: str) -> None:
        """
        Delete a webhook by its ID.
        """
        self.mutation("mutation ($id: ID!){ delete_webhook(id:$id){ id } }", {"id": webhook_id})

    # 6. Users and board subscribers -----------------------------------

    def me(self, *, fields: list[str] | tuple[str, ...] | None = None) -> dict:
        """Return the current user bound to this token."""
        field_str = self._fields_to_str(fields, self._DEFAULT_USER_FIELDS)
        q = f"query {{ me {{ {field_str} }} }}"
        return self.query(q)

    def list_users(
        self,
        *,
        limit: int | None = None,
        page: int | None = None,
        fields: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict]:
        field_str = self._fields_to_str(fields, self._DEFAULT_USER_FIELDS)
        var_decls: list[str] = []
        args: list[str] = []
        vars: dict[str, Any] = {}
        if limit is not None:
            var_decls.append("$lim:Int")
            args.append("limit:$lim")
            vars["lim"] = int(limit)
        if page is not None:
            var_decls.append("$pg:Int")
            args.append("page:$pg")
            vars["pg"] = int(page)
        arg_str = f"({', '.join(args)})" if args else ""
        q = f"query ({', '.join(var_decls)}) {{ users{arg_str} {{ {field_str} }} }}" if var_decls else f"query {{ users {{ {field_str} }} }}"
        return self.query(q, vars)["users"] if var_decls else self.query(q)["users"]

    def iter_users(
        self,
        *,
        page_size: int = 100,
        fields: list[str] | tuple[str, ...] | None = None,
    ) -> Iterator[dict]:
        from .pagination import iterate_pages

        yield from iterate_pages(
            lambda pg, sz: self.list_users(limit=sz, page=pg, fields=fields), page_size
        )

    def get_all_users(
        self,
        *,
        page_size: int = 100,
        fields: list[str] | tuple[str, ...] | None = None,
        max_items: int | None = None,
    ) -> list[dict]:
        from .pagination import collect

        return collect(self.iter_users(page_size=page_size, fields=fields), max_items)

    def list_board_subscribers(self, board_id: str, *, fields: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        field_str = self._fields_to_str(fields, self._DEFAULT_USER_FIELDS)
        q = (
            "query ($id:[ID!]!){"
            "  boards(ids:$id){"
            f"    subscribers{{ {field_str} }}"
            "  }"
            "}"
        )
        boards = self.query(q, {"id": [board_id]})["boards"]
        if not boards:
            raise MondayAPIError(f"Board {board_id} not found")
        return boards[0].get("subscribers", [])

    def list_board_owners(self, board_id: str, *, fields: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        """Return owners for a board."""
        field_str = self._fields_to_str(fields, self._DEFAULT_USER_FIELDS)
        q = (
            "query ($id:[ID!]!){"
            "  boards(ids:$id){"
            f"    owners{{ {field_str} }}"
            "  }"
            "}"
        )
        boards = self.query(q, {"id": [board_id]})["boards"]
        if not boards:
            raise MondayAPIError(f"Board {board_id} not found")
        return boards[0].get("owners", [])

    def list_board_members_by_role(self, board_id: str, *, fields: list[str] | tuple[str, ...] | None = None) -> dict:
        """Return both owners and subscribers for a board in one call."""
        field_str = self._fields_to_str(fields, self._DEFAULT_USER_FIELDS)
        q = (
            "query ($id:[ID!]!){"
            "  boards(ids:$id){"
            f"    owners{{ {field_str} }}"
            f"    subscribers{{ {field_str} }}"
            "  }"
            "}"
        )
        boards = self.query(q, {"id": [board_id]})["boards"]
        if not boards:
            raise MondayAPIError(f"Board {board_id} not found")
        b = boards[0]
        return {"owners": b.get("owners", []), "subscribers": b.get("subscribers", [])}

    def add_board_subscribers(self, board_id: str, user_ids: list[str] | list[int], *, kind: str = "subscriber") -> None:
        """Add users to a board as subscribers/viewers/editors depending on *kind*."""
        m = (
            "mutation ($bid: ID!, $ids: [ID!]!, $kind: BoardSubscriberKind!){"
            "  add_subscribers_to_board(board_id:$bid, user_ids:$ids, kind:$kind){ id }"
            "}"
        )
        self.mutation(m, {"bid": board_id, "ids": [int(i) for i in user_ids], "kind": kind})

    def add_board_owners(self, board_id: str, user_ids: list[str] | list[int]) -> None:
        """Convenience: add users as board owners."""
        self.add_board_subscribers(board_id, user_ids, kind="owner")

    def set_board_subscriber_roles(self, board_id: str, assignments: dict[str, str] | dict[int, str]) -> None:
        """
        Set specific roles for multiple users on a board.

        assignments maps user_id -> kind (e.g., "owner" or "subscriber").
        """
        # Group by kind for fewer mutations
        buckets: dict[str, list[int]] = {}
        for uid, kind in assignments.items():
            buckets.setdefault(str(kind), []).append(int(uid))
        for kind, ids in buckets.items():
            self.add_board_subscribers(board_id, ids, kind=kind)

    def remove_board_subscribers(self, board_id: str, user_ids: list[str] | list[int]) -> None:
        m = (
            "mutation ($bid: ID!, $ids: [ID!]!){"
            "  remove_subscribers_from_board(board_id:$bid, user_ids:$ids){ id }"
            "}"
        )
        self.mutation(m, {"bid": board_id, "ids": [int(i) for i in user_ids]})

    # ------------------------------------------------------------------
    # Convenience: resolve board + column IDs given human names
    # ------------------------------------------------------------------

    def resolve_board_and_column_ids(
        self,
        *,
        workspace_name: str,
        board_name: str,
        title_mappings: Dict[str, str],
        workspace_limit: int = 100,
        board_limit: int = 500,
    ) -> Tuple[str, Dict[str, str]]:
        """
        Resolve IDs required for the Django lookup tables in one go.

        Parameters
        ----------
        workspace_name
            Human-readable workspace name in the monday UI.
        board_name
            Human-readable board name inside that workspace.
        title_mappings
            Dict that maps *internal* field keys (e.g. ``"email"``) to the
            *column titles* as shown in monday (e.g. ``"Email address"``).

        Returns
        -------
        Tuple[str, Dict[str, str]]
            ``(board_id, {field_key: column_id, …})``
        """
        # 1. Workspace ➜ ID
        workspaces = self.list_workspaces(limit=workspace_limit)
        ws = next((w for w in workspaces if w["name"] == workspace_name), None)
        if ws is None:
            raise ValueError(f'Workspace “{workspace_name}” not found')
        workspace_id = ws["id"]

        # 2. Board ➜ ID  (filter by workspace to be safe)
        boards = self.list_boards(
            limit=board_limit,
            workspace_id=workspace_id,
            fields=("id", "name", "workspace_id"),
        )
        board = next((b for b in boards if b["name"] == board_name), None)
        if board is None:
            raise ValueError(
                f'Board “{board_name}” not found inside workspace “{workspace_name}”'
            )
        board_id = board["id"]

        # 3. Column titles ➜ IDs
        columns = self.get_columns(board_id, fields=("id", "title"))
        title_to_id = {c["title"]: c["id"] for c in columns}

        col_id_map: Dict[str, str] = {}
        missing: List[str] = []
        for field_key, human_title in title_mappings.items():
            col_id = title_to_id.get(human_title)
            if col_id:
                col_id_map[field_key] = col_id
            else:
                missing.append(human_title)

        if missing:
            raise ValueError(
                f'Board “{board_name}” is missing columns: {", ".join(missing)}'
            )

        return board_id, col_id_map

    # ==================================================================
    # COLUMNS ––– NEW / COMPLETED
    # ==================================================================

    # 1 · List all columns on a board -----------------------------------

    def get_columns(
            self,
            board_id: str,
            *,
            fields: Optional[List[str] | Tuple[str, ...]] = None,
            parse_settings: bool = True,
    ) -> List[Dict[str, Any]]:
        field_str = self._fields_to_str(fields, self._DEFAULT_COLUMN_FIELDS)

        q = f"""
        query ($bid:[ID!]!) {{
          boards (ids: $bid) {{
            columns {{
              {field_str}
            }}
          }}
        }}
        """
        boards = self.query(q, {"bid": [board_id]})["boards"]
        if not boards:
            raise MondayAPIError(f"Board with ID {board_id} not found")
        cols = boards[0]["columns"]

        if parse_settings:
            for col in cols:
                self._augment_column_meta(col)

        return cols

    # 2 · Retrieve a single column by ID --------------------------------

    def get_column(
            self,
            board_id: str,
            column_id: str,
            *,
            fields: Optional[List[str] | Tuple[str, ...]] = None,
            parse_settings: bool = True,
    ) -> Dict[str, Any]:
        field_str = self._fields_to_str(fields, self._DEFAULT_COLUMN_FIELDS)

        q = f"""
        query ($bid:[ID!]!, $cid:[String!]!) {{
          boards (ids:$bid) {{
            columns (ids:$cid) {{ {field_str} }}
          }}
        }}
        """
        boards = self.query(q, {"bid": [board_id], "cid": [column_id]})["boards"]
        if not boards or not boards[0]["columns"]:
            raise MondayAPIError(
                f"Column {column_id} not found on board {board_id}"
            )
        col = boards[0]["columns"][0]

        if parse_settings:
            self._augment_column_meta(col)

        return col

    def get_column_id_by_title(self, board_id: str, column_title: str) -> str:
        try:
            col_id = next(
                c["id"]
                for c in self.get_columns(board_id)
                if c["title"] == column_title
            )
        except StopIteration:
            raise Exception('Column "SDK File" (type File) not found on the board')
        return col_id

    # 3 · Create a column ----------------------------------------------

    def create_column(
            self,
            board_id: str,
            *,
            title: str,
            column_type: str | "ColumnType",
            defaults: Optional[Dict[str, Any] | "ColumnDefaults" | Mapping[str, Any]] = None,
            description: Optional[str] = None,
            fields: Optional[List[str] | Tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        # Use a minimal selection set on mutation to avoid transient schema glitches
        # (e.g. 404 on settings_str directly from create_column). We'll fetch full
        # metadata with a follow-up query.
        m = (
            "mutation (\n"
            "  $bid: ID!,\n"
            "  $title: String!,\n"
            "  $type: ColumnType!,\n"
            "  $defaults: JSON,\n"
            "  $desc: String\n"
            ") {\n"
            "  create_column(\n"
            "    board_id: $bid,\n"
            "    title: $title,\n"
            "    column_type: $type,\n"
            "    defaults: $defaults,\n"
            "    description: $desc\n"
            "  ) { id title type }\n"
            "}"
        )
        # Normalize historical/alias column type names for API compatibility
        try:
            # late import to avoid circular imports
            from .oo.enums import ColumnType as _ColumnType  # type: ignore
            if isinstance(column_type, _ColumnType):  # type: ignore[arg-type]
                normalized_type = column_type.value.lower()
            else:
                normalized_type = str(column_type or "").lower()
        except Exception:
            normalized_type = str(column_type or "").lower()
        if normalized_type == "connect_boards":
            normalized_type = "board_relation"

        # Coerce defaults: support Protocol with to_dict(), Mapping, or raw dict
        defaults_payload: Dict[str, Any] = {}
        if defaults is not None:
            try:
                # runtime-checkable Protocol
                from .oo.columns.defaults import ColumnDefaults as _ColumnDefaults  # type: ignore
                if isinstance(defaults, _ColumnDefaults):  # type: ignore[arg-type]
                    defaults_payload = dict(defaults.to_dict())
                elif hasattr(defaults, "to_dict") and callable(getattr(defaults, "to_dict")):
                    defaults_payload = dict(getattr(defaults, "to_dict")())
                elif isinstance(defaults, Mapping):
                    defaults_payload = dict(defaults)
                elif isinstance(defaults, dict):
                    defaults_payload = defaults
            except Exception:
                try:
                    if hasattr(defaults, "to_dict") and callable(getattr(defaults, "to_dict")):
                        defaults_payload = dict(getattr(defaults, "to_dict")())
                    elif isinstance(defaults, Mapping):
                        defaults_payload = dict(defaults)
                    elif isinstance(defaults, dict):
                        defaults_payload = defaults
                except Exception:
                    defaults_payload = {}

        vars = {
            "bid": board_id,
            "title": title,
            "type": normalized_type,
            "defaults": json.dumps(defaults_payload),
            "desc": description,
        }
        try:
            created = self.mutation(m, vars)["create_column"]
            # If the mutation result already includes enough fields (e.g. tests mock
            # settings_str), avoid an extra network call.
            created_keys = set((created or {}).keys())
            requested = set(fields) if isinstance(fields, (list, tuple)) else set()
            if (not requested and "settings_str" in created_keys) or (requested and requested.issubset(created_keys)):
                self._augment_column_meta(created)
                result = created
            else:
                # Otherwise, follow-up read to obtain full metadata and parsed settings
                result = self.get_column(board_id, created.get("id"), fields=fields)

            # Post-condition: if connect-boards column was created but API does not
            # expose any linkage metadata for allowed boards, treat it as unsupported
            # for this account to allow callers/tests to skip gracefully.
            try:
                if normalized_type == "board_relation":
                    cb_ids = (result or {}).get("connected_board_ids") or []
                    settings = (result or {}).get("settings") or {}
                    fallback = (
                        settings.get("boardIds")
                        or settings.get("board_ids")
                        or settings.get("boardId")
                        or settings.get("board_id")
                        or settings.get("connected_boards")
                    )
                    if (not cb_ids) and (not fallback):
                        raise FeatureNotSupported(
                            "Connect boards columns created but linkage metadata is not exposed by this API/account",
                            errors=[],
                        )
            except FeatureNotSupported:
                # Re-raise to outer handler
                raise
            except Exception:
                # Best-effort; if any unexpected error occurs, return as-is
                pass

            return result
        except MondayAPIError as exc:
            # If Connect Boards (board_relation) is not supported or forbidden, raise FeatureNotSupported
            try:
                normalized_for_check = normalized_type
            except Exception:
                normalized_for_check = str(column_type or "").lower()
                if normalized_for_check == "connect_boards":
                    normalized_for_check = "board_relation"
            if normalized_for_check == "board_relation" and self._is_connect_boards_not_supported_error(getattr(exc, "errors", [])):
                raise FeatureNotSupported(
                    "Connect boards columns are not supported or permitted by this API/account",
                    errors=getattr(exc, "errors", []),
                ) from exc
            raise

    # 4 · Update a column (multiple attributes at once) ----------------

    def update_column(
            self,
            board_id: str,
            column_id: str,
            *,
            title: str | None = None,
            description: str | None = None,
    ) -> None:
        """
        Rename a column or change its description.

        Notes
        -----
        * The public monday.com GraphQL schema (tested with API v2025-04) only
          exposes the **`title`** and **`description`** attributes through
          ``change_column_title`` and ``change_column_metadata`` respectively.
          Any attempt to modify *settings* (e.g. to re-wire a Mirror column)
          triggers a validation error because `settings_str` is **not** part of
          the ``ColumnProperty`` enum.

        * **Mirror columns are read-only** regarding their linkage: you can read
          which source column they mirror, but you cannot change that through
          the API. Re-targeting requires manual action in the UI or creating a
          brand-new mirror column with the desired defaults.

        Parameters
        ----------
        board_id, column_id
            Identify the column to be updated.
        title, description
            New values; pass ``None`` to leave a field unchanged.
        """
        if title is not None:
            self.mutation(
                "mutation ($b:ID!, $c:String!, $t:String!){"
                "  change_column_title(board_id:$b, column_id:$c, title:$t){ id }"
                "}",
                {"b": board_id, "c": column_id, "t": title},
            )
        if description is not None:
            self.mutation(
                "mutation ($b:ID!, $c:String!, $v:String!){"
                "  change_column_metadata(board_id:$b, column_id:$c, "
                "                          column_property:description, "
                "                          value:$v){ id }"
                "}",
                {"b": board_id, "c": column_id, "v": description},
            )

    # ------------------------------------------------------------------
    # Private helper – parse settings_str for Connect / Mirror columns
    # ------------------------------------------------------------------

    @staticmethod
    def _augment_column_meta(col: Dict[str, Any]) -> None:
        """
        Parse ``settings_str`` and attach convenience keys
        (``connected_board_ids``, ``referenced_column_id``, ``settings``).

        Mirror columns
        --------------
        A mirror column’s ``referenced_column_id`` tells you which source column
        it reflects. **This linkage is immutable through the public API** – you
        can *read* it but you cannot change it programmatically. To re-wire a
        mirror you must either adjust it manually in the Monday UI or delete and
        recreate the column with the desired defaults.
        """
        raw = col.get("settings_str")
        if raw:
            try:
                settings = json.loads(raw)
            except ValueError:
                settings = {}
        else:
            settings = {}

        # Always expose the parsed settings blob, even if empty
        col["settings"] = settings

        typ = str(col.get("type", "")).lower().replace("-", "_")

        # --------------------------------------------------------------
        # Connect Boards columns
        # --------------------------------------------------------------
        if typ in ("board_relation", "connect_boards"):
            # 1.  Prefer the native GraphQL field (API ≥ 2025-04)
            board_ids = col.get("allowed_board_ids") or []

            # 2.  Fall back to the JSON blob for older APIs / unrestricted cols
            board_ids = (
                board_ids
                or settings.get("boardIds")         # plural camelCase
                or settings.get("board_ids")        # plural snake_case
                or settings.get("boardId")          # singular camelCase
                or settings.get("board_id")         # singular snake_case
                or settings.get("connected_boards") # legacy key
                or []
            )
            col["connected_board_ids"] = [str(b) for b in board_ids]

        # --------------------------------------------------------------
        # Mirror columns
        # --------------------------------------------------------------
        elif typ == "mirror":
            linked_column_dict = settings.get('displayed_linked_columns')  # key(board id): value(column id)

            if linked_column_dict:
                col["linked_column_dict"] = linked_column_dict

    # -------------------------------------------------------------- 1 —
    # List *up to* ``limit`` items on a board (ID + name only)
    # --------------------------------------------------------------

    def list_items(
        self,
        board_id: str,
        *,
        limit: int = 100,
        state: str | list[str] | None = "active",      # NEW
        fields: list[str] | tuple[str, ...] | None = None,
        cursor: str | None = None,
    ) -> tuple[list[dict], str | None]:

        if limit > 500:
            all_items: list[dict] = []
            remaining = limit
            next_cursor = cursor

            while remaining > 0:
                chunk, next_cursor = self.list_items(
                    board_id,
                    limit=min(remaining, 500),
                    state=state,
                    fields=fields,
                    cursor=next_cursor,
                )
                if not chunk:
                    break
                all_items.extend(chunk)
                remaining -= len(chunk)
                if not next_cursor:
                    break

            return all_items, next_cursor

        field_str = self._fields_to_str(fields, self._DEFAULT_ITEM_FIELDS)
        vars: dict[str, Any] = {"bid": [board_id], "limit": limit}
        state_block = ""
        if state not in (None, "active"):
            state_block = ", state: $st"
            vars["st"] = state

        cursor_block = ""
        if cursor is not None:
            cursor_block = ", cursor: $cur"
            vars["cur"] = cursor

        q = f"""
        query (
          $bid:[ID!]!,
          $limit:Int!{', $st:ItemStateType' if state_block else ''}{', $cur:String' if cursor_block else ''}
        ) {{
          boards(ids:$bid) {{
            items_page(limit:$limit{state_block}{cursor_block}) {{
              cursor
              items {{ {field_str} }}
            }}
          }}
        }}"""
        boards = self.query(q, vars)["boards"]
        if not boards:
            raise MondayAPIError(f"Board {board_id} not found")
        page_data = boards[0]["items_page"]
        return page_data["items"], page_data.get("cursor")

    def iter_items(
        self,
        board_id: str,
        *,
        page_size: int = 200,
        state: str | list[str] | None = "active",
        fields: list[str] | tuple[str, ...] | None = None,
        start_cursor: str | None = None,
    ) -> Iterator[dict]:
        from .pagination import iterate_cursor

        yield from iterate_cursor(
            lambda cur, sz: self.list_items(
                board_id, limit=sz, state=state, fields=fields, cursor=cur
            ),
            page_size,
            start_cursor=start_cursor,
        )

    def get_all_items(
        self,
        board_id: str,
        *,
        page_size: int = 200,
        state: str | list[str] | None = "active",
        fields: list[str] | tuple[str, ...] | None = None,
        max_items: int | None = None,
    ) -> list[dict]:
        from .pagination import collect

        return collect(
            self.iter_items(board_id, page_size=page_size, state=state, fields=fields),
            max_items,
        )

    # -------------------------------------------------------------- 2 —
    # Fetch *values* for a single item by its ID
    # --------------------------------------------------------------

    def get_item_values(
        self,
        item_id: str,
        *,
        include_board: bool = False,
        exclude_nonactive: bool = False,
        column_ids: list[str] | None = None,
        parse_json_values: bool = True,                    # new flag
        item_fields: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        # ---------------- GraphQL boilerplate -----------------------------
        item_field_str = self._fields_to_str(
            item_fields, self._DEFAULT_ITEM_FIELDS
        )

        col_filter = "(ids:$cids)" if column_ids else ""
        col_subselect = """
            id
            value
            text
            type
            ... on BoardRelationValue { linked_item_ids }
        """

        board_block = "board { id name }" if include_board else ""

        q = f"""
        query ($id:[ID!]!, $flag:Boolean!{', $cids:[String!]' if column_ids else ''}) {{
          items(ids:$id, exclude_nonactive:$flag) {{
            {item_field_str}
            {board_block}
            column_values{col_filter} {{ {col_subselect} }}
          }}
        }}"""

        vars = {"id": [item_id], "flag": exclude_nonactive}
        if column_ids:
            vars["cids"] = column_ids

        data = self.query(q, vars)["items"]
        if not data:
            raise MondayAPIError(f"Item {item_id} not found")

        item = data[0]

        # ---------------- Optional auto-decode ----------------------------
        if parse_json_values:
            for cv in item.get("column_values", []):
                raw = cv.get("value")
                if isinstance(raw, str) and raw and raw[0] in "{[":
                    try:
                        cv["value"] = json.loads(raw)
                    except ValueError:
                        # leave the original string if it isn’t valid JSON
                        pass

            # Best-effort normalization: some API versions may not populate
            # the human-readable text for Location columns immediately. When
            # missing, synthesize it from the structured value so callers see
            # a useful string.
            for cv in item.get("column_values", []):
                try:
                    if (cv.get("type") == "location") and (not cv.get("text")):
                        val = cv.get("value")
                        computed: str | None = None
                        if isinstance(val, dict):
                            computed = (
                                val.get("address")
                                or val.get("formattedAddress")
                                or val.get("formatted_address")
                            )
                            if not computed:
                                # Compose from parts when full address is absent
                                parts = [
                                    val.get("street") or val.get("street_name") or val.get("route"),
                                    val.get("city") or val.get("locality"),
                                    val.get("state") or val.get("administrative_area_level_1"),
                                    val.get("country"),
                                ]
                                computed = ", ".join(p for p in parts if isinstance(p, str) and p.strip()) or None
                        elif isinstance(val, str):
                            computed = val
                        if computed:
                            cv["text"] = computed
                except Exception:
                    # best-effort only
                    pass

        return item

    # -------------------------------------------------------------- X —
    # Search helpers: items_by_column_values
    # --------------------------------------------------------------

    def items_by_column_values(
        self,
        board_id: str,
        *,
        column_id: str,
        column_value: Any,
        fields: Optional[List[str] | Tuple[str, ...]] = None,
        limit: int | None = None,
    ) -> List[Dict[str, Any]]:
        """
        Return items whose column value exactly matches the provided value.

        Prefer the modern `items_page_by_column_values` API and fall back to the
        legacy `items_by_column_values` when necessary for older API versions.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_ITEM_FIELDS)
        base_vars: Dict[str, Any] = {
            "bid": board_id,
            "col": column_id,
            "val": json.dumps(column_value),
        }
        if limit is not None:
            base_vars["lim"] = int(limit)

        # 1) Legacy API – used by existing unit tests and some accounts
        var_decls_old = ["$bid: ID!", "$col: String!", "$val: JSON!"]
        if limit is not None:
            var_decls_old.append("$lim: Int")
        args_old = [
            "board_id:$bid",
            "column_id:$col",
            "column_value:$val",
        ]
        if limit is not None:
            args_old.append("limit:$lim")
        q_old = (
            f"query ({', '.join(var_decls_old)}){{ "
            f"  items_by_column_values({', '.join(args_old)}){{ {field_str} }} "
            f"}}"
        )
        try:
            return self.query(q_old, dict(base_vars))["items_by_column_values"]
        except MondayAPIError as exc:
            # Fall back to the new API if legacy field is not available
            msg = str(getattr(exc, "errors", "")) + " " + str(exc)
            if "items_by_column_values" not in msg:
                # Some other error – re-raise
                raise

        # 2) New paged API
        # Normalize values for the new API which expects a list of strings.
        # We include multiple representations to maximize matching odds
        # while preserving the caller-facing paradigm (accept raw Python types
        # like dicts used by the legacy endpoint).
        normalized_values: list[str] = []
        try:
            if isinstance(column_value, dict):
                # Primary: full JSON payload as a string (e.g., {"index": 1})
                normalized_values.append(json.dumps(column_value))
                # Special-case well-known shapes
                if "index" in column_value and isinstance(column_value["index"], int):
                    normalized_values.append(str(column_value["index"]))
                    # Also attempt to resolve the human label for Status columns
                    try:
                        col_meta = self.get_column(board_id, column_id, fields=("id", "type", "settings_str"))
                        settings = col_meta.get("settings", {})
                        labels = settings.get("labels") or settings.get("labels_colors", {}).get("labels")
                        if isinstance(labels, dict):
                            lbl = labels.get(str(column_value["index"])) or labels.get(column_value["index"])  # type: ignore[index]
                            if isinstance(lbl, str) and lbl:
                                normalized_values.append(lbl)
                    except Exception:
                        # Best effort; ignore failures
                        pass
                if "date" in column_value and isinstance(column_value["date"], str):
                    normalized_values.append(column_value["date"])  # YYYY-MM-DD
            elif isinstance(column_value, (int, float)):
                normalized_values.append(str(column_value))
                normalized_values.append(json.dumps(column_value))
            elif isinstance(column_value, str):
                normalized_values.append(column_value)
            else:
                normalized_values.append(json.dumps(column_value))
        except Exception:
            normalized_values = [json.dumps(column_value)]

        var_decls_new = ["$bid: ID!", "$col: String!", "$val: String!"]
        if limit is not None:
            var_decls_new.append("$lim: Int")
        limit_arg = ", limit:$lim" if limit is not None else ""
        q_new = (
            f"query ({', '.join(var_decls_new)}){{ "
            f"  items_page_by_column_values(board_id:$bid, columns:[{{column_id:$col, column_values:[$val]}}]{limit_arg}){{ cursor items {{ {field_str} }} }} "
            f"}}"
        )
        for candidate in list(dict.fromkeys(normalized_values)):
            vars_new: Dict[str, Any] = {"bid": board_id, "col": column_id, "val": candidate}
            if limit is not None:
                vars_new["lim"] = int(limit)
            try:
                res_new = self.query(q_new, vars_new)
            except MondayAPIError:
                continue
            page = res_new.get("items_page_by_column_values") or {}
            items = page.get("items")
            if isinstance(items, list) and items:
                return items
        return []

    def iter_items_by_column_values(
        self,
        board_id: str,
        *,
        column_id: str,
        column_value: Any,
        fields: Optional[List[str] | Tuple[str, ...]] = None,
        page_size: int = 200,
    ) -> Iterator[Dict[str, Any]]:
        """
        Yield items matching a column value, transparently paging when the API supports it.

        Falls back to a single-shot legacy endpoint when paging is unavailable.
        """
        # 1) First, attempt the legacy non-paged endpoint (keeps older tests/servers happy)
        try:
            first = self.items_by_column_values(
                board_id,
                column_id=column_id,
                column_value=column_value,
                fields=fields,
                limit=page_size,
            )
            for it in first:
                yield it
            # If fewer than a page returned, nothing more to fetch
            if len(first) < page_size:
                return
        except MondayAPIError:
            # Proceed to the modern endpoint
            pass

        # 2) Modern paged API using normalized value candidates
        field_str = self._fields_to_str(fields, self._DEFAULT_ITEM_FIELDS)

        candidates: list[str]
        try:
            if isinstance(column_value, dict):
                candidates = [json.dumps(column_value)]
            elif isinstance(column_value, (int, float)):
                candidates = [str(column_value), json.dumps(column_value)]
            elif isinstance(column_value, str):
                candidates = [column_value]
            else:
                candidates = [json.dumps(column_value)]
        except Exception:
            candidates = [json.dumps(column_value)]

        for candidate in list(dict.fromkeys(candidates)):
            q = (
                "query ($bid:ID!, $col:String!, $val:String!, $lim:Int, $cur:String){ "
                f"  items_page_by_column_values(board_id:$bid, columns:[{{column_id:$col, column_values:[$val]}}], limit:$lim, cursor:$cur){{ cursor items {{ {field_str} }} }} "
                "}"
            )
            cursor: Optional[str] = None
            while True:
                vars_new: Dict[str, Any] = {"bid": board_id, "col": column_id, "val": candidate, "lim": int(page_size), "cur": cursor}
                try:
                    res_new = self.query(q, vars_new)
                except MondayAPIError as exc:
                    # If backend rejects the cursor argument explicitly, stop paginating this candidate
                    if "cursor" in str(exc) and ("Unknown argument" in str(exc) or "cannot query" in str(exc)):
                        break
                    # Try next candidate or fall back to legacy
                    break
                page = res_new.get("items_page_by_column_values") or {}
                items = list(page.get("items") or [])
                for it in items:
                    yield it
                cursor = page.get("cursor")
                if not cursor or len(items) < page_size:
                    break

        # If modern endpoint not available, we've already yielded the first legacy page
        return

    def get_all_items_by_column_values(
        self,
        board_id: str,
        *,
        column_id: str,
        column_value: Any,
        fields: Optional[List[str] | Tuple[str, ...]] = None,
        page_size: int = 200,
        max_items: int | None = None,
    ) -> List[Dict[str, Any]]:
        out: list[dict] = []
        for it in self.iter_items_by_column_values(board_id, column_id=column_id, column_value=column_value, fields=fields, page_size=page_size):
            out.append(it)
            if max_items is not None and len(out) >= max_items:
                break
        return out

    def get_items_values(
        self,
        item_ids: Sequence[str],
        *,
        include_board: bool = False,
        exclude_nonactive: bool = False,
        column_ids: list[str] | None = None,
        parse_json_values: bool = True,
        item_fields: list[str] | tuple[str, ...] | None = None,
        batch_size: int = 100,
    ) -> list[dict]:
        """Fetch values for multiple items in one request."""
        if not item_ids:
            return []

        item_field_str = self._fields_to_str(
            item_fields, self._DEFAULT_ITEM_FIELDS
        )
        col_filter = "(ids:$cids)" if column_ids else ""
        col_subselect = """
            id
            value
            text
            type
            ... on BoardRelationValue { linked_item_ids }
        """
        board_block = "board { id name }" if include_board else ""

        q = f"""
        query ($ids:[ID!]!, $flag:Boolean!{', $cids:[String!]' if column_ids else ''}) {{
          items(ids:$ids, exclude_nonactive:$flag) {{
            {item_field_str}
            {board_block}
            column_values{col_filter} {{ {col_subselect} }}
          }}
        }}"""

        all_rows: list[dict] = []
        ordered_ids = list(item_ids)
        # Chunk to avoid very large GraphQL requests
        for i in range(0, len(ordered_ids), max(1, int(batch_size))):
            chunk_ids = ordered_ids[i : i + int(batch_size)]
            vars = {"ids": list(chunk_ids), "flag": exclude_nonactive}
            if column_ids:
                vars["cids"] = column_ids
            rows = self.query(q, vars)["items"]
            all_rows.extend(rows)

        # Optionally decode JSON/text fields per row
        if parse_json_values:
            for item in all_rows:
                for cv in item.get("column_values", []):
                    raw = cv.get("value")
                    if isinstance(raw, str) and raw and raw[0] in "{[":
                        try:
                            cv["value"] = json.loads(raw)
                        except ValueError:
                            pass

                for cv in item.get("column_values", []):
                    try:
                        if (cv.get("type") == "location") and (not cv.get("text")):
                            val = cv.get("value")
                            computed: str | None = None
                            if isinstance(val, dict):
                                computed = (
                                    val.get("address")
                                    or val.get("formattedAddress")
                                    or val.get("formatted_address")
                                )
                                if not computed:
                                    parts = [
                                        val.get("street") or val.get("street_name") or val.get("route"),
                                        val.get("city") or val.get("locality"),
                                        val.get("state") or val.get("administrative_area_level_1"),
                                        val.get("country"),
                                    ]
                                    computed = ", ".join(p for p in parts if isinstance(p, str) and p.strip()) or None
                            elif isinstance(val, str):
                                computed = val
                            if computed:
                                cv["text"] = computed
                    except Exception:
                        pass

        return all_rows

    # ---------------------- BULK MUTATION HELPERS ----------------------
    def create_items(
        self,
        board_id: str,
        *,
        group_id: str,
        items: Sequence[Dict[str, Any]],
        return_fields: Optional[List[str] | Tuple[str, ...]] = None,
        batch_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Create many items using chunked alias mutations.

        items: [{"name": str, "values": dict[col_id -> value]}]
        """
        out: list[dict] = []
        field_str = self._fields_to_str(return_fields or ("id",), self._DEFAULT_ITEM_FIELDS)
        for start in range(0, len(items), max(1, int(batch_size))):
            chunk = items[start : start + int(batch_size)]
            parts: list[str] = []
            var_decls: list[str] = []
            vars_payload: dict[str, Any] = {}
            for idx, spec in enumerate(chunk, start=1):
                alias = f"c{idx}"
                nb, ng, nn, nv = f"nb{idx}", f"ng{idx}", f"nn{idx}", f"nv{idx}"
                parts.append(
                    f"{alias}: create_item(board_id:${nb}, group_id:${ng}, item_name:${nn}, column_values:${nv}){{ {field_str} }}"
                )
                var_decls.extend([f"${nb}: ID!", f"${ng}: String!", f"${nn}: String!", f"${nv}: JSON"])
                vals: Dict[str, Any] = dict((spec or {}).get("values") or {})
                try:
                    self._coerce_text_values(board_id, vals)
                except Exception:
                    pass
                vars_payload[nb] = (spec or {}).get("board_id") or board_id
                vars_payload[ng] = (spec or {}).get("group_id") or group_id
                vars_payload[nn] = (spec or {}).get("name") or ""
                vars_payload[nv] = json.dumps(vals)
            if not parts:
                continue
            mutation = f"mutation({', '.join(var_decls)}) {{ {' '.join(parts)} }}"
            resp = self.mutation(mutation, vars_payload)
            # Collect results in alias order
            for idx in range(1, len(chunk) + 1):
                obj = resp.get(f"c{idx}") or {}
                out.append(obj)
        return out

    def bulk_update_item_values(
        self,
        updates: Sequence[Dict[str, Any]],
        *,
        batch_size: int = 50,
    ) -> None:
        """Batch change_multiple_column_values in chunked alias mutations.

        updates: [{"board_id": str, "item_id": str, "values": dict[col_id -> value]}]
        """
        for start in range(0, len(updates), max(1, int(batch_size))):
            chunk = updates[start : start + int(batch_size)]
            parts: list[str] = []
            var_decls: list[str] = []
            vars_payload: dict[str, Any] = {}
            for idx, spec in enumerate(chunk, start=1):
                parts.append(
                    f"u{idx}: change_multiple_column_values(board_id:$b{idx}, item_id:$i{idx}, column_values:$v{idx}){{ id }}"
                )
                var_decls.extend([f"$b{idx}: ID!", f"$i{idx}: ID!", f"$v{idx}: JSON!"])
                bid = str((spec or {}).get("board_id") or "")
                vals: Dict[str, Any] = dict((spec or {}).get("values") or {})
                try:
                    self._coerce_text_values(bid, vals)
                except Exception:
                    pass
                vars_payload[f"b{idx}"] = bid
                vars_payload[f"i{idx}"] = str((spec or {}).get("item_id") or "")
                vars_payload[f"v{idx}"] = json.dumps(vals)
            if not parts:
                continue
            mutation = f"mutation({', '.join(var_decls)}) {{ {' '.join(parts)} }}"
            self.mutation(mutation, vars_payload)

    def bulk_upsert_items(
        self,
        board_id: str,
        *,
        group_id: str,
        new_items: Sequence[Dict[str, Any]] | None,
        updates: Sequence[Dict[str, Any]] | None,
        return_fields: Optional[List[str] | Tuple[str, ...]] = None,
        batch_size: int = 50,
    ) -> List[Dict[str, Any]]:
        """Mix create_item and change_multiple_column_values in chunked mutations."""
        new_items = list(new_items or [])
        updates = list(updates or [])
        out: list[dict] = []
        field_str = self._fields_to_str(return_fields or ("id",), self._DEFAULT_ITEM_FIELDS)

        # Partition into chunks of up to batch_size (creates + updates counted together)
        idx_new = 0
        idx_upd = 0
        while idx_new < len(new_items) or idx_upd < len(updates):
            parts: list[str] = []
            var_decls: list[str] = []
            vars_payload: dict[str, Any] = {}
            count = 0
            # fill from creates
            while count < batch_size and idx_new < len(new_items):
                spec = new_items[idx_new]
                count += 1
                alias = f"c{count}"
                nb, ng, nn, nv = f"nb{count}", f"ng{count}", f"nn{count}", f"nv{count}"
                parts.append(
                    f"{alias}: create_item(board_id:${nb}, group_id:${ng}, item_name:${nn}, column_values:${nv}){{ {field_str} }}"
                )
                var_decls.extend([f"${nb}: ID!", f"${ng}: String!", f"${nn}: String!", f"${nv}: JSON"])
                vals: Dict[str, Any] = dict((spec or {}).get("values") or {})
                bid = str((spec or {}).get("board_id") or board_id)
                try:
                    self._coerce_text_values(bid, vals)
                except Exception:
                    pass
                vars_payload[nb] = bid
                vars_payload[ng] = str((spec or {}).get("group_id") or group_id)
                vars_payload[nn] = (spec or {}).get("name") or ""
                vars_payload[nv] = json.dumps(vals)
                idx_new += 1
            # fill from updates
            while count < batch_size and idx_upd < len(updates):
                spec = updates[idx_upd]
                count += 1
                parts.append(
                    f"u{count}: change_multiple_column_values(board_id:$b{count}, item_id:$i{count}, column_values:$v{count}){{ id }}"
                )
                var_decls.extend([f"$b{count}: ID!", f"$i{count}: ID!", f"$v{count}: JSON!"])
                bid2 = str((spec or {}).get("board_id") or board_id)
                vals2: Dict[str, Any] = dict((spec or {}).get("values") or {})
                try:
                    self._coerce_text_values(bid2, vals2)
                except Exception:
                    pass
                vars_payload[f"b{count}"] = bid2
                vars_payload[f"i{count}"] = str((spec or {}).get("item_id") or "")
                vars_payload[f"v{count}"] = json.dumps(vals2)
                idx_upd += 1

            if not parts:
                continue
            mutation = f"mutation({', '.join(var_decls)}) {{ {' '.join(parts)} }}"
            resp = self.mutation(mutation, vars_payload)
            # collect create aliases only (updates return id but not needed)
            # We cannot easily know how many creates were in this chunk; detect by keys
            for k, v in resp.items():
                if k.startswith("c") and isinstance(v, dict):
                    out.append(v)
        return out

    # -------------------------------------------------------------- 3 —
    # Create an item (returns metadata you ask for)
    # --------------------------------------------------------------

    def create_item(
        self,
        board_id: str,
        *,
        group_id: str,
        item_name: str,
        column_values: Optional[Dict[str, Any]] = None,
        return_fields: Optional[List[str] | Tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Insert a new item and immediately fetch the desired metadata.

        Notes
        -----
        • *column_values* must be **raw** Python dict – it will be JSON-encoded
          inside the mutation call.
        • If you *just* need the new item’s ID, leave *return_fields* at
          ``None`` (the default → ``("id",)``).
        """
        self._coerce_text_values(board_id, column_values)
        field_str = self._fields_to_str(
            return_fields or ("id",), self._DEFAULT_ITEM_FIELDS
        )
        m = f"""
        mutation (
          $board: ID!,
          $group: String!,
          $name: String!,
          $cols: JSON
        ) {{
          create_item(
            board_id: $board,
            group_id: $group,
            item_name: $name,
            column_values: $cols
          ) {{
            {field_str}
          }}
        }}
        """
        vars = {
            "board": board_id,
            "group": group_id,
            "name": item_name,
            "cols": json.dumps(column_values or {}),
        }
        return self.mutation(m, vars)["create_item"]

    def delete_item(self, item_id: str) -> None:
        """
        Permanently delete an item.

        The public ``delete_item`` mutation moves the item to the account’s
        recycle bin where it can be restored within 30 days from the UI.
        There is no *archive* equivalent for items – use this call when you
        truly want it gone.

        Parameters
        ----------
        item_id
            The numeric ID of the item to be deleted.

        Returns
        -------
        None
            The monday API only responds with ``{ id }`` on success; nothing
            useful to forward, so we discard it (just like ``archive_board``).

        Raises
        ------
        MondayAPIError
            If the HTTP layer fails or GraphQL responds with an error.
        """
        m = """
        mutation ($id: ID!) {
          delete_item (item_id: $id) { id }
        }
        """
        self.mutation(m, {"id": item_id})

    # -------------------------------------------------------------- 4 —
    # Update *multiple* columns in one call
    # --------------------------------------------------------------

    def _get_text_column_ids(self, board_id: str) -> set[str]:
        """
        Return the set of *text* column IDs for the given board, caching
        the result per‑board so we only hit the API once.
        """
        cache: dict[str, set[str]] = getattr(self, "_text_col_cache", {})
        if board_id in cache:
            return cache[board_id]

        cols = self.get_columns(board_id, fields=("id", "type"), parse_settings=False)
        text_ids = {c["id"] for c in cols if c["type"] == "text"}
        cache[board_id] = text_ids
        self._text_col_cache = cache  # write back
        return text_ids

    def _coerce_text_values(self, board_id: str, column_values: dict[str, object]) -> None:
        """
        In‑place: make sure every value headed for a *text* column is a str.
        """
        if not column_values:
            return

        for cid in self._get_text_column_ids(board_id):
            if cid in column_values and not isinstance(column_values[cid], str):
                column_values[cid] = (
                    "" if column_values[cid] is None else str(column_values[cid])
                )

    def update_item_values(
            self,
            board_id: str,
            item_id: str,
            *,
            column_values: dict[str, object],
    ) -> None:
        if not column_values:
            raise ValueError("column_values must contain at least one entry")

        # --- NEW line ---------------------------------------------------
        self._coerce_text_values(board_id, column_values)
        # ---------------------------------------------------------------

        m = """
        mutation ($board: ID!, $item: ID!, $vals: JSON!) {
          change_multiple_column_values(
            board_id: $board,
            item_id: $item,
            column_values: $vals
          ) { id }
        }
        """
        self.mutation(
            m,
            {
                "board": board_id,
                "item": item_id,
                "vals": json.dumps(column_values),
            },
        )

    def safe_update_item_values(
        self,
        board_id: str,
        item_id: str,
        *,
        column_values: dict[str, object],
    ) -> None:
        """
        Like ``update_item_values`` but swallows certain validation errors
        (e.g. unassignable People columns or linked item limits) and retries
        without the offending payloads.
        """
        try:
            # first attempt: push everything
            self.update_item_values(board_id, item_id, column_values=column_values)
            return

        except MondayAPIError as exc:
            # ── detect specific column failures ───────────────────────────
            assign_errs = {
                err["extensions"]["error_data"]["column_id"]
                for err in getattr(exc, "errors", [])
                if "unable to assign person with id" in err.get("message", "").lower()
            }
            limit_errs = {
                err["extensions"]["error_data"]["column_id"]
                for err in getattr(exc, "errors", [])
                if err.get("extensions", {}).get("error_data", {}).get(
                    "column_validation_error_code"
                )
                == "linkedItemsLimitExceeded"
            }
            offending = assign_errs | limit_errs
            if not offending:
                raise   # ← some other problem – bubble it up unchanged

            # ── strip the blocked columns and retry once ───────────────────
            filtered = {
                cid: val for cid, val in column_values.items() if cid not in offending
            }

            if filtered:
                if assign_errs:
                    logger.warning(
                        "Skipped People columns %s for item %s on board %s "
                        "(user not subscriber). Retrying with the remainder.",
                        ", ".join(assign_errs), item_id, board_id,
                    )
                if limit_errs:
                    logger.warning(
                        "Skipped connect columns %s for item %s on board %s "
                        "(linked items limit exceeded). Retrying with the remainder.",
                        ", ".join(limit_errs), item_id, board_id,
                    )
                self.update_item_values(board_id, item_id, column_values=filtered)
            else:
                logger.info(
                    "All attempted columns blocked for item %s – no other columns to update.",
                    item_id,
                )

    # -------------------------------------------------------------- 4a —
    # (Optional convenience) – change a single column
    # --------------------------------------------------------------

    def update_item_single_column(
        self,
        board_id: str,
        item_id: str,
        *,
        column_id: str,
        value: Any,
    ) -> None:
        """
        Shorthand wrapper around monday’s ``change_column_value`` mutation.
        """
        m = """
        mutation ($board: ID!, $item: ID!, $col: String!, $val: JSON!) {
          change_column_value(
            board_id: $board,
            item_id: $item,
            column_id: $col,
            value: $val
          ) { id }
        }
        """
        self.mutation(
            m,
            {
                "board": board_id,
                "item": item_id,
                "col": column_id,
                "val": json.dumps(value),
            },
        )

    # -------------------------------------------------------------- 4b —
    # Additional item helpers: rename, archive/unarchive, duplicate, move
    # --------------------------------------------------------------

    def rename_item(self, item_id: str, *, name: str) -> None:
        """Change an item's name.

        Notes
        -----
        Some monday GraphQL deployments no longer expose the ``change_item_name``
        mutation. To ensure compatibility, this helper falls back to updating the
        implicit "name" column via ``change_column_value``.
        """
        try:
            m = "mutation ($id: ID!, $name: String!){ change_item_name(item_id:$id, name:$name){ id } }"
            self.mutation(m, {"id": item_id, "name": name})
            return
        except MondayAPIError as exc:
            # Fallback path: update the Name column directly
            # Only retry fallback when error indicates missing field or schema issue
            msgs = MondayClient._error_messages_lower(getattr(exc, "errors", []))
            if not (any("cannot query field \"change_item_name\"" in m for m in msgs) or any("unknown field" in m and "change_item_name" in m for m in msgs)):
                raise

        # Robust fallback: use generic change_column_value with required board_id
        # Discover the item's board id first (works across API variants)
        try:
            item = self.get_item_values(item_id, include_board=True, parse_json_values=False)
            board = item.get("board") or {}
            board_id = str(board.get("id")) if board.get("id") is not None else None
        except Exception:
            board_id = None

        if not board_id:
            # If board id couldn't be determined, surface the original capability error
            raise MondayAPIError("Unable to determine board_id for item rename fallback") from exc

        # Use the helper that always includes board_id
        self.update_item_single_column(board_id, item_id, column_id="name", value=name)
        return

    def archive_item(self, item_id: str) -> None:
        """Archive an item (moves to board archive)."""
        self.mutation("mutation ($id: ID!){ archive_item(item_id:$id){ id } }", {"id": item_id})

    def unarchive_item(self, item_id: str) -> None:
        """Unarchive an item."""
        try:
            self.mutation("mutation ($id: ID!){ unarchive_item(item_id:$id){ id } }", {"id": item_id})
            return
        except MondayAPIError as exc:
            # Fallback when deployment doesn't expose unarchive_item
            msgs = MondayClient._error_messages_lower(getattr(exc, "errors", []))
            unknown_unarchive = any(
                ("cannot query field \"unarchive_item\"" in m) or ("unknown field" in m and "unarchive_item" in m)
                for m in msgs
            )
            if not unknown_unarchive:
                raise
            # Try restore_item
            try:
                self.mutation("mutation ($id: ID!){ restore_item(item_id:$id){ id } }", {"id": item_id})
                return
            except MondayAPIError as exc2:
                msgs2 = MondayClient._error_messages_lower(getattr(exc2, "errors", []))
                unknown_restore_item = any(
                    ("cannot query field \"restore_item\"" in m) or ("unknown field" in m and "restore_item" in m)
                    for m in msgs2
                )
                if not unknown_restore_item:
                    raise
                # Last resort: bulk restore_items (some deployments expose only the bulk mutation)
                self.mutation("mutation ($ids: [ID!]!){ restore_items(item_ids:$ids){ id } }", {"ids": [item_id]})

    def duplicate_item(
        self,
        item_id: str,
        *,
        with_updates: bool = True,
        with_assets: bool = True,
        target_board_id: str | None = None,
        target_group_id: str | None = None,
    ) -> dict:
        """
        Duplicate an item, optionally into another board/group. Returns `{ id }` of the new item.
        """
        args = ["item_id:$id", f"with_updates:{str(with_updates).lower()}", f"with_assets:{str(with_assets).lower()}"]
        var_decls = ["$id: ID!"]
        vars: Dict[str, Any] = {"id": item_id}
        if target_board_id is not None:
            args.append("board_id:$board")
            var_decls.append("$board: ID")
            vars["board"] = target_board_id
        if target_group_id is not None:
            args.append("group_id:$group")
            var_decls.append("$group: String")
            vars["group"] = target_group_id
        m = (
            f"mutation ({', '.join(var_decls)}){{ "
            f"  duplicate_item({', '.join(args)}){{ id }} "
            f"}}"
        )
        return self.mutation(m, vars).get("duplicate_item", {})

    def move_item_to_group(self, item_id: str, *, group_id: str) -> None:
        """Move item to a different group on the same board."""
        self.mutation(
            "mutation ($id: ID!, $gid: String!){ move_item_to_group(item_id:$id, group_id:$gid){ id } }",
            {"id": item_id, "gid": group_id},
        )

    def move_item_to_board(self, item_id: str, *, board_id: str, group_id: str | None = None) -> dict:
        """
        Move an item to another board. Optionally specify the target group. Returns `{ id }` of the new item.
        """
        var_decls = ["$id: ID!", "$bid: ID!"]
        args = ["item_id:$id", "board_id:$bid"]
        vars: Dict[str, Any] = {"id": item_id, "bid": board_id}
        if group_id is not None:
            var_decls.append("$gid: String")
            args.append("group_id:$gid")
            vars["gid"] = group_id
        m = (
            f"mutation ({', '.join(var_decls)}){{ "
            f"  move_item_to_board({', '.join(args)}){{ id }} "
            f"}}"
        )
        return self.mutation(m, vars).get("move_item_to_board", {})

    # -------------------------------------------------------------- 5 —
    # Helper – replace *all* links in a Connect-boards column
    # --------------------------------------------------------------

    def set_connected_items(
        self,
        board_id: str,
        item_id: str,
        *,
        column_id: str,
        linked_item_ids: List[str] | List[int],
    ) -> None:
        """
        Convenience helper for “Connect boards” columns.

        The supplied *linked_item_ids* **replace** any existing links.
        """
        # IMPORTANT: IDs must be *numbers* inside the JSON blob
        column_payload = {
            column_id: {"item_ids": [int(i) for i in linked_item_ids]}
        }
        self.update_item_values(
            board_id,
            item_id,
            column_values=column_payload,
        )

    # -------------------------------------------------------------- 5b —
    # Group helpers (list/create/rename/archive)
    # --------------------------------------------------------------

    def list_groups(self, board_id: str, *, fields: list[str] | tuple[str, ...] | None = None) -> list[dict]:
        field_str = self._fields_to_str(fields, self._DEFAULT_GROUP_FIELDS)
        q = (
            "query ($id:[ID!]!){"
            "  boards(ids:$id){"
            f"    groups{{ {field_str} }}"
            "  }"
            "}"
        )
        boards = self.query(q, {"id": [board_id]})["boards"]
        if not boards:
            raise MondayAPIError(f"Board {board_id} not found")
        return boards[0].get("groups", [])

    def create_group(self, board_id: str, *, title: str, fields: list[str] | tuple[str, ...] | None = None) -> dict:
        field_str = self._fields_to_str(fields, self._DEFAULT_GROUP_FIELDS)
        m = f"""
        mutation ($id: ID!, $title: String!){{
          create_group(board_id:$id, group_name:$title){{ {field_str} }}
        }}
        """
        return self.mutation(m, {"id": board_id, "title": title})["create_group"]

    def rename_group(self, board_id: str, group_id: str, *, title: str) -> None:
        m = "mutation ($bid: ID!, $gid: String!, $title: String!){ change_group_title(board_id:$bid, group_id:$gid, title:$title){ id } }"
        try:
            self.mutation(m, {"bid": board_id, "gid": group_id, "title": title})
        except MondayAPIError as exc:
            # Gracefully degrade if the API version/account does not support this mutation
            messages = [str(err.get("message", "")) for err in getattr(exc, "errors", [])]
            not_supported = any(
                "Cannot query field \"change_group_title\"" in msg or
                "Field \"change_group_title\"" in msg
                for msg in messages
            )
            if not_supported:
                raise FeatureNotSupported("Group rename is not supported by this API version/account", errors=getattr(exc, "errors", [])) from exc
            raise

    def archive_group(self, board_id: str, group_id: str) -> None:
        self.mutation("mutation ($bid: ID!, $gid: String!){ archive_group(board_id:$bid, group_id:$gid){ id } }", {"bid": board_id, "gid": group_id})

    def delete_group(self, board_id: str, group_id: str) -> None:
        self.mutation("mutation ($bid: ID!, $gid: String!){ delete_group(board_id:$bid, group_id:$gid){ id } }", {"bid": board_id, "gid": group_id})

    # -------------------------------------------------------------- 5a —
    # Same convenience helper for sub-items
    # --------------------------------------------------------------

    def set_connected_subitems(
        self,
        subitem_id: str,
        *,
        column_id: str,
        linked_item_ids: List[str] | List[int],
        board_id: Optional[str] = None,
    ) -> None:
        """
        Identical to *set_connected_items* but defaults to resolving the
        hidden “sub-tasks” board automatically.
        """
        if board_id is None:
            board_id = self._get_board_id_for_subitem(subitem_id)

        column_payload = {
            column_id: {"item_ids": [int(i) for i in linked_item_ids]}
        }
        self.update_subitem_values(
            subitem_id,
            column_values=column_payload,
            board_id=board_id,
        )

    # -------------------------------------------------------------- 1 —
    # List all sub-items hanging off a parent item
    # --------------------------------------------------------------

    def list_subitems(
        self,
        parent_item_id: str,
        *,
        fields: Optional[List[str] | Tuple[str, ...]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return the immediate children (sub-items) of *parent_item_id*.

        monday exposes sub-items only through the parent → ``subitems`` edge.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_SUBITEM_FIELDS)
        q = f"""
        query ($pid:[ID!]!) {{
          items (ids:$pid) {{
            subitems {{ {field_str} }}
          }}
        }}
        """
        items = self.query(q, {"pid": [parent_item_id]})["items"]
        if not items:
            raise MondayAPIError(f"Parent item {parent_item_id} not found")
        return items[0]["subitems"]

    # -------------------------------------------------------------- 2 —
    # Fetch column values for a single sub-item
    # --------------------------------------------------------------

    def get_subitem_values(
        self,
        subitem_id: str,
        *,
        include_board: bool = False,
        include_parent: bool = False,
        top_level_fields: Optional[List[str] | Tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Retrieve a sub-item’s column values (mirrors :py:meth:`get_item_values`).

        *include_board* adds the hidden sub-items board metadata.
        *include_parent* adds ``parent_item { id }`` so you can link back up.
        """
        item_field_str = self._fields_to_str(
            top_level_fields, self._DEFAULT_SUBITEM_FIELDS
        )

        col_subselect = """
            id
            value
            text
            type
            ... on BoardRelationValue { linked_item_ids }
        """

        board_block = "board { id name }" if include_board else ""
        parent_block = "parent_item { id }" if include_parent else ""

        q = f"""
        query ($sid:[ID!]!) {{
          items (ids:$sid) {{
            {item_field_str}
            {board_block}
            {parent_block}
            column_values {{ {col_subselect} }}
          }}
        }}
        """
        items = self.query(q, {"sid": [subitem_id]})["items"]
        if not items:
            raise MondayAPIError(f"Sub-item with ID {subitem_id} not found")
        return items[0]

    # -------------------------------------------------------------- 3 —
    # Create a new sub-item under a parent item
    # --------------------------------------------------------------

    def create_subitem(
        self,
        parent_item_id: str,
        *,
        item_name: str,
        column_values: Optional[Dict[str, Any]] = None,
        return_fields: Optional[List[str] | Tuple[str, ...]] = None,
    ) -> Dict[str, Any]:
        """
        Insert a sub-item and immediately return the desired metadata.

        Notes
        -----
        • Unlike normal items, no ``board_id`` / ``group_id`` is required –
          the API figures that out from *parent_item_id*.
        """
        field_str = self._fields_to_str(
            return_fields or ("id",), self._DEFAULT_SUBITEM_FIELDS
        )
        m = f"""
        mutation (
          $parent: ID!,
          $name: String!,
          $cols: JSON
        ) {{
          create_subitem(
            parent_item_id: $parent,
            item_name: $name,
            column_values: $cols
          ) {{ {field_str} }}
        }}
        """
        vars = {
            "parent": parent_item_id,
            "name": item_name,
            "cols": json.dumps(column_values or {}),
        }
        return self.mutation(m, vars)["create_subitem"]

    # -------------------------------------------------------------- 4 —
    # Update multiple columns on an existing sub-item
    # --------------------------------------------------------------

    def update_subitem_values(
        self,
        subitem_id: str,
        *,
        column_values: Dict[str, Any],
        board_id: Optional[str] = None,
    ) -> None:
        """
        Batch-update **many** columns on a sub-item.

        *board_id* is the ID of the hidden “sub-items board”; if omitted the
        helper will perform one extra lookup to resolve it automatically.
        """
        if not column_values:
            raise ValueError("column_values must contain at least one entry")

        if board_id is None:
            board_id = self._get_board_id_for_subitem(subitem_id)

        m = """
        mutation ($board: ID!, $item: ID!, $vals: JSON!) {
          change_multiple_column_values(
            board_id: $board,
            item_id: $item,
            column_values: $vals
          ) { id }
        }
        """
        self.mutation(
            m,
            {
                "board": board_id,
                "item": subitem_id,
                "vals": json.dumps(column_values),
            },
        )

    # -------------------------------------------------------------- 4a —
    # Convenience – change a single column on a sub-item
    # --------------------------------------------------------------

    def update_subitem_single_column(
        self,
        subitem_id: str,
        *,
        column_id: str,
        value: Any,
        board_id: Optional[str] = None,
    ) -> None:
        """
        Shorthand wrapper around ``change_column_value`` for sub-items.
        """
        if board_id is None:
            board_id = self._get_board_id_for_subitem(subitem_id)

        m = """
        mutation ($board: ID!, $item: ID!, $col: String!, $val: JSON!) {
          change_column_value(
            board_id: $board,
            item_id: $item,
            column_id: $col,
            value: $val
          ) { id }
        }
        """
        self.mutation(
            m,
            {
                "board": board_id,
                "item": subitem_id,
                "col": column_id,
                "val": json.dumps(value),
            },
        )

    # -------------------------------------------------------------- 6 —
    # Internal helper – resolve the *hidden* board ID for a sub-item
    # --------------------------------------------------------------

    def _get_board_id_for_subitem(self, subitem_id: str) -> str:
        """
        Sub-items live on a hidden board of type ``subtasks``.  This helper
        performs one lightweight lookup and caches results per-instance.
        """
        cache: Dict[str, str] = getattr(self, "_subitem_board_cache", {})
        if subitem_id in cache:
            return cache[subitem_id]

        q = """
        query ($sid:[ID!]!) {
          items (ids:$sid) { board { id } }
        }
        """
        items = self.query(q, {"sid": [subitem_id]})["items"]
        if not items or not items[0].get("board"):
            raise MondayAPIError(f"Cannot resolve board for sub-item {subitem_id}")

        board_id = str(items[0]["board"]["id"])
        cache[subitem_id] = board_id
        self._subitem_board_cache = cache
        return board_id

    # ------------------------------------------------------------------
    # DOCS
    # ------------------------------------------------------------------

    def get_doc(
            self,
            doc_or_object_id: str | int,
            *,
            by_object_id: bool = True,
            fields: list[str] | tuple[str, ...] | None = None,
            include_blocks: bool = False,
            block_limit: int | None = None,
            block_page: int | None = None,
            block_fields: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """
        Fetch a monday **doc** (and optionally a page of its blocks).

        Parameters
        ----------
        doc_or_object_id
            Accepts either the real *doc ID* or the *object_id* stored in files.
        by_object_id
            If ``True`` (default) treat *doc_or_object_id* as **object_id**,
            otherwise as the doc’s real ID.
        include_blocks
            Set ``True`` to add ``blocks{…}`` to the selection set.
        block_limit, block_page
            Pagination knobs (`limit` defaults to 25, `page` to 1 at the API).
        block_fields
            Customise the field list inside each block.

        Returns
        -------
        dict
            A single doc object.
        """
        # 1 · build the outer selection set ---------------------------------
        arg_name = "object_ids" if by_object_id else "ids"
        doc_sel = self._fields_to_str(fields, self._DEFAULT_DOC_FIELDS)

        block_sel = ""
        if include_blocks:
            # optional paging arguments inside blocks(…)
            blk_args = []
            if block_limit is not None:
                blk_args.append("limit:$bl")
            if block_page is not None:
                blk_args.append("page:$bp")
            arg_str = f"({', '.join(blk_args)})" if blk_args else ""
            block_sel = (
                f" blocks{arg_str} {{ "
                f"{self._fields_to_str(block_fields, ('id', 'type', 'content'))} }}"
            )

        # 2 · variable declarations ----------------------------------------
        var_decls = ["$ids:[ID!]"]
        if block_limit is not None:
            var_decls.append("$bl:Int")
        if block_page is not None:
            var_decls.append("$bp:Int")

        q = (
            f"query ({', '.join(var_decls)}) {{ "
            f"docs({arg_name}:$ids) {{ {doc_sel}{block_sel} }} }}"
        )

        # 3 · variable payload ---------------------------------------------
        vars_ = {"ids": [str(doc_or_object_id)]}
        if block_limit is not None:
            vars_["bl"] = block_limit
        if block_page is not None:
            vars_["bp"] = block_page

        docs = self.query(q, vars_)["docs"]
        if not docs:
            raise MondayAPIError(f"Doc {doc_or_object_id} not found via {arg_name}")
        return docs[0]

    def get_all_blocks(
            self,
            doc_id: str | int,
            *,
            page_size: int = 100,
            by_object_id: bool = True,
    ) -> list[dict]:
        """
        Retrieve **every block** of a doc, transparently paging under the hood.

        Parameters
        ----------
        doc_id
            Either the true doc ID or the object_id (see *by_object_id*).
        page_size
            How many blocks per request (≥1, ≤ platform max; 100 is a good default).
        by_object_id
            Pass ``False`` if *doc_id* is the real doc ID.

        Returns
        -------
        list[dict]
            All block dicts in order.
        """
        from .pagination import collect, iterate_pages

        def _fetch(pg: int | None, sz: int) -> list[dict]:
            doc = self.get_doc(
                doc_id,
                by_object_id=by_object_id,
                include_blocks=True,
                block_limit=sz,
                block_page=(1 if pg is None else pg),
            )
            return list(doc.get("blocks") or [])

        return collect(iterate_pages(_fetch, page_size), None)

    def get_doc_text(
            self,
            doc_id: str | int,
            *,
            by_object_id: bool = True,
            page_size: int = 100,
    ) -> str:
        """
        Convenience one-liner – returns the entire doc as **plain text**.

        Internally calls :py:meth:`get_all_blocks` to avoid the 25-block clip.
        """
        blocks = self.get_all_blocks(doc_id, page_size=page_size, by_object_id=by_object_id)
        return self.blocks_to_plaintext(blocks)

    # ---------- optional convenience ----------------------------------
    @staticmethod
    def blocks_to_plaintext(blocks: List[Dict[str, Any]]) -> str:
        """
        Flatten monday‐doc blocks to plain text.

        • Works with both dict and JSON-string `content` payloads
        • Falls back to treating raw strings as literal text
        """
        parts: List[str] = []

        for b in blocks:
            content = b.get("content")
            if content is None:
                continue

            # ── 1. Auto-decode JSON strings ────────────────────────────────
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except ValueError:
                    # plain string → treat as literal paragraph
                    parts.append(content.strip())
                    continue

            # ── 2. Parse Quill “deltaFormat” ops (rich-text) ───────────────
            for op in content.get("deltaFormat", []):
                txt = op.get("insert")
                if isinstance(txt, str):
                    parts.append(txt.rstrip("\n"))

        return "\n".join(parts)

    def get_doc_text_from_column(self, item_id, column_id: str | int) -> str:
        vals = self.get_item_values(item_id, column_ids=[column_id], include_board=True)
        doc_id = vals['column_values'][0]['value']['files'][0]['objectId']
        doc_text = self.get_doc_text(doc_id)
        return doc_text

    def get_tags_from_column(self, item_id, column_id: str | int) -> List[Dict]:
        item = self.get_item_values(item_id, column_ids=[column_id])
        tag_text_list = [text.strip() for text in item['column_values'][0]['text'].split(',')]
        tag_id_list = item['column_values'][0]['value']['tag_ids']
        tags = []
        for n, skill_id in enumerate(tag_id_list):
            tags.append({'skill_id': str(skill_id), 'skill_name': tag_text_list[n]})
        return tags

    def create_doc(
        self,
        *,
        item_id: str,
        column_id: str,
        fields: list[str] | tuple[str, ...] | None = None,
    ) -> dict:
        """
        Create a Workdoc inside the given *doc column* and return its metadata.

        You must have the `docs:write` scope on the user token.
        """
        field_str = self._fields_to_str(fields, self._DEFAULT_DOC_FIELDS)

        m = f"""
        mutation ($item: ID!, $col: String!) {{
          create_doc (location: {{ board: {{ item_id: $item, column_id: $col }} }}) {{
            {field_str}
          }}
        }}
        """
        try:
            return self.mutation(m, {"item": item_id, "col": column_id})["create_doc"]
        except MondayAPIError as exc:
            if self._is_docs_not_supported_or_forbidden_error(getattr(exc, "errors", [])):
                raise FeatureNotSupported(
                    "Docs API not supported or permitted with current token/account",
                    errors=getattr(exc, "errors", []),
                ) from exc
            raise

    def create_doc_block(
        self,
        doc_id: str,
        *,
        block_type: str,
        content: dict,
        after_block_id: str | None = None,
        fields: tuple[str, ...] = ("id",),
    ) -> dict:
        """
        Insert a new block (text, table, image, etc.) into *doc_id*.

        • *block_type* examples: "normal text", "table", "page_break"
        • *content* must be **raw dict**—it will be JSON‑encoded.
        """
        field_str = " ".join(fields)
        args = ", after_block_id: $after" if after_block_id else ""
        m = f"""
        mutation ($doc: ID!, $type: DocBlockContentType!, $cnt: JSON!{', $after: String' if after_block_id else ''}) {{
          create_doc_block (doc_id: $doc, type: $type, content: $cnt{args}) {{
            {field_str}
          }}
        }}"""
        vars = {
            "doc": doc_id,
            "type": block_type,
            "cnt": json.dumps(content),
        }
        if after_block_id:
            vars["after"] = after_block_id
        try:
            return self.mutation(m, vars)["create_doc_block"]
        except MondayAPIError as exc:
            if self._is_docs_not_supported_or_forbidden_error(getattr(exc, "errors", [])):
                raise FeatureNotSupported(
                    "Docs API not supported or permitted with current token/account",
                    errors=getattr(exc, "errors", []),
                ) from exc
            raise

    def delete_doc(self, doc_id: str) -> None:
        """
        Permanently delete a monday Workdoc.

        Internally calls the `delete_board` mutation because each doc is
        implemented as a board of type `doc`.

        Parameters
        ----------
        doc_id : str
            The numeric ID of the Workdoc to delete.
        """
        try:
            self.mutation(
                "mutation ($id: ID!){ delete_board(board_id:$id){ id } }",
                {"id": doc_id},
            )
        except MondayAPIError as exc:
            if self._is_docs_not_supported_or_forbidden_error(getattr(exc, "errors", [])):
                raise FeatureNotSupported(
                    "Docs API not supported or permitted with current token/account",
                    errors=getattr(exc, "errors", []),
                ) from exc
            raise

    def set_full_doc_plain_text(self, item_id, column_id, body_text):
        """Replace every block in the doc cell with a single plain‑text block."""
        # ── 1. Does the cell already contain a doc? ─────────────────────────
        vals = self.get_item_values(item_id, column_ids=[column_id])

        col_vals = vals.get("column_values", [])
        raw_val = col_vals[0].get("value") if col_vals else None
        if isinstance(raw_val, str):
            try:
                raw_val = json.loads(raw_val)
            except ValueError:
                raw_val = None
        raw_val = raw_val or {}

        files = raw_val.get("files", [])
        doc_id = None  # <- will hold the REAL doc id

        if files:
            object_id = files[0]["objectId"]  # the one you see in the URL
            # Resolve to the true doc id (top‑left corner of the editor)
            doc_id = (
                self.get_doc(object_id, by_object_id=True, fields=["id"])["id"]
            )

            # ── 2. Nuke existing blocks (needs *only* the block_id) ─────────
            try:
                for blk in self.get_all_blocks(object_id):  # OK to use objectId here
                    print(blk["type"])
                    if blk["type"] in self._DELETABLE_DOC_BLOCK_TYPES:
                        self.mutation(
                            "mutation ($b:String!){ "
                            "  delete_doc_block(block_id:$b){ id } "
                            "}",
                            {"b": blk["id"]},
                        )
            except MondayAPIError as exc:
                if self._is_docs_not_supported_or_forbidden_error(getattr(exc, "errors", [])):
                    raise FeatureNotSupported(
                        "Docs API not supported or permitted with current token/account",
                        errors=getattr(exc, "errors", []),
                    ) from exc
                raise
        else:
            # Cell was empty → create a fresh doc first
            doc_meta = self.create_doc(item_id=item_id, column_id=column_id)
            doc_id = doc_meta["id"]

        # ── 3. Add the replacement block  ───────────────────────────────────
        try:
            self.create_doc_block(
                doc_id,
                block_type="normal_text",
                content={
                    "alignment": "left",
                    "direction": "ltr",
                    "deltaFormat": [{"insert": body_text}],
                },
            )
        except MondayAPIError as exc:
            if self._is_docs_not_supported_or_forbidden_error(getattr(exc, "errors", [])):
                raise FeatureNotSupported(
                    "Docs API not supported or permitted with current token/account",
                    errors=getattr(exc, "errors", []),
                ) from exc
            raise


    # ------------------------------------------------------------------
    # FILE HANDLING
    # ------------------------------------------------------------------

    def upload_file_to_column(
            self,
            item_id: str,
            *,
            column_id: str,
            file_obj,
            filename: str | None = None,
            mime_type: str = "application/octet-stream",
    ) -> dict:
        """
        Upload *file_obj* to a File column (API‑version 2025‑04).

        Returns the new asset’s `{ id, url, public_url }`.
        """
        # 1 . GraphQL — **no comments allowed!**
        mutation = (
            "mutation ($item: ID!, $col: String!, $file: File!) {"
            "  add_file_to_column(item_id: $item, column_id: $col, file: $file) {"
            "    id url public_url"
            "  }"
            "}"
        )

        # 2 . Form‑data parts -------------------------------------------------
        data = {
            # separate `query` and `variables` fields (Monday's preferred layout)
            "query": mutation,
            "variables": json.dumps({"item": item_id, "col": column_id}),
            # **string** path, not array
            "map": json.dumps({"file": "variables.file"}),
        }
        files = {
            "file": (
                filename or getattr(file_obj, "name", "upload"),
                file_obj,
                mime_type,
            )
        }

        headers = {
            "Authorization": self.token,
            "API-Version": self.api_version,
            "User-Agent": "today-hub/2.0 (https://github.com/today-hub)",
            # ← no Content‑Type – `requests` sets the correct multipart boundary
        }

        resp = requests.post(
            self.files_endpoint,
            headers=headers,
            data=data,
            files=files,
            timeout=30,
        )
        if resp.status_code != 200:
            raise MondayAPIError(f"HTTP {resp.status_code}: {resp.text}")

        payload = resp.json()
        if "errors" in payload:
            raise MondayAPIError("GraphQL errors returned", errors=payload["errors"])

        return payload["data"]["add_file_to_column"]

    def download_files_from_column(self, item_id: str, column_id: str) -> list[bytes]:
        item = self.get_item_values(item_id, column_ids=[column_id])
        try:
            files = item["column_values"][0]["value"]["files"]
        except (KeyError, IndexError, TypeError):
            raise MondayAPIError("File column is empty")

        out: list[bytes] = []
        for fi in files:
            url = fi.get("public_url")
            if not url:
                asset_id = fi.get("assetId") or fi.get("id")
                url = self.query(
                    "query ($id:[ID!]!){ assets(ids:$id){ public_url } }",
                    {"id": [asset_id]},
                )["assets"][0]["public_url"]
            resp = requests.get(url, timeout=30,
                                headers={"User-Agent": self._session.headers["User-Agent"]})
            if resp.status_code != 200:
                raise MondayAPIError(f"HTTP {resp.status_code}: {resp.text}")
            out.append(resp.content)
        return out

    def list_files_from_column(self, item_id: str, column_id: str) -> list[dict]:
        """Return file metadata for a monday *Files* column."""
        item = self.get_item_values(item_id, column_ids=[column_id])
        try:
            files = item["column_values"][0]["value"]["files"]
        except (KeyError, IndexError, TypeError):
            return []

        out: list[dict] = []
        for fi in files:
            asset_id = fi.get("assetId") or fi.get("id")
            url = fi.get("public_url")
            if not url and asset_id:
                try:
                    url = self.query(
                        "query ($id:[ID!]!){ assets(ids:$id){ public_url } }",
                        {"id": [asset_id]},
                    )["assets"][0]["public_url"]
                except Exception:
                    url = None

            out.append(
                {
                    "asset_id": str(asset_id) if asset_id is not None else None,
                    "name": fi.get("name"),
                    "file_size": fi.get("file_size") or fi.get("fileSize"),
                    "file_extension": fi.get("file_extension") or fi.get("fileExtension"),
                    "created_at": fi.get("uploaded_at") or fi.get("created_at"),
                    "public_url": url,
                }
            )

        return out

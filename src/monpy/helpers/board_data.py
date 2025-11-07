from __future__ import annotations

from dataclasses import dataclass
from datetime import date as _date, datetime as _datetime, time as _time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

from ..oo import Session
from ..oo.item import Item
from ..oo.utils import to_attr
from ..exceptions import RateLimitError
from .inventory import _retry_with_backoff


@dataclass(frozen=True)
class _ResolvedColumn:
    title: str
    attr: str
    id: str
    type: Optional[str]
    mode: str  # "decoded" | "text" | "index"
    norm_type: str  # normalized hint/type (e.g., "date", "status")


def _resolve_workspace_and_board_ids(session: Session, *, workspace_name: str, board_name: str) -> Tuple[str, str]:
    client = session.client

    workspaces = client.list_workspaces(limit=100, fields=("id", "name"))
    ws = next((w for w in workspaces if w.get("name") == workspace_name), None)
    if not ws:
        raise SystemExit(f'Workspace "{workspace_name}" not found')
    workspace_id = str(ws["id"])  # type: ignore[index]

    boards = client.list_boards(limit=500, workspace_id=workspace_id, fields=("id", "name"))
    b = next((x for x in boards if x.get("name") == board_name), None)
    if not b:
        raise SystemExit(f'Board "{board_name}" not found in workspace "{workspace_name}"')
    board_id = str(b["id"])  # type: ignore[index]

    return workspace_id, board_id


def _normalize_columns_spec(columns: Mapping[str, str] | Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    if isinstance(columns, Mapping):
        return [(k, v) for k, v in columns.items()]
    return list(columns)


def _resolve_columns(session: Session, *, board_id: str, columns: Sequence[Tuple[str, str]]) -> List[_ResolvedColumn]:
    bd = session.board(board_id)
    col_collection = bd.columns

    resolved: List[_ResolvedColumn] = []
    for title, type_hint in columns:
        attr = to_attr(title)
        col = col_collection.by_attr(attr)
        t = (str(type_hint or "").strip() or (col.type or "")).lower()
        # Choose extraction mode
        # - status/email/phone prefer human-readable text
        # - explicit "index" suffix requests status index
        # - otherwise use OO decoded values
        mode = "decoded"
        if t.endswith(":index"):
            mode = "index"
            t = t.split(":", 1)[0]
        elif t in ("status", "email", "phone"):
            mode = "text"
        resolved.append(_ResolvedColumn(title=title, attr=attr, id=str(col.id), type=col.type, mode=mode, norm_type=t))

    return resolved


def fetch_board_data(
    session: Session,
    *,
    workspace_name: str,
    board_name: str,
    columns: Mapping[str, str] | Sequence[Tuple[str, str]],
    state: str | Sequence[str] | None = "active",
    limit: Optional[int] = None,
    batch_size: int = 100,
    max_retries: int = 5,
    include_subitems: bool = False,
    debug: bool = False,
    logger: Optional[Callable[[str], None]] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch item data from a board identified by workspace and board names.

    Parameters
    ----------
    session: Session
        OO session bound to a `MondayClient`.
    workspace_name: str
        Exact workspace name.
    board_name: str
        Exact board name within the workspace.
    columns: Mapping[str, str] | Sequence[Tuple[str, str]]
        Column titles and type hints to extract. Type hints guide extraction:
        - "text": plain text value (for Text columns)
        - "phone", "email": return human-readable text
        - "status": return the label text
        - "date": decoded ISO date (via OO decoder)
        - append ":index" to request status index (e.g., "status:index")
        If an unknown hint is provided, OO decoded value is returned.
    state: str | list[str] | None
        Item state filter (default: "active").
    limit: Optional[int]
        Maximum number of items to return; fetches all when None.

    Returns
    -------
    list[dict]
        One dict per item with keys: "id", "name", and the provided column titles.
    """

    # Resolve workspace and board ids
    _, board_id = _resolve_workspace_and_board_ids(
        session, workspace_name=workspace_name, board_name=board_name
    )

    # Resolve requested columns to ids/attrs and extraction modes
    specs = _resolve_columns(session, board_id=board_id, columns=_normalize_columns_spec(columns))
    column_ids = [s.id for s in specs]

    client = session.client

    def _log(msg: str) -> None:
        if not debug:
            return
        try:
            if logger:
                logger(msg)
            else:
                print(f"[fetch_board_data] {msg}")
        except Exception:
            pass

    # List item ids (and names) on the board (optionally across states)
    states_to_fetch: List[str]
    if isinstance(state, (list, tuple)):
        states_to_fetch = [str(s) for s in state if s]
    elif isinstance(state, str) and state.lower() == "all":
        states_to_fetch = ["active", "archived"]
    elif isinstance(state, str) and state:
        states_to_fetch = [state]
    else:
        states_to_fetch = ["active"]
    _log(f"states={states_to_fetch}, limit={'None' if limit is None else limit}, include_subitems={include_subitems}")

    def _list_all_items_resilient(st: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        cur: Optional[str] = None
        remaining: Optional[int] = None if limit is None else int(max(0, int(limit)))
        page_idx = 0
        while True:
            try:
                items, cur = _retry_with_backoff(
                    client.list_items,
                    board_id,
                    limit=200,
                    state=st,
                    fields=["id", "name"],
                    cursor=cur,
                    max_retries=max_retries,
                )
            except RateLimitError:
                # As a last resort after retries, keep going if server gave us a cursor
                items, cur = [], cur

            # Some tenants can yield empty pages with a non-null cursor; skip forward
            if not items and cur:
                page_idx += 1
                _log(f"page {page_idx} (state={st}): empty page with cursor -> advancing")
                continue

            if not items:
                _log(f"completed state={st}, total_items={len(out)}")
                break

            page_idx += 1
            _log(f"page {page_idx} (state={st}): got {len(items)} items, cursor={'set' if cur else 'None'}")
            out.extend(items)
            if remaining is not None:
                remaining -= len(items)
                if remaining <= 0:
                    _log(f"limit reached: {len(out)} items")
                    break
            if not cur:
                break
        return out

    rows_meta: List[Dict[str, Any]] = []
    for st in states_to_fetch:
        rows_meta.extend(_list_all_items_resilient(st))
    if not rows_meta:
        return []

    item_ids: List[str] = [str(r.get("id")) for r in rows_meta if r.get("id") is not None]
    _log(f"top-level item_ids fetched: {len(item_ids)}")
    if not item_ids:
        return []

    # Optionally include subitems
    all_item_ids: List[str] = list(item_ids)
    if include_subitems:
        def fetch_subs(pid: str) -> List[str]:
            try:
                subs = _retry_with_backoff(session.client.list_subitems, pid, fields=["id"], max_retries=max_retries)
            except Exception:
                subs = []
            return [str(s.get("id")) for s in (subs or []) if s.get("id") is not None]

        # Light parallelism to reduce wall time while respecting limits
        sub_ids: List[str] = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = {ex.submit(fetch_subs, pid): pid for pid in item_ids}
            for fut in as_completed(futures):
                try:
                    sub_ids.extend(fut.result() or [])
                except Exception:
                    pass
        if sub_ids:
            all_item_ids.extend(sub_ids)
        _log(f"subitem ids fetched: {len(sub_ids)}; total ids now: {len(all_item_ids)}")

    # Fetch selected column values for all items in efficient batches
    # Rate-limit resilient: fetch in chunks with exponential backoff and
    # automatic chunk splitting when retries are exhausted.
    def _fetch_chunk(ids: List[str], *, bs: int) -> List[Dict[str, Any]]:
        if not ids:
            return []
        try:
            _log(f"values chunk: size={len(ids)}, bs={bs}")
            ret = _retry_with_backoff(
                client.get_items_values,
                ids,
                include_board=True,  # include board to correctly decode subitems on their hidden board
                # Important: keep archived/deleted when present, so do NOT exclude nonactive
                exclude_nonactive=False,
                column_ids=(None if include_subitems else column_ids),
                item_fields=["id", "name", "state", "updated_at"],
                batch_size=int(max(1, bs)),
                max_retries=int(max_retries),
            )
            # Detect missing IDs (some tenants may under-return per request)
            try:
                returned_ids = {str(r.get("id")) for r in (ret or []) if r.get("id") is not None}
                missing = [i for i in ids if i not in returned_ids]
            except Exception:
                missing = []
            if missing:
                _log(f"missing {len(missing)} of {len(ids)}; retrying smaller bs")
                # Re-fetch only missing; reduce batch size to be conservative
                next_bs = max(1, min(bs // 2, 50))
                addl = _fetch_chunk(missing, bs=next_bs)
                # Merge: avoid duplicates
                id_seen = set(returned_ids)
                for row in addl:
                    iid = str(row.get("id")) if row.get("id") is not None else None
                    if iid and iid not in id_seen:
                        ret.append(row)
                        id_seen.add(iid)
            return ret
        except RateLimitError:
            # Split the chunk and retry recursively when possible
            if len(ids) <= 1:
                raise
            mid = len(ids) // 2
            _log(f"rate-limit split: left={mid}, right={len(ids)-mid}")
            left = _fetch_chunk(ids[:mid], bs=max(1, bs // 2))
            right = _fetch_chunk(ids[mid:], bs=max(1, bs // 2))
            return left + right

    rows: List[Dict[str, Any]] = []
    step = int(max(1, batch_size))
    for i in range(0, len(all_item_ids), step):
        chunk_ids = all_item_ids[i : i + step]
        rows.extend(_fetch_chunk(chunk_ids, bs=step))
    _log(f"total rows with values: {len(rows)}")

    # Build fast lookup from column id to title/spec for result keys
    id_to_spec: Dict[str, _ResolvedColumn] = {s.id: s for s in specs}

    results: List[Dict[str, Any]] = []
    for row in rows:
        item_id = str(row.get("id"))
        item_name = row.get("name")

        out: Dict[str, Any] = {"id": item_id, "name": item_name}

        # Warm OO decoder for decoded mode once per item
        # Use board from payload when present (important for subitems)
        board_from_row = row.get("board") or {}
        board_for_item = str(board_from_row.get("id")) if board_from_row else board_id
        it = Item(id=item_id, name=item_name, state=row.get("state"), updated_at=row.get("updated_at"), board_id=board_for_item)
        it._session = session  # bind for column metadata access
        it.values.warm_from_row(row)

        # Index by column id for text/raw fallbacks
        cvs = {cv.get("id"): cv for cv in (row.get("column_values") or []) if isinstance(cv, dict)}

        for col_id, spec in id_to_spec.items():
            # Prefer title as key in result
            key = spec.title
            if spec.mode == "decoded":
                try:
                    val = getattr(it.values, spec.attr)
                    # Cast date-like values to Python datetime when requested/typed
                    if val is not None and spec.norm_type in ("date", "datetime"):
                        try:
                            if isinstance(val, str) and val:
                                # Prefer full datetime parsing; fallback to date-only at midnight
                                dt: Optional[_datetime] = None
                                try:
                                    # This expects full ISO with time; may raise ValueError for date-only
                                    dt = _datetime.fromisoformat(val)
                                except Exception:
                                    try:
                                        d = _date.fromisoformat(val)
                                        dt = _datetime.combine(d, _time())
                                    except Exception:
                                        dt = None
                                out[key] = dt if dt is not None else val
                            else:
                                out[key] = val
                        except Exception:
                            out[key] = val
                    else:
                        out[key] = val
                except AttributeError:
                    # Column disappeared or mismatch – return None
                    out[key] = None
            elif spec.mode == "index":
                try:
                    out[key] = getattr(it.values, f"{spec.attr}_index")
                except AttributeError:
                    out[key] = None
            else:  # "text"
                cv = cvs.get(col_id)
                out[key] = None if cv is None else cv.get("text")

        results.append(out)

    return results


__all__ = [
    "fetch_board_data",
]



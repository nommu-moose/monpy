from __future__ import annotations

from typing import Callable, Iterable, Iterator, Optional, Sequence, Tuple, TypeVar, List


T = TypeVar("T")


def iterate_pages(
    fetch: Callable[[Optional[int], int], Sequence[T]],
    page_size: int,
    *,
    start_page: int = 1,
) -> Iterator[T]:
    """Generic page-number paginator.

    Calls ``fetch(page, page_size)`` for each page where ``page`` is ``None``
    on the first iteration (to match APIs that default to page 1 when the
    argument is omitted), and the explicit page number thereafter.
    """
    page = start_page
    while True:
        current_page_arg: Optional[int] = None if page == start_page else page
        rows = fetch(current_page_arg, page_size)
        if not rows:
            return
        for row in rows:
            yield row
        if len(rows) < page_size:
            return
        page += 1


def iterate_cursor(
    fetch: Callable[[Optional[str], int], Tuple[Sequence[T], Optional[str]]],
    page_size: int,
    *,
    start_cursor: Optional[str] = None,
) -> Iterator[T]:
    """Generic cursor paginator.

    Calls ``fetch(cursor, page_size)`` starting with ``start_cursor``;
    expects a tuple ``(rows, next_cursor)``.
    """
    cursor = start_cursor
    while True:
        rows, cursor = fetch(cursor, page_size)
        if not rows:
            return
        for row in rows:
            yield row
        if not cursor:
            return


def collect(iterable: Iterable[T], max_items: Optional[int] = None) -> List[T]:
    """Collect items from an iterable, optionally capping at ``max_items``."""
    out: List[T] = []
    for x in iterable:
        out.append(x)
        if max_items is not None and len(out) >= max_items:
            break
    return out



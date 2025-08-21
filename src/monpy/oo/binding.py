from __future__ import annotations

from typing import Type, TypeVar, Callable, Any

from .session import Session
from .item import Item
from .subitem import SubItem
from .board import Board
from .workspace import Workspace


T = TypeVar("T")


def bind_session(session: Session) -> Callable[[Type[T]], Type[T]]:
    """Class decorator to attach a Session-aware constructor.

    Usage:
        from monpy.generated.sales_pipeline_item import SalesPipelineItem
        from monpy.oo import bind_session

        @bind_session(sess)
        class Sales(SalesPipelineItem):
            pass

        it = Sales(id="...")   # auto-bound to sess
    """

    def decorator(cls: Type[T]) -> Type[T]:
        orig_init = getattr(cls, "__init__")

        def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[no-redef]
            orig_init(self, *args, **kwargs)  # type: ignore[misc]
            try:
                self._session = session
            except Exception:
                # best-effort only
                pass

        setattr(cls, "__init__", __init__)
        return cls

    return decorator



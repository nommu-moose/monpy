from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class _EditContext:
    def __init__(self, model: "BaseModel") -> None:
        self._model = model

    def __enter__(self) -> "BaseModel":
        return self._model

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc is None:
            self._model.save()


@dataclass
class BaseModel:
    id: str
    _dirty: Dict[str, Any] = field(default_factory=dict, repr=False)

    # Session is injected by concrete classes to avoid import cycle
    _session: Any = field(default=None, repr=False)

    def mark_dirty(self, key: str, value: Any) -> None:
        self._dirty[key] = value

    def clear_dirty(self) -> None:
        self._dirty.clear()

    def edit(self) -> _EditContext:
        return _EditContext(self)

    def save(self) -> None:
        if not self._dirty:
            return
        self._flush_changes()
        self.clear_dirty()

    def _flush_changes(self) -> None:
        raise NotImplementedError

    def refresh(self) -> None:
        """Reload latest values from API into this model (best-effort)."""
        self._refresh_from_api()

    def _refresh_from_api(self) -> None:
        # Overridden by concrete models
        pass

    # --- helpers -------------------------------------------------------
    def bind(self, session: Any) -> "BaseModel":
        """Attach a Session to this model and return self for chaining."""
        self._session = session
        return self



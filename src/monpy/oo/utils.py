from __future__ import annotations

import re
from typing import Dict


_NON_ALNUM = re.compile(r"[^0-9a-zA-Z]+")


def to_attr(name: str) -> str:
    """Normalize human titles like "Due Date" to snake_case attribute names.

    - collapse non-alnum to underscore
    - lowercase
    - trim leading/trailing underscores
    - ensure does not start with a digit by prefixing "c_"
    """
    s = _NON_ALNUM.sub("_", name).lower().strip("_")
    if s and s[0].isdigit():
        s = f"c_{s}"
    return s or "value"



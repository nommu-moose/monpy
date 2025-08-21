from __future__ import annotations

import argparse
import keyword
from pathlib import Path
from typing import Iterable

from monpy.client import MondayClient
from .utils import to_attr


HEADER = """
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional, Union, List, Tuple

from monpy.oo.item import Item
from monpy.oo.columns.values import LocationValue

"""

CLASS_TEMPLATE = """
@dataclass
class {class_name}(Item):
    """Typed item model for board {board_id}.

    Columns exposed as properties on `.values` for completion.
    """
{properties}
"""

STUB_HEADER = """
from __future__ import annotations
from datetime import date, datetime
from typing import Optional, Union, List, Tuple
from monpy.oo.item import Item
from monpy.oo.columns.values import LocationValue
class {class_name}(Item):
{stub_properties}
"""


def sanitize(name: str) -> str:
    n = to_attr(name).title().replace("_", "")
    if not n:
        n = "Board"
    if keyword.iskeyword(n):
        n = f"{n.capitalize()}Board"
    return n


def _getter_type(col_type: str) -> str:
    t = col_type.lower()
    if t in ("text",):
        return "Optional[str]"
    if t in ("numbers", "number"):
        return "Optional[Union[int, float]]"
    if t in ("status",):
        return "Optional[str]"
    if t in ("date",):
        return "Optional[str]"  # ISO date string
    if t in ("people", "person"):
        return "List[int]"
    if t in ("board_relation", "connect_boards"):
        return "List[int]"
    if t in ("tags", "tag"):
        return "List[int]"
    if t in ("link",):
        return "Optional[str]"
    if t in ("doc",):
        return "Optional[str]"  # objectId
    if t in ("location",):
        return "Optional[LocationValue]"
    return "object"


def _setter_type(col_type: str) -> str:
    t = col_type.lower()
    if t in ("text",):
        return "Optional[str]"
    if t in ("numbers", "number"):
        return "Optional[Union[int, float]]"
    if t in ("status",):
        return "Optional[Union[str, int, dict]]"
    if t in ("date",):
        return "Optional[Union[str, date, datetime]]"
    if t in ("people", "person", "board_relation", "connect_boards", "tags", "tag"):
        return "Union[int, List[int]]"
    if t in ("link",):
        return "Union[str, Tuple[str, str]]"
    if t in ("doc",):
        return "Optional[str]"
    if t in ("location",):
        return "Optional[Union[str, dict, LocationValue]]"
    return "object"


def _unique_attr(name: str, used: set[str]) -> str:
    base = name
    idx = 1
    while name in used or keyword.iskeyword(name):
        idx += 1
        name = f"{base}_{idx}"
    used.add(name)
    return name


def _gen_property(attr: str, title: str, col_type: str) -> str:
    getter_t = _getter_type(col_type)
    setter_t = _setter_type(col_type)
    return (
        f"    @property\n"
        f"    def {attr}(self) -> {getter_t}:\n"
        f"        \"\"\"Column: {title} (type: {col_type})\"\"\"\n"
        f"        return self.values.{attr}\n\n"
        f"    @{attr}.setter\n"
        f"    def {attr}(self, value: {setter_t}) -> None:\n"
        f"        self.values.{attr} = value\n"
    )


def _gen_property_stub(attr: str, title: str, col_type: str) -> str:
    getter_t = _getter_type(col_type)
    setter_t = _setter_type(col_type)
    return (
        f"    @property\n"
        f"    def {attr}(self) -> {getter_t}: ...\n"
        f"    @{attr}.setter\n"
        f"    def {attr}(self, value: {setter_t}) -> None: ...\n"
    )


def generate_board_item_class(client: MondayClient, *, board_id: str, out_dir: Path, emit_stub: bool = True) -> tuple[Path, Path | None]:
    cols = client.get_columns(board_id, fields=("id", "title", "type"))
    board = client.get_board(board_id)
    class_name = sanitize(board.get("name") or f"Board{board_id}") + "Item"
    used: set[str] = set()
    props: list[str] = []
    stub_props: list[str] = []
    for c in cols:
        title = c.get("title") or c.get("id")
        ctype = c.get("type") or "text"
        attr = _unique_attr(to_attr(title), used)
        props.append(_gen_property(attr, title, ctype))
        stub_props.append(_gen_property_stub(attr, title, ctype))

    body = "\n".join(props) if props else "    pass\n"
    code = HEADER + CLASS_TEMPLATE.format(class_name=class_name, board_id=board_id, properties=body)

    out_dir.mkdir(parents=True, exist_ok=True)
    base_name = to_attr(board.get('name') or f'board_{board_id}') + "_item"
    py_path = out_dir / f"{base_name}.py"
    py_path.write_text(code, encoding="utf-8")

    pyi_path: Path | None = None
    if emit_stub:
        stub_body = "\n".join(stub_props) if stub_props else "    pass\n"
        stub_code = STUB_HEADER.format(class_name=class_name, stub_properties=stub_body)
        pyi_path = out_dir / f"{base_name}.pyi"
        pyi_path.write_text(stub_code, encoding="utf-8")

    return py_path, pyi_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate typed Item class for a board")
    parser.add_argument("--token", required=True)
    parser.add_argument("--board-id", required=True)
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--no-stub", action="store_true", help="Do not emit .pyi stub file")
    args = parser.parse_args(argv)

    client = MondayClient(args.token)
    py_path, pyi_path = generate_board_item_class(client, board_id=args.board_id, out_dir=Path(args.out), emit_stub=not args.no_stub)
    print(f"Generated: {py_path}")
    if pyi_path:
        print(f"Generated: {pyi_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())



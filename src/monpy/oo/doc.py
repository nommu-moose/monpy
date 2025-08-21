from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .base import BaseModel


@dataclass
class Doc(BaseModel):
    name: str | None = None
    url: str | None = None
    object_id: str | None = None
    workspace_id: str | None = None

    # read ops
    def blocks(self, *, page_size: int = 100, by_object_id: bool = True) -> List[Dict[str, Any]]:
        return self._session.client.get_all_blocks(self.id if not by_object_id else self.object_id or self.id, page_size=page_size, by_object_id=by_object_id)

    def text(self, *, by_object_id: bool = True) -> str:
        return self._session.client.get_doc_text(self.id if not by_object_id else self.object_id or self.id, by_object_id=by_object_id)

    # write ops
    def replace_plain_text(self, body_text: str, *, column_item_id: Optional[str] = None, column_id: Optional[str] = None) -> None:
        # Convenience to reuse existing client helper when invoked via a doc column context
        if column_item_id and column_id:
            self._session.client.set_full_doc_plain_text(column_item_id, column_id, body_text)
            return
        # If we already know the real doc id, replace blocks using low-level calls
        # Simplified: delete all existing deletable blocks then insert one text block
        for blk in self._session.client.get_all_blocks(self.id, by_object_id=False):
            if blk.get("type") in self._session.client._DELETABLE_DOC_BLOCK_TYPES:  # type: ignore[attr-defined]
                self._session.client.mutation(
                    "mutation ($b:String!){ delete_doc_block(block_id:$b){ id } }",
                    {"b": blk["id"]},
                )
        self._session.client.create_doc_block(self.id, block_type="normal_text", content={
            "alignment": "left",
            "direction": "ltr",
            "deltaFormat": [{"insert": body_text}],
        })



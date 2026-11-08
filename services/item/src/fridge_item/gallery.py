from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4
import numpy as np


class ItemGallery:
    """Persistent item gallery tracking items currently in the fridge."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._items: list[dict] = []
        if self.path.exists():
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as exc:
                raise ValueError(
                    f"Corrupt or unreadable gallery file at '{self.path}': please fix or delete it."
                ) from exc

            if not isinstance(data, dict) or not isinstance(data.get("items"), list):
                raise ValueError(
                    f"Corrupt or invalid gallery file at '{self.path}': please fix or delete it."
                )

            items: list[dict] = []
            for item in data["items"]:
                if not isinstance(item, dict):
                    raise ValueError(
                        f"Corrupt or invalid item in gallery file at '{self.path}': please fix or delete it."
                    )
                item_id = item.get("id")
                label = item.get("label")
                if not isinstance(item_id, str) or not item_id or not isinstance(label, str):
                    raise ValueError(
                        f"Corrupt or invalid item in gallery file at '{self.path}': please fix or delete it."
                    )
                embedding = item.get("embedding", None)
                items.append({"id": item_id, "label": label, "embedding": embedding})
            self._items = items

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.path.with_name(self.path.name + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump({"items": self._items}, f, indent=2)
        os.replace(tmp_path, self.path)

    def add(self, label: str, embedding: np.ndarray | None = None) -> str:
        item_id = "item_" + uuid4().hex[:8]
        emb_list = (
            np.asarray(embedding, dtype=float).tolist()
            if embedding is not None
            else None
        )
        self._items.append(
            {"id": item_id, "label": label, "embedding": emb_list}
        )
        self._save()
        return item_id

    def take(
        self, label: str, embedding: np.ndarray | None = None
    ) -> tuple[str, float]:
        if not self._items:
            return ("unknown", 0.0)

        # Oldest item with matching label (items are in insertion order)
        for idx, item in enumerate(self._items):
            if item.get("label") == label:
                matched = self._items.pop(idx)
                self._save()
                return (matched["id"], 1.0)

        # Fallback to oldest item of any label
        matched = self._items.pop(0)
        self._save()
        return (matched["id"], 0.3)

    def items(self) -> dict[str, dict]:
        return {
            item["id"]: {
                "label": item["label"],
                "embedding": item.get("embedding"),
            }
            for item in self._items
        }

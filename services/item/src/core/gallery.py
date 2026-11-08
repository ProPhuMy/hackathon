"""Persistent JSON gallery of items currently in the fridge; TAKEs are matched by label or embedding."""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np


def _cosine(q_vec: np.ndarray, stored: list[float]) -> float:
    """Cosine similarity clipped to [0, 1]; 0 for zero vectors or mismatched lengths."""
    s_vec = np.asarray(stored, dtype=float)
    q_norm = np.linalg.norm(q_vec)
    s_norm = np.linalg.norm(s_vec)
    if q_norm > 0 and s_norm > 0 and len(q_vec) == len(s_vec):
        cos = float(np.dot(q_vec, s_vec) / (q_norm * s_norm))
    else:
        cos = 0.0
    return max(0.0, min(1.0, cos))


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

        emb_items = [
            (idx, item)
            for idx, item in enumerate(self._items)
            if item.get("embedding") is not None
        ]

        if embedding is not None and emb_items:
            q_vec = np.asarray(embedding, dtype=float)
            scored = []
            for orig_idx, item in emb_items:
                score = _cosine(q_vec, item["embedding"])
                # Tie-breaking key: max score, prefer same label, then oldest (lowest orig_idx)
                key = (score, 1 if item.get("label") == label else 0, -orig_idx)
                scored.append((key, orig_idx, score))

            best = max(scored, key=lambda x: x[0])
            matched = self._items.pop(best[1])
            self._save()
            return (matched["id"], best[2])

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

    def take_many(
        self, queries: list[tuple[str, np.ndarray]]
    ) -> list[tuple[str, float]]:
        if not queries:
            return []

        emb_items = [
            (idx, item)
            for idx, item in enumerate(self._items)
            if item.get("embedding") is not None
        ]
        if not emb_items:
            return [self.take(label, None) for label, _ in queries]

        from scipy.optimize import linear_sum_assignment

        n = len(queries)
        m = len(emb_items)
        cost_matrix = np.zeros((n, m), dtype=float)

        for i, (_, q_emb) in enumerate(queries):
            if q_emb is None:
                cost_matrix[i, :] = 1.0
                continue
            q_vec = np.asarray(q_emb, dtype=float)
            for j, (_, item) in enumerate(emb_items):
                cost_matrix[i, j] = 1.0 - _cosine(q_vec, item["embedding"])

        row_ind, col_ind = linear_sum_assignment(cost_matrix)
        results: list[tuple[str, float]] = [("unknown", 0.0)] * n
        indices_to_remove: set[int] = set()

        for r, c in zip(row_ind, col_ind):
            orig_idx, item = emb_items[c]
            clipped_cos = max(0.0, min(1.0, 1.0 - cost_matrix[r, c]))
            results[r] = (item["id"], float(clipped_cos))
            indices_to_remove.add(orig_idx)

        self._items = [
            item
            for idx, item in enumerate(self._items)
            if idx not in indices_to_remove
        ]
        self._save()
        return results

    def items(self) -> dict[str, dict]:
        return {
            item["id"]: {
                "label": item["label"],
                "embedding": item.get("embedding"),
            }
            for item in self._items
        }

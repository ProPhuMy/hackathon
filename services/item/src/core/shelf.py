from __future__ import annotations

from .geometry import Track


def shelf_diff(
    before: list[Track],
    after: list[Track],
    iou_min: float = 0.3,
) -> tuple[list[Track], list[Track]]:
    """Compare item tracks before and after door opening.

    Returns (added, removed) where:
    - Only tracks with kind == "item" count.
    - An "after" item is matched to an unmatched "before" item with the same label
      and IoU >= iou_min (greedy, highest IoU first).
    - Unmatched "after" items are added.
    - Unmatched "before" items are removed.
    """
    before_items = [t for t in before if t.kind == "item"]
    after_items = [t for t in after if t.kind == "item"]

    candidates: list[tuple[float, int, int]] = []
    for a_idx, a_track in enumerate(after_items):
        for b_idx, b_track in enumerate(before_items):
            if a_track.label == b_track.label:
                iou = a_track.box.iou(b_track.box)
                if iou >= iou_min:
                    candidates.append((iou, a_idx, b_idx))

    # Greedy match, highest IoU first (tie-break by indices for determinism)
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))

    matched_after: set[int] = set()
    matched_before: set[int] = set()
    for _, a_idx, b_idx in candidates:
        if a_idx not in matched_after and b_idx not in matched_before:
            matched_after.add(a_idx)
            matched_before.add(b_idx)

    added = [
        a_track for a_idx, a_track in enumerate(after_items) if a_idx not in matched_after
    ]
    removed = [
        b_track for b_idx, b_track in enumerate(before_items) if b_idx not in matched_before
    ]

    return added, removed

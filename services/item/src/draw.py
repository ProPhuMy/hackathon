import cv2
import numpy as np

from .core.geometry import DoorLine, Track


def overlay(
    frame: np.ndarray,
    tracks: list[Track],
    line: DoorLine,
    door_open: bool,
    events: list[dict],
) -> np.ndarray:
    """Draw tracking boxes, door line, door status, and recent events onto a frame copy."""
    display = frame.copy()

    # 1. Door line
    p1 = (int(round(line.p1[0])), int(round(line.p1[1])))
    p2 = (int(round(line.p2[0])), int(round(line.p2[1])))
    cv2.line(display, p1, p2, (0, 255, 255), 2)

    # 2. Door state text
    door_text = "Door: OPEN" if door_open else "Door: CLOSED"
    door_color = (0, 255, 0) if door_open else (0, 0, 255)
    cv2.putText(
        display,
        door_text,
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        door_color,
        2,
        cv2.LINE_AA,
    )

    # 3. Detection and tracking boxes
    for track in tracks:
        x1 = int(round(track.box.x1))
        y1 = int(round(track.box.y1))
        x2 = int(round(track.box.x2))
        y2 = int(round(track.box.y2))

        # Magenta for hand, green for item
        box_color = (255, 0, 255) if track.kind == "hand" else (0, 255, 0)
        cv2.rectangle(display, (x1, y1), (x2, y2), box_color, 2)

        label_text = f"{track.id}:{track.label}"
        (tw, th), baseline = cv2.getTextSize(
            label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1
        )
        text_y = max(y1 - 5, th + 5)
        cv2.rectangle(
            display,
            (x1, text_y - th - 2),
            (x1 + tw + 2, text_y + baseline),
            box_color,
            -1,
        )
        cv2.putText(
            display,
            label_text,
            (x1, text_y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    # 4. Recent events
    y_ev = 60
    for ev in events[-3:]:
        ev_type = ev.get("type", "")
        ev_label = ev.get("item_label", "")
        ev_id = ev.get("item_id", "")
        ev_text = f"Event: {ev_type} {ev_label} ({ev_id})"
        cv2.putText(
            display,
            ev_text,
            (20, y_ev),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (255, 255, 0),
            2,
            cv2.LINE_AA,
        )
        y_ev += 25

    return display

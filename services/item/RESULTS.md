| layer | correct | missed | extra | accuracy |
|---|---|---|---|---|

## Detector choice (2026-11-08)

Two 30-second clips came from an iPhone (DroidCam, 1280x720) looking down: one with a hand holding a small bunch
of green grapes, one with a hand holding a water bottle. Every 3rd frame was run through `predict` at conf 0.25,
with the default prompts plus "grapes", on a GTX 1650. Each cell gives frames detected (max confidence).

| model | ms/frame | grapes clip: hand | grapes clip: grapes | bottle clip: hand | bottle clip: bottle |
|---|---|---|---|---|---|
| yoloe-11s-seg (old default) | 15 | 87 (0.77) | 2 (0.44) | 17 (0.54) | 18 (0.96) |
| yoloe-26n-seg | 8 | 81 (0.75) | 6 (0.42) | 174 (0.74) | 35 (0.95) |
| yoloe-26s-seg | 15 | 93 (0.65) | 0 | 59 (0.78) | 38 (0.97) |
| yoloe-26m-seg | 38 | 78 (0.82) | 5 (0.39) | 31 (0.64) | 43 (0.96) |
| **yoloe-26l-seg (default)** | 44 | 86 (0.75) | **13 (0.69)** | 69 (0.51) | 41 (0.96) |
| yoloe-26x-seg | 89 | 69 (0.59) | 4 (0.46) | 9 (0.29) | 45 (0.96) |

All of the top 6 yoloe-26l grape boxes were on the grape bunch. Rejected alternatives:
- The prompt-free yoloe-11s-seg-pf (4,585 built-in names) mislabelled the background ("manatee", "tree frog").
- yolov8m-oiv7 (Open Images) found no grapes and almost no hands.
- Brand-level prompts ("coca-cola can", "water bottle") made the bottle read as "soda can".

## Top-down camera, edge mode (2026-11-08)

An iPhone (DroidCam) sat on top of the fridge looking down its front. Two labelled 40 s clips each contained
one PUT then one TAKE of a water bottle. A third clip only opened and closed the door. The door line is
vertical at x=690, measured from where hands reach and the door/body edges. The detector was yoloe-26l-seg.

| clip | expected | "crossing" mode (hand crossings + door gate) | "edge" mode |
|---|---|---|---|
| put_take | PUT, TAKE | TAKE only | TAKE (PUT missed: bottle visible in 4 frames) |
| put_take2 | PUT, TAKE | PUT only | PUT, TAKE (same gallery item_id) |
| door_test | nothing | nothing | nothing |

Why crossing mode fails here:
- Door brightness is not monotonic: a half-open door darkens the ROI, a wide-open one brightens it, so the door
  gate flickered.
- The tracker loses the hand at the door edge, so in/out crossings are missed.

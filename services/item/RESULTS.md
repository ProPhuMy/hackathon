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

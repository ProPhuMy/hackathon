# Fridge Pixel — selected direction

The selected display face follows the user's repository-root `image.png`.
`fridge-pixel.ttf` reproduces its A–Z and 0–9 shapes on a 7-row pixel grid,
including narrow I, T, Y and 1. Lowercase ASCII maps to uppercase.
Space and `. : - / ! ?` supplement the reference; other Unicode is unsupported.
Keep body copy and personal names in Inter. Shadow is a separate CSS effect.

Import `/fonts/fridge-pixel.css`. Install the TTF locally to use editable text
in Figma; the Figma specimen uses vector outlines and needs no installation.
Rebuild with `uv run --with fonttools python dashboard/tools/build_fridge_pixel.py`.
The character definitions are in `fridge-pixel-glyphs.json`.

## Cold Grid — superseded exploration

Original pixel display typefaces created for Fridge Tracker: Regular and Scan.
Both use a 5 × 7 construction, clipped corners and a 580-unit advance.
Scan introduces horizontal apertures. Use at 32px or larger; keep body copy,
personal names, forms and data tables in a readable text face.

Coverage: A–Z, 0–9, space and `. , : ! ? - / + ( ) '`. Lowercase ASCII letters
map to uppercase shapes. Accented letters and other Unicode glyphs are not
included in v1. This is a display family, not a general-purpose body font.

Import `/fonts/cold-grid.css` to use either family in the website. The TTFs
can also be installed locally for native Figma text; the Figma specimen uses
editable vector outlines so it is viewable without font installation.

Regenerate from the repository root:

```sh
uv run --with fonttools python dashboard/tools/build_cold_grid.py
```

The source glyph definitions and generator are in `dashboard/tools/build_cold_grid.py`.

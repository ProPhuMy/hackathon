"""Build Fridge Pixel from the glyphs transcribed from the user's image.png.

Run: uv run --with fonttools python dashboard/tools/build_fridge_pixel.py
"""
import json
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

out = Path(__file__).resolve().parents[1] / 'public' / 'fonts'
rows = json.loads((out / 'fridge-pixel-glyphs.json').read_text())
# Punctuation is supplemental; the reference only supplies A-Z and digits.
rows.update({
    ' ': ['000'] * 7,
    '.': ['00'] * 5 + ['11'] * 2,
    ':': ['00', '11', '11', '00', '11', '11', '00'],
    '-': ['0000'] * 3 + ['1111'] + ['0000'] * 3,
    '/': ['0000001', '0000011', '0000110', '0001100', '0011000', '0110000', '1100000'],
    '!': ['11'] * 5 + ['00', '11'],
    '?': ['011110', '110011', '000011', '000110', '001100', '000000', '001100'],
})
glyphs, metrics = {}, {}
names = {c: f'uni{ord(c):04X}' for c in rows}
for c in ['.notdef'] + list(rows):
    bitmap = rows['?' if c == '.notdef' else c]
    name = '.notdef' if c == '.notdef' else names[c]
    pen = TTGlyphPen(None)
    for y, row in enumerate(bitmap):
        x = 0
        while x < len(row):
            if row[x] == '0':
                x += 1
                continue
            start = x
            while x < len(row) and row[x] == '1':
                x += 1
            left, right = start * 100, x * 100
            top, bottom = 800 - y * 100, 700 - y * 100
            pen.moveTo((left, bottom))
            pen.lineTo((left, top))
            pen.lineTo((right, top))
            pen.lineTo((right, bottom))
            pen.closePath()
    glyphs[name] = pen.glyph()
    metrics[name] = ((len(bitmap[0]) + 1) * 100, 0)
fb = FontBuilder(1000, isTTF=True)
fb.setupGlyphOrder(list(glyphs))
cmap = {ord(c): names[c] for c in rows}
cmap.update({ord(c.lower()): names[c] for c in rows if c.isalpha()})
fb.setupCharacterMap(cmap)
fb.setupGlyf(glyphs)
fb.setupHorizontalMetrics(metrics)
fb.setupHorizontalHeader(ascent=900, descent=-100)
fb.setupNameTable({'familyName': 'Fridge Pixel', 'styleName': 'Regular',
                  'uniqueFontIdentifier': 'FridgePixel-1.0', 'fullName': 'Fridge Pixel Regular',
                  'psName': 'FridgePixel-Regular', 'version': 'Version 1.0'})
fb.setupOS2(sTypoAscender=900, sTypoDescender=-100, usWinAscent=900, usWinDescent=100)
fb.setupPost()
fb.setupMaxp()
fb.save(out / 'fridge-pixel.ttf')
print(f'Built Fridge Pixel: {len(cmap)} mapped characters')

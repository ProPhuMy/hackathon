"""Build the original Cold Grid display fonts and matching editable SVG specimens.

Run: uv run --with fonttools python dashboard/tools/build_cold_grid.py
"""
import json
from pathlib import Path
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public' / 'fonts'
OUT.mkdir(parents=True, exist_ok=True)
ROWS = {
 'A':'01110/11011/11011/11111/11011/11011/11011',
 'B':'11110/11011/11011/11110/11011/11011/11110',
 'C':'01111/11000/11000/11000/11000/11000/01111',
 'D':'11110/11011/11011/11011/11011/11011/11110',
 'E':'11111/11000/11000/11110/11000/11000/11111',
 'F':'11111/11000/11000/11110/11000/11000/11000',
 'G':'01111/11000/11000/11011/11011/11011/01111',
 'H':'11011/11011/11011/11111/11011/11011/11011',
 'I':'11111/00100/00100/00100/00100/00100/11111',
 'J':'00111/00011/00011/00011/11011/11011/01110',
 'K':'11011/11011/11110/11100/11110/11011/11011',
 'L':'11000/11000/11000/11000/11000/11000/11111',
 'M':'11011/11111/11111/11011/11011/11011/11011',
 'N':'11001/11101/11101/11111/11011/11011/11001',
 'O':'01110/11011/11011/11011/11011/11011/01110',
 'P':'11110/11011/11011/11110/11000/11000/11000',
 'Q':'01110/11011/11011/11011/11111/00110/00011',
 'R':'11110/11011/11011/11110/11100/11011/11011',
 'S':'01111/11000/11000/01110/00011/00011/11110',
 'T':'11111/00100/00100/00100/00100/00100/00100',
 'U':'11011/11011/11011/11011/11011/11011/01110',
 'V':'11011/11011/11011/11011/11011/01110/00100',
 'W':'11011/11011/11011/11011/11111/11111/01010',
 'X':'11011/11011/01110/00100/01110/11011/11011',
 'Y':'11011/11011/11011/01110/00100/00100/00100',
 'Z':'11111/00011/00110/00100/01100/11000/11111',
 '0':'01110/11011/11011/11011/11011/11011/01110',
 '1':'00100/01100/00100/00100/00100/00100/01110',
 '2':'11110/00011/00011/01110/11000/11000/11111',
 '3':'11110/00011/00011/01110/00011/00011/11110',
 '4':'11011/11011/11011/11111/00011/00011/00011',
 '5':'11111/11000/11000/11110/00011/00011/11110',
 '6':'01111/11000/11000/11110/11011/11011/01110',
 '7':'11111/00011/00110/00100/01100/01100/01100',
 '8':'01110/11011/11011/01110/11011/11011/01110',
 '9':'01110/11011/11011/01111/00011/00011/11110',
 '.':'00000/00000/00000/00000/00000/00110/00110',
 ',':'00000/00000/00000/00000/00110/00110/00100',
 ':':'00000/00110/00110/00000/00110/00110/00000',
 '!':'00100/00100/00100/00100/00100/00000/00100',
 '?':'01110/11011/00011/00110/00100/00000/00100',
 '-':'00000/00000/00000/11111/00000/00000/00000',
 '/':'00001/00011/00110/00100/01100/11000/10000',
 '+':'00000/00100/00100/11111/00100/00100/00000',
 '(':'00010/00100/01100/01100/01100/00100/00010',
 ')':'01000/00100/00110/00110/00110/00100/01000',
 "'":'00100/00100/00000/00000/00000/00000/00000',
 ' ':'00000/00000/00000/00000/00000/00000/00000',
}

def polygons(ch, scan=False):
    result = []
    for y, row in enumerate(ROWS[ch].split('/')):
        x = 0
        while x < 5:
            if row[x] == '0':
                x += 1
                continue
            start = x
            while x < 5 and row[x] == '1':
                x += 1
            left, right, top, bottom = start*100+12, x*100-12, y*100+5, y*100+95
            # Asymmetric chamfers and narrow horizontal breaks are the signature.
            ranges = [(top, top+36), (top+54, bottom)] if scan else [(top, bottom)]
            for t, b in ranges:
                result.append([(left,t),(right-14,t),(right,t+14),(right,b),(left+10,b),(left,b-10)])
    return result

def svg(text, scan=False, color='#D5FF5F'):
    paths = []
    for i,ch in enumerate(text.upper()):
        for poly in polygons(ch,scan):
            paths.append('M'+' L'.join(f'{x+i*580},{y}' for x,y in poly)+' Z')
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{max(1,len(text)*580-80)}" height="700" viewBox="0 0 {max(1,len(text)*580-80)} 700"><path fill="{color}" d="{" ".join(paths)}"/></svg>'

for scan in (False,True):
    family = 'Cold Grid Scan' if scan else 'Cold Grid'
    stem = 'cold-grid-scan' if scan else 'cold-grid'
    chars = list(ROWS)
    names = {c:f'uni{ord(c):04X}' for c in chars}
    order = ['.notdef']+[names[c] for c in chars]
    glyphs = {}
    for c in ['.notdef']+chars:
        pen = TTGlyphPen(None)
        for poly in polygons('?' if c=='.notdef' else c,scan):
            # SVG y grows down; font y grows up. Reverse winding for outer contours.
            pts = [(x+40,800-y) for x,y in reversed(poly)]
            pen.moveTo(pts[0])
            for point in pts[1:]: pen.lineTo(point)
            pen.closePath()
        glyphs['.notdef' if c=='.notdef' else names[c]]=pen.glyph()
    fb=FontBuilder(1000,isTTF=True)
    fb.setupGlyphOrder(order)
    cmap={ord(c):names[c] for c in chars}
    cmap.update({ord(c.lower()):names[c] for c in chars if c.isalpha()})
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({g:(580,40) for g in order})
    fb.setupHorizontalHeader(ascent=900,descent=-100)
    fb.setupNameTable({'familyName':family,'styleName':'Regular','uniqueFontIdentifier':family+'-1.0','fullName':family+' Regular','psName':family.replace(' ','')+'-Regular','version':'Version 1.0'})
    fb.setupOS2(sTypoAscender=900,sTypoDescender=-100,usWinAscent=900,usWinDescent=100)
    fb.setupPost()
    fb.setupMaxp()
    fb.save(OUT/(stem+'.ttf'))
    fb.font.flavor='woff2'
    # WOFF2 uses the optional Brotli dependency; TTF works in browsers as well.
    try: fb.font.save(OUT/(stem+'.woff2'))
    except ImportError: pass

specimens = {key:svg(text,scan) for key,text,scan in [
    ('title','COLD GRID',False),('scan','COLD GRID',True),
    ('alphabet1','ABCDEFGHIJKLM',False),('alphabet2','NOPQRSTUVWXYZ',False),
    ('digits','0123456789 .:!?',False),('headline','WHO TOOK MY MILK?',False),
    ('label','FRIDGE 01 / LIVE',True)]}
(OUT/'specimens.json').write_text(json.dumps(specimens))
print(f'Built Cold Grid and Cold Grid Scan; {len(ROWS)} source glyphs, lowercase aliases, SVG specimens.')

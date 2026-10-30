#!/usr/bin/env python3
"""Contact sheet of the assembled handbook for order and blank-page checks."""
import sys
from pathlib import Path

import fitz

pdf = Path(sys.argv[1])
out = Path(sys.argv[2])
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 4

doc = fitz.open(pdf)
zoom = 0.55
thumbs = []
for page in doc:
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
    thumbs.append(pix)

w, h = thumbs[0].width, thumbs[0].height
gap = 10
rows = (len(thumbs) + cols - 1) // cols
sheet = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, cols * (w + gap) + gap, rows * (h + gap) + gap), False)
sheet.clear_with(200)
for i, pix in enumerate(thumbs):
    x = gap + (i % cols) * (w + gap)
    y = gap + (i // cols) * (h + gap)
    pix.set_origin(x, y)
    sheet.copy(pix, pix.irect)

sheet.save(out)
print(f"{len(thumbs)} pages -> {out} ({sheet.width}x{sheet.height})")

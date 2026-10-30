#!/usr/bin/env python3
"""Render one page of the assembled PDF to PNG: render_page.py <pdf> <n> <out> [dpi]"""
import sys

import fitz

pdf, number, out = sys.argv[1], int(sys.argv[2]), sys.argv[3]
dpi = int(sys.argv[4]) if len(sys.argv) > 4 else 150
doc = fitz.open(pdf)
doc[number - 1].get_pixmap(dpi=dpi).save(out)
print(f"page {number} -> {out}")

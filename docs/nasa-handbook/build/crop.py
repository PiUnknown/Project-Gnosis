import pymupdf, sys

# usage: crop.py pdf out x0 y0 x1 y1   (coordinates in millimetres)
pdf, out = sys.argv[1], sys.argv[2]
x0, y0, x1, y1 = [float(v) * 72 / 25.4 for v in sys.argv[3:7]]
doc = pymupdf.open(pdf)
pix = doc[0].get_pixmap(clip=pymupdf.Rect(x0, y0, x1, y1), dpi=600)
pix.save(out)
print(pix.width, pix.height)

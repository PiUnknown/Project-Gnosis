#!/usr/bin/env python3
"""Merge the rendered page PDFs into one handbook in PAGES_SPEC order.

    uv run --with pymupdf python docs/nasa-handbook/build/assemble.py

Reads docs/nasa-handbook/<page>.pdf for every entry in build.PAGES_SPEC,
writes docs/nasa-handbook/Project-Gnosis-Operations-Handbook.pdf, and
prints the page order actually embedded so the result can be checked
against the reading map.
"""
from pathlib import Path

import fitz

from build import DOC, HANDBOOK, PAGES_SPEC

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "Project-Gnosis-Operations-Handbook.pdf"


def section_of(page_label: str) -> str:
    return page_label.split("-")[0]


def main() -> int:
    missing = [s[0] for s in PAGES_SPEC if not (ROOT / "pdf" / f"{s[0]}.pdf").exists()]
    if missing:
        print("missing page PDFs:", ", ".join(missing))
        return 1

    doc = fitz.open()
    toc = []
    current = None
    section_pages = {}
    for spec in PAGES_SPEC:
        section_pages[section_of(spec[5])] = section_pages.get(section_of(spec[5]), 0) + 1
    for index, (name, _frag, _opener, subsystem, _tab, page_label, _footer) in enumerate(PAGES_SPEC, start=1):
        src = fitz.open(ROOT / "pdf" / f"{name}.pdf")
        if src.page_count != 1:
            print(f"{name}.pdf has {src.page_count} pages, expected 1")
            return 1
        doc.insert_pdf(src)
        src.close()

        section = section_of(page_label)
        if section != current:
            current = section
            toc.append([1, f"{section}  {subsystem}", index])
        if section_pages[section] > 1:
            toc.append([2, f"{page_label}  {subsystem}", index])

    doc.set_toc(toc)
    doc.set_metadata(
        {
            "title": f"{DOC} {HANDBOOK}",
            "author": "Project Gnosis",
            "subject": "Systems data: architecture, subsystems, file catalogue, decisions, operation",
            "keywords": "Project Gnosis, handbook, systems data, architecture, file catalogue",
            "creator": "nasa-handbook build (HTML + Chrome print)",
            "producer": "PyMuPDF",
        }
    )
    doc.save(OUT, garbage=4, deflate=True)
    doc.close()

    print(f"wrote {OUT.name}: {len(PAGES_SPEC)} pages")
    for name, _frag, _opener, subsystem, _tab, page_label, _footer in PAGES_SPEC:
        print(f"  {page_label:<7} {name:<5} {subsystem}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Assemble the Project Gnosis handbook pages from editable body fragments.

Each fragment in build/pages/ holds only the page body: opener, numbered
paragraphs, figures and the lower band. This script supplies the shared
head, thumb tab, footer and the Apollo-page CSS, then writes a standalone
HTML file that can be edited on its own.

    python docs/nasa-handbook/build/build.py
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent
PAGES = ROOT / "pages"

DOC = "GN1A-03-BLOCK I-(1)"
HANDBOOK = "PROJECT GNOSIS OPERATIONS HANDBOOK"
PART = "SYSTEMS DATA"
BASIC_DATE = "25 JULY 2026"
CHANGE_DATE = "16 OCTOBER 2026"

CSS = r"""
  @font-face { font-family: "Routed Gothic"; src: url("fonts/routed-gothic.ttf"); unicode-range: U+0000-0030, U+0032-FFFF; }
  @font-face { font-family: "Routed Gothic Narrow"; src: url("fonts/routed-gothic-narrow.ttf"); unicode-range: U+0000-0030, U+0032-FFFF; }
  @font-face { font-family: "Routed Gothic"; src: local("Helvetica Neue"), local("HelveticaNeue"), local("Arial"); unicode-range: U+0031; }
  @font-face { font-family: "Routed Gothic Narrow"; src: local("Helvetica Neue"), local("HelveticaNeue"), local("Arial"); unicode-range: U+0031; }
  @font-face { font-family: "Letter Gothic"; src: url("fonts/LetterGothicCode-R.ttf"); font-weight: 400; }
  @font-face { font-family: "Letter Gothic"; src: url("fonts/LetterGothicCode-B.ttf"); font-weight: 700; }

  @page { size: A4; margin: 0; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #8a8a86; }
  body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  @media print { html, body { background: none; } }

  :root {
    --ink: #000000;
    --paper: #fbfaf5;
    --type: "Iowan Old Style", "Iowan", Georgia, serif;
    --leroy: "Routed Gothic Narrow", "Routed Gothic", sans-serif;
    --selectric: "Letter Gothic", "Courier", monospace;
  }
  @media print { :root { --paper: #ffffff; } }

  .page {
    position: relative; width: 210mm; height: 297mm; margin: 0 auto;
    padding: 9mm 15mm 0 16mm; background: var(--paper); color: var(--ink);
    font-family: var(--type); font-size: 8pt; line-height: 1.33;
    letter-spacing: 0.055em; overflow: hidden;
  }

  .head { text-align: center; line-height: 1.25; }
  .head .doc { font-weight: 700; font-size: 8.6pt; letter-spacing: 0.06em; }
  .head .title { font-weight: 700; font-size: 8.6pt; letter-spacing: 0.08em; }
  .head .part { margin-top: 2.2mm; font-size: 8.2pt; letter-spacing: 0.1em; }
  .rule { height: 0; border-top: 1.5pt solid var(--ink); margin: 1.4mm -2mm 0; }

  .foot { position: absolute; left: 16mm; right: 15mm; bottom: 8mm; }
  .foot .rule { margin: 0 -2mm 1.6mm; }
  .foot .sub { text-align: center; letter-spacing: 0.1em; font-size: 8.2pt; }
  .foot .line { display: flex; align-items: baseline; justify-content: space-between; margin-top: 2.2mm; font-size: 8.2pt; }
  .foot .fill { display: inline-block; border-bottom: 0.6pt solid var(--ink); text-align: center; padding: 0 1mm; font-size: 8.8pt; letter-spacing: 0.03em; }

  .opener { text-align: center; letter-spacing: 0.12em; margin: 3.4mm 0 2mm; line-height: 1.6; }

  .para { display: grid; grid-template-columns: 19mm 1fr; position: relative; }
  .para .num { letter-spacing: 0.08em; }
  .para h2, .para h3 { margin: 0 0 0.8mm; font: inherit; font-weight: 400; letter-spacing: 0.08em; }
  .para h3 { text-decoration: underline; text-underline-offset: 1.6pt; text-decoration-thickness: 0.5pt; letter-spacing: 0.06em; }
  .para p { margin: 0 0 1mm; text-indent: 9mm; text-align: left; }
  .para p.flush { text-indent: 0; }
  .para p.tight { margin-bottom: 0.4mm; }
  .changebar { position: absolute; left: -9mm; width: 1.3mm; background: var(--ink); }
  .nowrap { white-space: nowrap; }

  figure { margin: 1.6mm 0 0; }
  figure svg { display: block; width: 100%; height: auto; }
  figcaption { text-align: center; margin-top: 0.6mm; letter-spacing: 0.07em; }
  figcaption .n { margin-right: 3mm; }

  svg text { font-family: var(--leroy); fill: var(--ink); letter-spacing: 0.04px; }
  svg .o    { fill: none; stroke: var(--ink); stroke-width: 0.42; stroke-linejoin: round; stroke-linecap: round; }
  svg .of   { fill: var(--paper); stroke: var(--ink); stroke-width: 0.42; stroke-linejoin: round; }
  svg .t    { fill: none; stroke: var(--ink); stroke-width: 0.17; stroke-linecap: round; }
  svg .hid  { fill: none; stroke: var(--ink); stroke-width: 0.22; stroke-dasharray: 1.3 0.7; }
  svg .cl   { fill: none; stroke: var(--ink); stroke-width: 0.16; stroke-dasharray: 5 0.8 0.9 0.8; }
  svg .cut  { fill: none; stroke: var(--ink); stroke-width: 0.5; stroke-dasharray: 5 1 1 1; }
  svg .ld   { fill: none; stroke: var(--ink); stroke-width: 0.16; marker-end: url(#nh-leader); }
  svg .dim  { fill: none; stroke: var(--ink); stroke-width: 0.16; marker-start: url(#nh-dim); }
  svg .w    { fill: none; stroke: var(--ink); stroke-width: 0.3; stroke-linejoin: round; }
  svg .wa   { fill: none; stroke: var(--ink); stroke-width: 0.3; stroke-linejoin: round; marker-end: url(#nh-arrow); }
  svg .box  { fill: var(--paper); stroke: var(--ink); stroke-width: 0.45; }
  svg .panel{ fill: none; stroke: var(--ink); stroke-width: 0.3; stroke-dasharray: 2 1; }
  svg .ev   { fill: none; stroke: var(--ink); stroke-width: 0.18; stroke-dasharray: 1 0.7; }
  svg .vid  { fill: url(#nh-hatch); stroke: var(--ink); stroke-width: 0.35; }
  svg .aud  { fill: var(--paper); stroke: var(--ink); stroke-width: 0.35; }
  svg .gap  { fill: var(--paper); stroke: var(--ink); stroke-width: 0.35; stroke-dasharray: 0.6 0.5; }
  svg .grain{ fill: url(#nh-dots); stroke: var(--ink); stroke-width: 0.35; }
  svg .dot  { fill: var(--ink); }
  svg .lbl   { font-size: 2.35px; }
  svg .lbl-s { font-size: 2.05px; }
  svg .lbl-b { font-size: 2.5px; font-family: "Routed Gothic", sans-serif; }
  svg .code  { font-size: 2.4px; font-family: "Routed Gothic", sans-serif; }

  .lower { display: grid; grid-template-columns: 1fr 64mm; column-gap: 6mm; margin-top: 2.8mm; }
  .tcap { text-align: center; letter-spacing: 0.07em; margin: 0 0 0.8mm; }
  table { width: 100%; border-collapse: collapse; font-size: 7.3pt; line-height: 1.2; }
  th, td { border: 0.6pt solid var(--ink); padding: 0.35mm 1.6mm; text-align: left; vertical-align: top; font-weight: 400; }
  thead th { text-align: center; letter-spacing: 0.1em; padding: 0.5mm 1.6mm; }
  td.v { white-space: nowrap; }
  table.dense { font-size: 6.9pt; line-height: 1.16; }
  table.dense th, table.dense td { padding: 0.24mm 1.2mm; }

  .notice { text-align: left; margin-bottom: 1.8mm; }
  .notice .tag { display: block; text-align: center; letter-spacing: 0.18em; font-weight: 700; text-decoration: underline; text-underline-offset: 1.6pt; text-decoration-thickness: 0.6pt; margin-bottom: 0.8mm; }
  .notice p { margin: 0; font-size: 7.4pt; line-height: 1.28; }

  .card { border: 0.8pt solid var(--ink); font-family: var(--selectric); font-size: 7.1pt; line-height: 1.3; letter-spacing: 0; }
  .card .bar { background: var(--ink); color: var(--paper); font-weight: 700; padding: 0.5mm 1.8mm; display: flex; justify-content: space-between; }
  .card ol { list-style: none; margin: 0; padding: 0.8mm 1.8mm 1mm; }
  .card li { display: grid; grid-template-columns: 3.2mm 1fr; white-space: pre; }

  .tab { position: absolute; right: 0; top: 112mm; width: 8.5mm; height: 17mm; background: var(--ink); color: var(--paper);
    font-family: "Routed Gothic", sans-serif; font-size: 8pt; letter-spacing: 0.08em; display: flex; align-items: center; justify-content: center; }

  /* ---------- additions for this handbook ---------- */
  .cover-title { text-align: center; margin-top: 22mm; }
  .cover-title .kicker { font-family: var(--leroy); font-size: 9pt; letter-spacing: 0.28em; }
  .cover-title .main { font-family: var(--leroy); font-weight: 700; font-size: 27pt; letter-spacing: 0.10em; line-height: 1.15; margin-top: 5mm; }
  .cover-title .sub { font-family: var(--leroy); font-size: 11pt; letter-spacing: 0.20em; margin-top: 4mm; }
  .cover-rule { border-top: 2.2pt solid var(--ink); margin: 8mm 8mm 0; }
  .cover-abstract { margin: 7mm 12mm 0; text-align: left; }
  .cover-abstract p { text-indent: 0; margin: 0 0 2.2mm; font-size: 9pt; line-height: 1.4; }
  .cover-meta { margin: 7mm 12mm 0; }
  .cover-meta table { font-size: 7.8pt; }
  .cover-meta td { padding: 0.8mm 2mm; }

  .listing { font-family: var(--selectric); font-size: 6.8pt; line-height: 1.34; letter-spacing: 0;
    border: 0.6pt solid var(--ink); padding: 1.4mm 2mm; margin: 1.2mm 0 1.6mm; white-space: pre; overflow: hidden; }
  .listing .c { font-style: italic; }
  .caption { text-align: center; letter-spacing: 0.07em; margin: 0.4mm 0 1.4mm; font-size: 7.6pt; }
  .twocol { display: grid; grid-template-columns: 1fr 1fr; column-gap: 6mm; }
  .threecol { display: grid; grid-template-columns: 1fr 1fr 1fr; column-gap: 4mm; }
  .kv { width: 100%; }
  .note { font-size: 7.2pt; line-height: 1.28; }
  ul.tight, ol.tight { margin: 0.4mm 0 1mm 0; padding-left: 4.5mm; }
  ul.tight li, ol.tight li { margin-bottom: 0.5mm; }
  .center { text-align: center; }
"""

DEFS = r"""
<svg width="0" height="0" style="position:absolute" aria-hidden="true">
  <defs>
    <marker id="nh-leader" viewBox="0 0 6 4" refX="5.6" refY="2" markerWidth="2.1" markerHeight="1.05" markerUnits="userSpaceOnUse" orient="auto" preserveAspectRatio="none"><path d="M0,0 L6,2 L0,4 Z" fill="#000"/></marker>
    <marker id="nh-arrow" viewBox="0 0 6 4" refX="5.6" refY="2" markerWidth="2.4" markerHeight="1.3" markerUnits="userSpaceOnUse" orient="auto" preserveAspectRatio="none"><path d="M0,0 L6,2 L0,4 Z" fill="#000"/></marker>
    <marker id="nh-dim" viewBox="0 0 6 4" refX="0" refY="2" markerWidth="2.2" markerHeight="0.95" markerUnits="userSpaceOnUse" orient="auto" preserveAspectRatio="none"><path d="M6,0 L0,2 L6,4 Z" fill="#000"/></marker>
    <pattern id="nh-hatch" width="1.1" height="1.1" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="1.1" stroke="#000" stroke-width="0.2"/></pattern>
    <pattern id="nh-bp" width="1.4" height="1.4" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><rect width="0.7" height="1.4" fill="#000"/></pattern>
    <pattern id="nh-dots" width="1.3" height="1.3" patternUnits="userSpaceOnUse"><circle cx="0.32" cy="0.32" r="0.15" fill="#000"/><circle cx="0.97" cy="0.97" r="0.15" fill="#000"/></pattern>
  </defs>
</svg>
"""

FIT = r"""
<script>
  document.fonts.ready.then(() => {
    const page = document.querySelector('.page')
    const foot = page.querySelector('.foot')
    let bottom = 0
    for (const el of page.children) {
      if (el === foot || el.classList.contains('tab')) continue
      bottom = Math.max(bottom, el.getBoundingClientRect().bottom)
    }
    const free = (foot.getBoundingClientRect().top - bottom) * 25.4 / 96
    document.documentElement.dataset.fit = free >= 0 ? `ok, ${free.toFixed(1)} mm free above the footer` : `OVERFLOW by ${(-free).toFixed(1)} mm`
  })
</script>
"""

# out file, fragment, section opener, subsystem, tab, page label, footer name
PAGES_SPEC = [
    ("1-1", "01-cover", "", "GENERAL", "GEN", "1-1", "HANDBOOK RECORD"),
    ("1-2", "02-reading-map", "SECTION 1 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 1.1", "SCOPE AND READING MAP", "GEN", "1-2", "GENERAL"),
    ("1-3", "03-system-purpose", "SECTION 1 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 1.2", "SYSTEM PURPOSE AND BOUNDARIES", "GEN", "1-3", "GENERAL"),
    ("1-4", "04-architecture", "SECTION 1 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 1.3", "ARCHITECTURE AND DEPLOYMENT", "GEN", "1-4", "GENERAL"),
    ("2-1", "05-stack-backend", "SECTION 2 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 2.1", "COMPUTING EQUIPMENT AND SOFTWARE", "STK", "2.1-1", "TECHNOLOGY STACK"),
    ("2-2", "06-stack-frontend", "SECTION 2 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 2.1 (CONT.)", "COMPUTING EQUIPMENT AND SOFTWARE", "STK", "2.1-2", "TECHNOLOGY STACK"),
    ("3-1", "07-ingestion", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.1", "FILE INGESTION", "ING", "3.1-1", "SUBSYSTEM 1"),
    ("3-2", "08-ast", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.2", "SYMBOL EXTRACTION", "AST", "3.2-1", "SUBSYSTEM 2"),
    ("3-3", "09-graph", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.3", "DEPENDENCY GRAPH", "DEP", "3.3-1", "SUBSYSTEM 3"),
    ("3-4", "10-complexity", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.4", "COMPLEXITY SCORING", "CPX", "3.4-1", "SUBSYSTEM 4"),
    ("3-5", "11-rag", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.5", "CODE RETRIEVAL", "RAG", "3.5-1", "SUBSYSTEM 5"),
    ("3-6", "12-explainability", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.6", "EXPLAINABILITY", "EXP", "3.6-1", "SUBSYSTEM 6"),
    ("3-7", "13-docgen", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.7", "DOCUMENT GENERATION", "DOC", "3.7-1", "SUBSYSTEM 7"),
    ("3-8", "14-api", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.8", "WEB API AND JOB CONTROL", "API", "3.8-1", "SUBSYSTEM 8"),
    ("3-9", "15-store-queue", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.8 (CONT.)", "STORE, QUEUE AND WORKER", "API", "3.8-2", "SUBSYSTEM 8"),
    ("3-10", "16-frontend", "SECTION 3 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 3.9", "OPERATOR DISPLAY", "WEB", "3.9-1", "SUBSYSTEM 9"),
    ("4-1", "17-flow", "SECTION 4 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 4.1", "END-TO-END LOGIC FLOW", "FLW", "4.1-1", "OPERATION"),
    ("4-2", "18-failure", "SECTION 4 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 4.2", "STATE, ERRORS AND RETRIES", "FLW", "4.2-1", "OPERATION"),
    ("5-1", "19-files-backend", "SECTION 5 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 5.1", "FILE CATALOGUE: BACKEND", "CAT", "5.1-1", "EQUIPMENT LIST"),
    ("5-2", "20-files-tests", "SECTION 5 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 5.1 (CONT.)", "FILE CATALOGUE: TESTS AND RECORDS", "CAT", "5.1-2", "EQUIPMENT LIST"),
    ("5-3", "21-files-frontend", "SECTION 5 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 5.2", "FILE CATALOGUE: FRONTEND AND ASSETS", "CAT", "5.2-1", "EQUIPMENT LIST"),
    ("6-1", "22-decisions", "SECTION 6 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 6.1", "DESIGN DECISIONS", "DEC", "6.1-1", "DESIGN RECORD"),
    ("6-2", "23-ledger", "SECTION 6 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 6.2", "DECISION LEDGER AND DOCUMENT DRIFT", "DEC", "6.2-1", "DESIGN RECORD"),
    ("7-1", "24-running", "SECTION 7 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 7.1", "STARTING AND OPERATING", "OPS", "7.1-1", "CHECKOUT"),
    ("7-2", "25-testing", "SECTION 7 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 7.2", "TEST AND VERIFICATION PROGRAM", "OPS", "7.2-1", "CHECKOUT"),
    ("8-1", "26-defects", "SECTION 8 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 8.1", "KNOWN DEFECTS AND LIMITATIONS", "VER", "8.1-1", "APPENDIX"),
    ("8-2", "27-verification", "SECTION 8 &nbsp;&nbsp;&middot;&nbsp;&nbsp; SUBSECTION 8.2", "SOURCE VERIFICATION AND OPEN ITEMS", "VER", "8.2-1", "APPENDIX"),
]


def render(spec):
    out_name, frag_name, opener, subsystem, tab, page_label, footer_name = spec
    body = (PAGES / f"{frag_name}.html").read_text(encoding="utf-8")
    body = re.sub(r"<!--.*?-->\s*", "", body, flags=re.S)
    opener_html = f'<div class="opener">{opener}<br>\n    {subsystem}</div>' if opener else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{DOC} {HANDBOOK}, page {page_label}</title>
<style>{CSS}</style>
</head>
<body>
{DEFS}
<div class="page">

  <header class="head">
    <div class="doc">{DOC}</div>
    <div class="title">{HANDBOOK}</div>
    <div class="part">{PART}</div>
    <div class="rule"></div>
  </header>

  <div class="tab">{tab}</div>

  {opener_html}

{body}

  <footer class="foot">
    <div class="rule"></div>
    <div class="sub">{footer_name}</div>
    <div class="line">
      <span>Mission <span class="fill" style="width:20mm">&nbsp;</span></span>
      <span>Basic Date <span class="fill" style="width:30mm">{BASIC_DATE}</span></span>
      <span>Change Date <span class="fill" style="width:30mm">{CHANGE_DATE}</span></span>
      <span>Page <span class="fill" style="width:18mm">{page_label}</span></span>
    </div>
  </footer>

</div>
{FIT}
</body>
</html>
"""


def main():
    missing = [s[1] for s in PAGES_SPEC if not (PAGES / f"{s[1]}.html").exists()]
    if missing:
        print("missing fragments:", missing)
        return 1
    for spec in PAGES_SPEC:
        (OUT / f"{spec[0]}.html").write_text(render(spec), encoding="utf-8")
        print("wrote", spec[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

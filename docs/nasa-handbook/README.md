# Project Gnosis Operations Handbook

A 27-page Apollo-style systems-data handbook for this repository, built from the
working tree at commit `4135a25` (16 October 2026). It describes the pipeline,
the API and store, the frontend, every repository-owned file, the design
decisions, the documented drift, and the known defects.

## Read this

| File | What it is |
| --- | --- |
| `Project-Gnosis-Operations-Handbook.pdf` | The assembled 27-page document, with PDF bookmarks. Start here. |
| `png/<page>.png` | One preview image per page (`1-1` … `8-2`), in reading order. |
| `pdf/<page>.pdf` | One single-page PDF per page, same order. |
| `<page>.html` | Standalone, editable HTML for that page (fonts and CSS inlined). |
| `build/pages/*.html` | Editable body fragments; the source of truth for page content. |
| `build/build.py` | Supplies the shared header, thumb tab, footer, CSS and page metadata. |

Page labels follow the handbook's own scheme: `2.1-1`, `3.8-2`, `8.2-1`.
The cover (`1-1`) carries the contents table and the reading map is `1-2`.

## Rebuild

Requires Python 3.11+ and Chrome, plus the `nasa-handbook` skill's render
scripts at `~/.agents/skills/nasa-handbook/scripts/`. From this directory:

```sh
python build/build.py                 # regenerate the 27 standalone HTML files
sh build/render-all.sh                # print each page to pdf/ and png/
sh build/check-all.sh                 # A4, colour count, fonts, page count for pdf/*.pdf
uv run --with pymupdf python build/assemble.py   # merge into the single PDF
```

`render-all.sh` calls `build.py` first, so the HTML is never stale. The render
script prints `fit: ok` with the free space above the footer; any page that
overflows is reported and must be edited before assembly.

Two inspection helpers are kept because they were used for verification:
`build/contact.py` (thumbnail contact sheet) and `build/render_page.py`
(one page of the merged PDF at a chosen dpi). `build/audit_lines.py` re-counts
every catalogue row against the working tree.

## Conventions used in the document

- **Line counts** in the catalogue are non-empty lines: truly empty lines are
  excluded, whitespace-only lines are counted.
- **Evidence marks**: `OBSERVED` = read from executable source or a test run in
  this tree; `DOCUMENTED` = asserted by a repository record; `INFERRED` = this
  handbook's reading of structure. Where a record and the code disagree, the
  code is described and the disagreement is quoted in section 6.2.
- **Dashed boxes** in figures mark a declared-but-unused path, an absent
  record, or an unreachable state — never a normal flow.
- **Secrets** are excluded. Only variable *names* from `.env.example` appear.
- No deployed environment, live service, paid model call or remote repository
  was inspected. Section 7.1.2.1 lists exactly which commands were executed.

## Verification performed

- 476 tests passed in 20.40 s (`pytest tests -q`); `--collect-only` confirms
  476 cases across 15 files.
- `run.py --help` exits 0 with the documented options.
- `uvicorn src.api.main:app --port 8011` started; `GET /health` returned
  `status ok`, version `1.0.0`, `redis_connected false`,
  `queue_mode local_threadpool`; the listener was then stopped.
- All 27 pages: A4 (209.9 × 297.0 mm), two colours, expected fonts, one page
  each. The merged PDF is 27 pages with 31 bookmark entries and page text
  identical to the single-page files.

## Scope and known limits

The handbook is a reading of the tree, not a certification. It records
16 defects and 7 open items (section 8) rather than fixing them. Application
code, tests and the existing repository documents were not modified; this
directory is the only output.

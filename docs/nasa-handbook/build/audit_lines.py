"""Compare stated line counts in the catalogue tables with the working tree."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PAGES = Path(__file__).resolve().parent / "pages"

ROW = re.compile(
    r"<tr><td>(.*?)</td><td class=\"v\">([0-9,]+)</td>(?:<td class=\"v\">([0-9,]+)</td>)?"
)


def actual_lines(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return sum(1 for line in text.splitlines() if line)


def check(frag, table_index, line_col, prefix=""):
    text = (PAGES / frag).read_text(encoding="utf-8")
    tables = re.findall(r"<table class=\"dense\">(.*?)</table>", text, re.S)
    body = tables[table_index]
    print(f"== {frag} table {table_index + 1}")
    for m in ROW.finditer(body):
        name = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        nums = [g for g in m.groups()[1:] if g]
        if len(nums) <= line_col:
            continue
        stated = int(nums[line_col].replace(",", ""))
        rel = prefix + name
        path = ROOT / rel
        if not path.is_file():
            continue
        actual = actual_lines(path)
        flag = "" if actual == stated else f"  <-- actual {actual}"
        print(f"  {'ok ' if not flag else 'BAD'} {name:42} {stated}{flag}")


check("19-files-backend.html", 0, 0, "src/")
check("20-files-tests.html", 0, 1, "tests/")
check("20-files-tests.html", 1, 0)
check("21-files-frontend.html", 0, 0, "frontend/")

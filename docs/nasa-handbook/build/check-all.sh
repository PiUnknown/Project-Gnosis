#!/bin/sh
cd '/c/Users/Om/Desktop/Projects/Project Gnosis/docs/nasa-handbook' || exit 1
for f in 1-1 1-2 1-3 1-4 2-1 2-2 3-1 3-2 3-3 3-4 3-5 3-6 3-7 3-8 3-9 3-10 4-1 4-2 5-1 5-2 5-3 6-1 6-2 7-1 7-2 8-1 8-2; do
  printf '%s: ' "$f"
  uv run --no-project --with pymupdf python /c/Users/Om/.agents/skills/nasa-handbook/scripts/check.py "pdf/$f.pdf" --pages 1 2>&1 | tr '\n' ' '
  echo
done

#!/bin/sh
export CHROME='/c/Program Files/Google/Chrome/Application/chrome.exe'
cd '/c/Users/Om/Desktop/Projects/Project Gnosis/docs/nasa-handbook' || exit 1
mkdir -p pdf png
python build/build.py > /dev/null || exit 1
for f in 1-1 1-2 1-3 1-4 2-1 2-2 3-1 3-2 3-3 3-4 3-5 3-6 3-7 3-8 3-9 3-10 4-1 4-2 5-1 5-2 5-3 6-1 6-2 7-1 7-2 8-1 8-2; do
  echo "== $f"
  sh /c/Users/Om/.agents/skills/nasa-handbook/scripts/render.sh "$f.html" | tail -1
  mv -f "$f.pdf" pdf/ && mv -f "$f.png" png/
done

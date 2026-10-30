#!/bin/sh
export CHROME='/c/Program Files/Google/Chrome/Application/chrome.exe'
cd '/c/Users/Om/Desktop/Projects/Project Gnosis/docs/nasa-handbook' || exit 1
mkdir -p pdf png
python build/build.py > /dev/null || exit 1
for f in "$@"; do
  echo "== $f"
  sh /c/Users/Om/.agents/skills/nasa-handbook/scripts/render.sh "$f.html" | tail -1
  mv -f "$f.pdf" pdf/ && mv -f "$f.png" png/
done

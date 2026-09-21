#!/usr/bin/env bash
# Does this change set need the Python job? (OPS-0002)
#
# Reads changed paths on stdin, one per line, and prints `true` or `false`.
# `false` only when *every* path is one the Python suite cannot observe: the
# web app, the voxel package, prose, tracked measurements. Anything else —
# a decision record at any depth, contracts, scripts, the workflow itself —
# prints `true`.
#
# Deliberately biased towards running: an unrecognised path is a reason to
# run the tests, not to skip them. The cost of a wrong `true` is four minutes;
# the cost of a wrong `false` is a merged regression.
set -euo pipefail

seen=0
while IFS= read -r path; do
  [ -n "$path" ] || continue
  seen=1
  case "$path" in
    apps/web/*|packages/world/*|docs/*|ops/*) ;;
    */*) echo true; exit 0 ;;
    *.md) ;;
    *) echo true; exit 0 ;;
  esac
done

# No paths at all (an empty diff, or an event with no base to compare
# against) means we cannot prove the change is web-only. Run it.
if [ "$seen" -eq 0 ]; then
  echo true
else
  echo false
fi

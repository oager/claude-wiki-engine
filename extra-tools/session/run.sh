#!/bin/sh
# ~/.claude/tools/session/run.sh
# Runs a session tool from this folder with the first Python 3.11+ that works: python3, else python.
# (On Windows, python3 is often the Microsoft Store stub.) The tool runs once; its exit code is passed through.
#   sh ~/.claude/tools/session/run.sh close.py push --message "..." --files ...
# Every code line ends in '#': in a CRLF checkout (core.autocrlf on Windows) the '\r' then lands in a comment.
[ $# -gt 0 ] || { echo "usage: sh run.sh <tool.py> [args...]" >&2; exit 2; } #
case "$0" in */*) dir="${0%/*}" ;; *) dir=. ;; esac #
tool="$dir/$1"; shift #
for p in python3 python; do "$p" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null && exec "$p" "$tool" "$@"; done #
echo "run.sh: session tools need Python 3.11+ as python3 or python on PATH" >&2 #
exit 127 #

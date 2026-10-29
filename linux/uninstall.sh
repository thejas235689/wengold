#!/bin/sh
# WENGOLD — uninstaller. Removes exactly what install.sh created and nothing else.
set -eu

APP=wengold
PREFIX=${PREFIX:-}
SYSTEM=0

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --system) SYSTEM=1; shift ;;
        -h|--help) sed -n '2,3p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$PREFIX" ]; then
    if [ "$SYSTEM" = 1 ]; then PREFIX=/usr/local; else PREFIX="$HOME/.local"; fi
fi

removed=0
for p in \
    "$PREFIX/bin/$APP" \
    "$PREFIX/share/applications/$APP.desktop" \
    "$PREFIX/share/icons/hicolor/scalable/apps/$APP.svg"
do
    if [ -e "$p" ]; then rm -f "$p"; printf '  removed %s\n' "$p"; removed=$((removed+1)); fi
done

LIB="$PREFIX/share/$APP"
if [ -d "$LIB" ]; then rm -rf "$LIB"; printf '  removed %s\n' "$LIB"; removed=$((removed+1)); fi

if [ "$removed" = 0 ]; then
    printf '  nothing to remove under %s\n' "$PREFIX"
else
    printf '  %d item(s) removed. Your project data and .tof/ directories are untouched.\n' "$removed"
fi

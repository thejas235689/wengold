#!/bin/sh
# WENGOLD native Linux desktop installer: isolated dependencies, no root.
# Usage: sh linux/install-desktop.sh [--prefix DIR] [--python PYTHON]
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
PREFIX="${PREFIX:-$HOME/.local}"
PREFERRED="${WENGOLD_PYTHON:-}"
WITH_FORMAL=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --prefix)
            [ "$#" -ge 2 ] || { echo "--prefix needs a directory" >&2; exit 2; }
            PREFIX="$2"; shift 2 ;;
        --python)
            [ "$#" -ge 2 ] || { echo "--python needs a Python executable" >&2; exit 2; }
            PREFERRED="$2"; shift 2 ;;
        --formal) WITH_FORMAL=1; shift ;;
        --help)
            echo "Usage: sh linux/install-desktop.sh [--prefix DIR] [--python PYTHON] [--formal]"
            exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

PY=""
for candidate in "$PREFERRED" python3.13 python3.12 python3.11 python3; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
        PY=$(command -v "$candidate")
        break
    fi
done
[ -n "$PY" ] || {
    echo "ERROR: Python 3.11+ is required. On Rocky 9: sudo dnf install python3.11 python3.11-pip" >&2
    exit 1
}

# Avoid placing an isolated environment inside the application data copied by
# install.sh and removed by uninstall.sh. Reusing an existing venv is supported.
VENV="$PREFIX/share/wengold-venv"
"$PY" -m venv "$VENV" || {
    echo "ERROR: failed to create venv. Install python3.11-venv on Debian/Ubuntu." >&2
    exit 1
}
VPY="$VENV/bin/python"
"$VPY" -m pip --version >/dev/null 2>&1 || {
    echo "ERROR: pip missing from venv. Install python3.11-venv / ensurepip." >&2
    exit 1
}
echo "Installing isolated WENGOLD Qt dependencies into $VENV"
if [ "$WITH_FORMAL" = 1 ]; then
    "$VPY" -m pip install 'PyQt6>=6.6,<7' 'pyslang>=9' 'numpy>=1.24' 'z3-solver>=4.12'
else
    "$VPY" -m pip install 'PyQt6>=6.6,<7' 'pyslang>=9' 'numpy>=1.24'
fi
QT_QPA_PLATFORM=offscreen "$VPY" -c 'from PyQt6 import QtWidgets; assert QtWidgets.QApplication'

# Use the exact environment that owns Qt to install the launcher, rather than
# whichever python3 the OS chooses for its default Python installation.
WENGOLD_PYTHON="$VPY" sh "$HERE/install.sh" --prefix "$PREFIX"
"$PREFIX/bin/wengold" --version
echo "Installed WENGOLD native desktop. Launch with:"
echo "  $PREFIX/bin/wengold desktop --native /path/to/rtl"

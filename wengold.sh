#!/bin/sh
# WENGOLD — run without installing anything.
#
# The graph, the kernel, the front-ends and the CLI are standard library only, so
# WENGOLD needs no pip packages to work. Only the extras are optional:
#
#   pyslang     a real SystemVerilog parse instead of the bounded regex fallback
#   z3-solver   the formal loop
#   numpy       `wengold learn` and `wengold spec-from-text`
#   PyQt6       the native desktop window
#
# So if installing tools is failing, this script is the way in: no pip, no root, no
# package manager, nothing written outside the checkout.
#
#   ./wengold.sh --version
#   ./wengold.sh doctor
#   ./wengold.sh index path/to/rtl
#   ./wengold.sh cdc path/to/file.sv
#
# To find a suitable interpreter it tries, in order: $WENGOLD_PYTHON, python3.13,
# python3.12, python3.11, python3.
set -eu

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

say()  { printf '  %s\n' "$*"; }
fail() {
    printf '\n  error: %s\n\n' "$*" >&2
    printf '  WENGOLD needs Python 3.11 or newer. On Rocky/RHEL 9 the system\n' >&2
    printf '  python3 is 3.9, so install a newer one alongside it:\n\n' >&2
    printf '      sudo dnf install -y python3.11\n\n' >&2
    printf '  Then run this again. Do not replace the system python3 — dnf runs on it.\n\n' >&2
    exit 1
}

# ---- find an interpreter that is new enough ------------------------------
PY=""
for cand in ${WENGOLD_PYTHON:-} python3.13 python3.12 python3.11 python3; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if "$cand" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
        PY=$(command -v "$cand")
        break
    fi
done

[ -n "$PY" ] || fail "no Python 3.11 or newer found on PATH"

VER=$("$PY" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])')

# ---- what is optional, and what its absence costs ------------------------
have() { "$PY" -c "import $1" >/dev/null 2>&1 && echo yes || echo no; }

if [ "${1:-}" = "--where" ]; then
    say "python  $PY ($VER)"
    say "repo    $HERE"
    say ""
    say "optional        present  what its absence costs"
    for row in \
        "pyslang:$(have pyslang):a real SystemVerilog parse; without it the bounded regex front-end finds fewer modules" \
        "z3:$(have z3):the formal loop" \
        "numpy:$(have numpy):learn and spec-from-text" \
        "PyQt6.QtWidgets:$(have PyQt6.QtWidgets):the native window; the browser fallback still works"
    do
        mod=${row%%:*}; rest=${row#*:}; st=${rest%%:*}; cost=${rest#*:}
        name=$(printf '%s' "$mod" | sed 's/PyQt6.QtWidgets/PyQt6/')
        printf '  %-14s  %-7s  %s\n' "$name" "$st" "$cost"
    done
    say ""
    say "none of these is required to run wengold."
    exit 0
fi

# ---- run it --------------------------------------------------------------
# PYTHONPATH rather than an install: nothing is written, and removing the checkout
# removes every trace of WENGOLD.
PYTHONPATH="$HERE${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

exec "$PY" -m wengold.cli "$@"

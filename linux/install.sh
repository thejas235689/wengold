#!/bin/sh
# WENGOLD — Linux installer.
#
# Installs the desktop app for the current user, with no root and no package
# manager. Everything lands under $PREFIX (default ~/.local), which is on the
# XDG search path, so the app appears in the launcher without a logout.
#
#   ./linux/install.sh              # per-user, ~/.local
#   ./linux/install.sh --prefix DIR # somewhere else
#   sudo ./linux/install.sh --system # /usr/local, all users
#   ./linux/install.sh --check      # report what is missing, change nothing
#   ./linux/install.sh --diagnose   # everything needed to debug a failed install
#
# It is a shell script rather than a Makefile because a Linux user with a
# terminal should be able to read every line of what it does to their home
# directory before running it.
set -eu

APP=wengold
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname -- "$HERE")

PREFIX=${PREFIX:-}
SYSTEM=0
CHECK=0
DIAGNOSE=0
WITH_QT=1

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --system) SYSTEM=1; shift ;;
        --no-qt) WITH_QT=0; shift ;;
        --check) CHECK=1; shift ;;
        --diagnose) DIAGNOSE=1; shift ;;
        -h|--help) sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "unknown option: $1" >&2; exit 2 ;;
    esac
done

if [ -z "$PREFIX" ]; then
    if [ "$SYSTEM" = 1 ]; then PREFIX=/usr/local; else PREFIX="$HOME/.local"; fi
fi

BIN="$PREFIX/bin"
APPS="$PREFIX/share/applications"
ICONS="$PREFIX/share/icons/hicolor/scalable/apps"
LIB="$PREFIX/share/$APP"

say()  { printf '  %s\n' "$*"; }
fail() { printf '  error: %s\n' "$*" >&2; exit 1; }

# Explicit installed interpreter wins; otherwise select a suitable 3.11+.
# Rocky 9 ships python3=3.9, but may have python3.11 installed alongside it.
PY=""
for candidate in "${WENGOLD_PYTHON:-}" python3.13 python3.12 python3.11 python3; do
    [ -n "$candidate" ] || continue
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        PY=$(command -v "$candidate")
        break
    fi
done
[ -n "$PY" ] || fail "Python 3.11+ is required. On Rocky 9: sudo dnf install python3.11 python3.11-pip"

PYVER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
say "python3 $PYVER at $PY"

# pyproject.toml requires >=3.11. Without this check a 3.9 interpreter installs
# and then fails at "the package did not import", which says nothing about why.
if ! "$PY" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)'; then
    printf '\n  error: WENGOLD needs Python 3.11 or newer; this is %s at %s\n\n' \
        "$PYVER" "$PY" >&2
    printf '  On Rocky/RHEL 9 the system python3 is 3.9. Install a newer one\n' >&2
    printf '  alongside it — do NOT replace the system python3, dnf runs on it:\n\n' >&2
    printf '      sudo dnf install -y python3.11 python3.11-pip\n' >&2
    printf '      mkdir -p ~/.local/bin-py\n' >&2
    printf '      ln -sf /usr/bin/python3.11 ~/.local/bin-py/python3\n' >&2
    printf '      PATH="$HOME/.local/bin-py:$PATH" sh linux/install.sh\n\n' >&2
    printf '  See docs/INSTALL-ROCKY.md.\n' >&2
    exit 1
fi

# numpy is a declared runtime dependency (`wengold learn`, `spec-from-text`).
# The package imports without it, so a missing numpy is not fatal here — but
# saying so now beats a traceback three commands later.
NUMPY_OK=1
"$PY" -c 'import numpy' >/dev/null 2>&1 || NUMPY_OK=0
[ "$NUMPY_OK" = 1 ] || say "numpy: MISSING — \`$PY -m pip install --user numpy\`"

# ---- what is missing -----------------------------------------------------
QT_OK=1
if ! "$PY" -c 'import PyQt6.QtWidgets' >/dev/null 2>&1; then
    QT_OK=0
fi

if [ "$DIAGNOSE" = 1 ]; then
    say "distro"
    [ -r /etc/os-release ] && . /etc/os-release && say "  ${PRETTY_NAME:-unknown}"
    say "  kernel: $(uname -srm)"
    say "python"
    say "  python3:    $PY ($PYVER)"
    "$PY" -c 'import sys; print("  ok for 3.11+:", sys.version_info >= (3,11))' 2>/dev/null || true
    for m in pip numpy PyQt6.QtWidgets; do
        if "$PY" -c "import $m" >/dev/null 2>&1; then say "  $m: present"
        else say "  $m: MISSING"; fi
    done
    say "  which pip:  $(command -v pip3 || command -v pip || echo none)"
    say "repo"
    say "  script:     $HERE"
    say "  package:    $REPO/$APP ($([ -d "$REPO/$APP" ] && echo present || echo MISSING))"
    say "  prefix:     $PREFIX"
    say "  writable:   $([ -w "$(dirname "$PREFIX")" ] && echo yes || echo no)"
    say "shell"
    say "  PATH has ~/.local/bin: $(case ":$PATH:" in *":$HOME/.local/bin:"*) echo yes;; *) echo no;; esac)"
    exit 0
fi

if [ "$CHECK" = 1 ]; then
    say "PyQt6 (native window): $([ "$QT_OK" = 1 ] && echo present || echo MISSING)"
    say "prefix: $PREFIX"
    say "repo:   $REPO"
    [ "$QT_OK" = 1 ] || say "For a complete native installation run: sh linux/install-desktop.sh"
    exit 0
fi

# ---- the package itself --------------------------------------------------
if [ ! -d "$REPO/$APP" ]; then
    fail "no $APP/ package next to linux/ — run this from a checkout of the repo"
fi
mkdir -p "$LIB"
# copy rather than symlink: a symlink into the checkout breaks the moment the
# user moves or deletes the clone, and the launcher would then fail with a
# traceback instead of saying what happened
rm -rf "$LIB/$APP"
cp -R "$REPO/$APP" "$LIB/$APP"
say "package -> $LIB/$APP"

# ---- the launcher --------------------------------------------------------
mkdir -p "$BIN"
cat > "$BIN/$APP" <<LAUNCHER
#!/bin/sh
# WENGOLD launcher — written by linux/install.sh
#
# This runs the CLI, not the GUI. It used to exec $APP.native, which meant an
# installed copy answered every subcommand by opening a window: \`wengold --version\`
# and \`wengold cdc file.sv\` both tried to start Qt. \`wengold desktop\` is the way
# into the GUI, and the .desktop entry below calls it directly.
export PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PY" -m $APP.cli "\$@"
LAUNCHER
chmod 0755 "$BIN/$APP"
say "launcher -> $BIN/$APP"

# ---- icon and desktop entry ---------------------------------------------
mkdir -p "$APPS" "$ICONS"
cp "$HERE/wengold.svg" "$ICONS/$APP.svg"
say "icon -> $ICONS/$APP.svg"

# Exec takes the absolute launcher path. An unquoted path with spaces in it is
# the classic way a .desktop entry silently stops working.
# The menu entry starts the window, not the CLI — that is the one place the GUI is
# the right entry point.
sed -e "s|@BIN@|$BIN/$APP desktop --native|g" \
    -e "s|@ICON@|$APP|g" \
    "$HERE/wengold.desktop.in" > "$APPS/$APP.desktop"
chmod 0644 "$APPS/$APP.desktop"
say "desktop entry -> $APPS/$APP.desktop"

# ---- make it visible without a logout -----------------------------------
# Best effort: these tools are absent on minimal systems and their absence is
# not an installation failure.
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS" >/dev/null 2>&1 || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t "$PREFIX/share/icons/hicolor" >/dev/null 2>&1 || true
fi

# ---- verify --------------------------------------------------------------
# An installer that does not check its own result is a script that hopes.
# Check the thing the user will actually run, not just that the package imports.
# The old line ran the launcher with `|| true`, so a launcher that started a GUI
# instead of printing a version passed silently.
if ! PYTHONPATH="$LIB" "$PY" -c "import $APP; print($APP.__version__)" >/dev/null 2>&1; then
    fail "the package did not import after installation"
fi
VER=$(PYTHONPATH="$LIB" "$PY" -c "import $APP; print($APP.__version__)")
if ! OUT=$("$BIN/$APP" --version 2>&1); then
    printf '  error: the launcher failed:\n\n%s\n\n' "$OUT" >&2
    fail "installed, but \`$BIN/$APP --version\` does not work"
fi
case "$OUT" in
    *"$VER"*) ;;
    *) fail "launcher printed '$OUT', expected version $VER" ;;
esac
say "verified: $APP $VER — launcher answers --version"

if [ "$QT_OK" = 0 ]; then
    printf '\n  PyQt6 is not installed, so the native window cannot start.\n'
    printf '  Install it with:\n\n      %s -m pip install --user PyQt6\n\n' "$PY"
    printf '  The application-menu launcher requires PyQt6; install it to open Silicon Studio.\n'
else
    printf '\n  Installed. Launch it from your application menu, or run:\n\n'
    printf '      %s\n\n' "$BIN/$APP"
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) printf '  note: %s is not on your PATH. Add:\n\n' "$BIN"
       printf '      export PATH="%s:$PATH"\n\n' "$BIN" ;;
esac

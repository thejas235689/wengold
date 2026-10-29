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
WITH_QT=1

while [ $# -gt 0 ]; do
    case "$1" in
        --prefix) PREFIX=$2; shift 2 ;;
        --system) SYSTEM=1; shift ;;
        --no-qt) WITH_QT=0; shift ;;
        --check) CHECK=1; shift ;;
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

PY=$(command -v python3 || true)
[ -n "$PY" ] || fail "python3 is required and was not found on PATH"

PYVER=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
say "python3 $PYVER at $PY"

# ---- what is missing -----------------------------------------------------
QT_OK=1
if ! "$PY" -c 'import PyQt6.QtWidgets' >/dev/null 2>&1; then
    QT_OK=0
fi

if [ "$CHECK" = 1 ]; then
    say "PyQt6 (native window): $([ "$QT_OK" = 1 ] && echo present || echo MISSING)"
    say "prefix: $PREFIX"
    say "repo:   $REPO"
    [ "$QT_OK" = 1 ] || say "install it with: $PY -m pip install --user PyQt6"
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
export PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}"
exec "$PY" -m $APP.native "\$@"
LAUNCHER
chmod 0755 "$BIN/$APP"
say "launcher -> $BIN/$APP"

# ---- icon and desktop entry ---------------------------------------------
mkdir -p "$APPS" "$ICONS"
cp "$HERE/wengold.svg" "$ICONS/$APP.svg"
say "icon -> $ICONS/$APP.svg"

# Exec takes the absolute launcher path. An unquoted path with spaces in it is
# the classic way a .desktop entry silently stops working.
sed -e "s|@BIN@|$BIN/$APP|g" \
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
"$BIN/$APP" --version >/dev/null 2>&1 || true
if ! PYTHONPATH="$LIB" "$PY" -c "import $APP; print($APP.__version__)" >/dev/null 2>&1; then
    fail "the package did not import after installation"
fi
VER=$(PYTHONPATH="$LIB" "$PY" -c "import $APP; print($APP.__version__)")
say "verified: $APP $VER imports from $LIB"

if [ "$QT_OK" = 0 ]; then
    printf '\n  PyQt6 is not installed, so the native window cannot start.\n'
    printf '  Install it with:\n\n      %s -m pip install --user PyQt6\n\n' "$PY"
    printf '  Until then `%s desktop` falls back to a browser window.\n' "$APP"
else
    printf '\n  Installed. Launch it from your application menu, or run:\n\n'
    printf '      %s\n\n' "$BIN/$APP"
fi

case ":$PATH:" in
    *":$BIN:"*) ;;
    *) printf '  note: %s is not on your PATH. Add:\n\n' "$BIN"
       printf '      export PATH="%s:$PATH"\n\n' "$BIN" ;;
esac

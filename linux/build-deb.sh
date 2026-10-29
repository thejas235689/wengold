#!/bin/sh
# WENGOLD — build a Debian package.
#
#   sh linux/build-deb.sh            # writes wengold_<version>_all.deb
#   sudo dpkg -i wengold_*.deb       # then it is a normal system package
#   sudo apt remove wengold          # and it uninstalls like one
#
# `Architecture: all` because the package is pure Python: there is nothing to
# compile and no per-architecture build. PyQt6 is a *recommends*, not a depends —
# without it the app still starts, in a browser window, and a hard dependency
# would make the package uninstallable on a machine that has no Qt.
set -eu

APP=wengold
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(dirname -- "$HERE")
OUT=${OUT:-$REPO/dist}

[ -d "$REPO/$APP" ] || { echo "no $APP/ package next to linux/" >&2; exit 1; }

VERSION=$(cd "$REPO" && python3 -c "import $APP; print($APP.__version__)")
PKG="$APP"_"$VERSION"_all

say() { printf '  %s\n' "$*"; }
say "building $APP $VERSION"

STAGE="$REPO/build/deb-$VERSION"
rm -rf "$STAGE"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/$APP" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/doc/$APP"

# ---- payload -------------------------------------------------------------
cp -R "$REPO/$APP" "$STAGE/usr/share/$APP/$APP"
find "$STAGE/usr/share/$APP" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE/usr/share/$APP" -name '*.pyc' -delete 2>/dev/null || true

cat > "$STAGE/usr/bin/$APP" <<'LAUNCHER'
#!/bin/sh
# WENGOLD — installed by the wengold Debian package
export PYTHONPATH="/usr/share/wengold${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m wengold.native "$@"
LAUNCHER
chmod 0755 "$STAGE/usr/bin/$APP"

cp "$HERE/wengold.svg" "$STAGE/usr/share/icons/hicolor/scalable/apps/$APP.svg"

sed -e "s|@BIN@|/usr/bin/$APP|g" \
    -e "s|@ICON@|$APP|g" \
    "$HERE/wengold.desktop.in" > "$STAGE/usr/share/applications/$APP.desktop"
chmod 0644 "$STAGE/usr/share/applications/$APP.desktop"

# ---- metadata ------------------------------------------------------------
INSTALLED_KB=$(du -sk "$STAGE/usr" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $APP
Version: $VERSION
Section: devel
Priority: optional
Architecture: all
Installed-Size: $INSTALLED_KB
Depends: python3 (>= 3.10)
Recommends: python3-pyqt6 | python3-pyqt5
Maintainer: Thejas KG <thejaswalterobrain@gmail.com>
Homepage: https://github.com/thejas235689/wengold
Description: Validity kernel for silicon verification
 WENGOLD keeps every verification result that still holds after a change and
 reruns only what the change could have touched. Results are classified valid,
 invalidated or unknown, and never assumed.
 .
 The graph, the validity kernel and the ledger are open, dual-licensed
 MIT or Apache-2.0.
 .
 The native window needs PyQt6; without it the desktop command falls back to a
 browser window rather than failing to start.
CONTROL

cat > "$STAGE/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -f -t /usr/share/icons/hicolor >/dev/null 2>&1 || true
fi
exit 0
POSTINST
chmod 0755 "$STAGE/DEBIAN/postinst"

cat > "$STAGE/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
exit 0
POSTRM
chmod 0755 "$STAGE/DEBIAN/postrm"

# ---- build ---------------------------------------------------------------
# dpkg-deb refuses a control directory that is group-writable or setgid, which is
# what you get for free on a filesystem with a default ACL or a setgid parent.
# `chmod 0755` alone leaves the setgid bit when the parent directory is setgid
# (a default ACL, or /scratch on some hosts), and dpkg-deb rejects that. Clear it
# explicitly first.
chmod g-s "$STAGE/DEBIAN" 2>/dev/null || true
chmod 0755 "$STAGE/DEBIAN"
# every staged directory, not just DEBIAN: a setgid bit inherited from the build
# directory would otherwise ship in the package
find "$STAGE" -type d -exec chmod g-s {} + 2>/dev/null || true
find "$STAGE" -type d -exec chmod 0755 {} + 2>/dev/null || true
mkdir -p "$OUT"
# --root-owner-group so the payload is owned by root:root without needing
# fakeroot, which is not installed everywhere
dpkg-deb --root-owner-group --build "$STAGE" "$OUT/$PKG.deb" >/dev/null

say "wrote $OUT/$PKG.deb"
dpkg-deb --info "$OUT/$PKG.deb" | sed -n '1,12p' | sed 's/^/    /'

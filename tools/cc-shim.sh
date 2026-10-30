#!/bin/sh
# Give GHDL a C compiler when the machine has none.
#
# GHDL's LLVM backend refuses to start without `cc` on PATH:
#
#   ghdl:error: installation problem: cc not found
#
# Most Linux systems have gcc, so this is usually a non-issue. But containers,
# minimal CI images and sandboxes often do not, and the failure reads as "GHDL is
# broken" rather than "a build tool is missing". Zig ships a complete C compiler as
# a pip package, so this makes a `cc` from it in a directory you can prepend to
# PATH.
#
#   sh tools/cc-shim.sh                 # writes ~/.cache/wengold/ccbin/cc
#   export PATH=~/.cache/wengold/ccbin:$PATH
#   ghdl --version                      # now starts
#
# It does nothing if a real compiler already exists — a shim in front of gcc would
# be a worse compiler than gcc.
set -eu

DEST=${1:-${XDG_CACHE_HOME:-$HOME/.cache}/wengold/ccbin}

if command -v cc >/dev/null 2>&1; then
    printf '  cc already exists: %s\n' "$(command -v cc)"
    printf '  nothing to do — a real compiler beats a shim.\n'
    exit 0
fi

PY=${PYTHON:-python3}
if ! "$PY" -c 'import ziglang' >/dev/null 2>&1; then
    printf '  ziglang is not installed. Install it with:\n\n'
    printf '      %s -m pip install --user ziglang\n\n' "$PY"
    printf '  (or install gcc/cc through your package manager, which is better)\n'
    exit 1
fi

ZIG=$("$PY" -c 'import ziglang, os; print(os.path.join(os.path.dirname(ziglang.__file__), "zig"))')
if [ ! -x "$ZIG" ]; then
    printf '  ziglang is installed but no zig binary was found at %s\n' "$ZIG"
    exit 1
fi

mkdir -p "$DEST"
# A symlink is not enough: zig decides its mode from argv[0] only in some builds,
# so invoking a link named `cc` prints usage instead of compiling. A wrapper that
# passes `cc` explicitly is the reliable form.
printf '#!/bin/sh\nexec %s cc "$@"\n' "$ZIG" > "$DEST/cc"
chmod 0755 "$DEST/cc"

# prove it works rather than assuming
TMPD=$(mktemp -d)
trap 'rm -rf "$TMPD"' EXIT
printf '#include <stdio.h>\nint main(void){return 0;}\n' > "$TMPD/t.c"
if "$DEST/cc" "$TMPD/t.c" -o "$TMPD/t" 2>/dev/null && [ -x "$TMPD/t" ]; then
    printf '  wrote %s/cc and compiled a test program with it\n' "$DEST"
    printf '  add it to PATH with:\n\n'
    printf '      export PATH="%s:$PATH"\n\n' "$DEST"
else
    printf '  wrote %s/cc but it could not compile a trivial program\n' "$DEST"
    exit 1
fi

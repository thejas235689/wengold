#!/bin/sh
# Verify a release claim from a fresh checkout of the repository.
#
#   sh tools/verify-release.sh              # verify main
#   sh tools/verify-release.sh v0.48.1      # verify a tag
#   sh tools/verify-release.sh main 654     # also assert the pass count
#
# Why this exists
# ---------------
# v0.48.0's release note said "659 tests passing, CI green". Both were wrong: three
# test files had been edited in a working tree and never pushed, so the branch the
# release pointed at had four failing tests. The 659 came from the tree that had the
# edits.
#
# A test count is a claim about the repository. This script is the only thing that
# measures it from the repository rather than from whatever happens to be in the
# working directory. Run it before writing a number in a release note.
#
# It deliberately does not use the local checkout, PYTHONPATH, or installed state:
# a fresh tarball, a temporary directory, nothing inherited.
set -eu

REF=${1:-main}
EXPECT=${2:-}
WORK=${WORK:-$(mktemp -d)}
URL="https://codeload.github.com/thejas235689/wengold/tar.gz/refs/heads/$REF"

case "$REF" in
    v*) URL="https://codeload.github.com/thejas235689/wengold/tar.gz/refs/tags/$REF" ;;
esac

say()  { printf '  %s\n' "$*"; }
fail() { printf '  FAILED: %s\n' "$*" >&2; exit 1; }

say "verifying $REF from a fresh checkout"
say "workdir $WORK"

timeout 180 curl -sL "$URL" -o "$WORK/src.tgz" || fail "could not download $REF"
[ -s "$WORK/src.tgz" ] || fail "empty download — does $REF exist?"
mkdir -p "$WORK/src"
tar -xzf "$WORK/src.tgz" -C "$WORK/src" --strip-components=1 \
    || fail "could not extract — is $REF a real ref?"

[ -d "$WORK/src/wengold" ] || fail "no wengold/ package in $REF"
say "package present"

VERSION=$(cd "$WORK/src" && python3 -c "import sys; sys.path.insert(0, '.'); import wengold; print(wengold.__version__)")
PYPROJECT=$(cd "$WORK/src" && python3 -c "
import re, pathlib
t = pathlib.Path('pyproject.toml').read_text()
print(re.search(r'^version\s*=\s*\"([^\"]+)\"', t, re.M).group(1))
")
say "version $VERSION (pyproject says $PYPROJECT)"
[ "$VERSION" = "$PYPROJECT" ] || fail "the two version strings disagree"

# The whole point: no PYTHONPATH from the caller, no installed wengold.
say "running the suite with a clean environment"
OUT=$(cd "$WORK/src" && env -u PYTHONPATH PYTHONPATH=. \
      timeout 600 python3 -m pytest -q -p no:cacheprovider tests 2>&1) || true
TAIL=$(printf '%s\n' "$OUT" | tail -3)

# `654 passed, 5 skipped` — the number can start the line, so a leading
# [^0-9] anchor silently produced 0. Extract with grep instead of sed.
# `|| true`: a suite with no failures prints no "failed", and grep returning 1
# would kill the script under `set -e` — the one case we most want to survive.
count() { printf '%s\n' "$OUT" | grep -oE "[0-9]+ $1" | tail -1 | grep -oE '^[0-9]+' || true; }
PASSED=$(count passed)
FAILED=$(count failed)
SKIPPED=$(count skipped)
PASSED=${PASSED:-0}
FAILED=${FAILED:-0}
SKIPPED=${SKIPPED:-0}

printf '%s\n' "$TAIL" | sed 's/^/  /'

[ "$FAILED" = "0" ] || fail "$FAILED test(s) failed on $REF"

if [ -n "$EXPECT" ]; then
    [ "$PASSED" = "$EXPECT" ] || \
        fail "expected $EXPECT passing, $REF has $PASSED"
    say "count matches the claim: $PASSED"
fi

say "VERIFIED: $REF — $PASSED passed, $SKIPPED skipped, $FAILED failed"
say "version $VERSION"

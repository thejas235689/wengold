"""Content fingerprints.

Every verification conclusion is fingerprinted against the content it consumed
and produced. Edit something upstream and the conclusion goes stale on the next
query — no flags, no snapshots, just recomputation from the ledger.
"""
from __future__ import annotations

import hashlib


def fingerprint(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update(p.encode())
        h.update(b"\x00")
    return "sha256:" + h.hexdigest()[:16]

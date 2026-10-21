"""The Ledger: an append-only, hash-chained record of the program.

Every run, revision, verdict and waiver is appended and chained to the entry
before it, so the record is tamper-evident and each change starts from what is
already proven. Status is always derived from the ledger, never stored as a flag.

Hardening:

* **Concurrent writes** are serialised with an advisory file lock, and each
  append recomputes its sequence and previous-hash under that lock.
* **Sequence and chain** are validated on read; a gap, a bad link or a wrong hash
  is reported, not silently accepted.
* **Malformed records** (truncated lines, non-JSON) are skipped and surfaced.
* **Truncation** of trailing records — which a local hash chain alone cannot
  detect — is caught by a **trusted checkpoint** written out of band.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

try:  # advisory locking is POSIX; degrade gracefully elsewhere
    import fcntl
except Exception:  # pragma: no cover
    fcntl = None  # type: ignore

GENESIS = "0" * 64
_REQUIRED = ("seq", "ts", "kind", "payload", "prev", "hash")


def _hash_body(body: dict) -> str:
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


@dataclass
class LedgerReport:
    ok: bool
    count: int
    issues: list[str] = field(default_factory=list)
    last_seq: int = 0
    last_hash: str = GENESIS
    checkpoint_status: str = "none"   # none | ok | missing | truncated | mismatched

    def as_dict(self) -> dict:
        return {"ok": self.ok, "count": self.count, "issues": self.issues,
                "last_seq": self.last_seq, "last_hash": self.last_hash,
                "checkpoint_status": self.checkpoint_status}


class Ledger:
    def __init__(self, path: str | Path = "ledger.tof") -> None:
        self.path = Path(path)
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        self.checkpoint_path = self.path.with_suffix(self.path.suffix + ".ckpt")
        if not self.path.exists():
            self.path.write_text("")

    # ---- locking ------------------------------------------------------
    class _Lock:
        def __init__(self, lock_path: Path):
            self.lock_path = lock_path
            self.fh = None

        def __enter__(self):
            if fcntl is not None:
                self.fh = open(self.lock_path, "w")
                fcntl.flock(self.fh, fcntl.LOCK_EX)
            return self

        def __exit__(self, *exc):
            if self.fh is not None:
                try:
                    fcntl.flock(self.fh, fcntl.LOCK_UN)
                finally:
                    self.fh.close()
                    self.fh = None
            return False

    # ---- reading ------------------------------------------------------
    def records(self) -> Iterator[tuple[int, dict | None, str]]:
        """Yield (line_number, parsed_or_None, raw_line) for every non-blank line."""
        with self.path.open() as f:
            for i, raw in enumerate(f, start=1):
                line = raw.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                    if not isinstance(obj, dict) or not all(k in obj for k in _REQUIRED):
                        obj = None
                except json.JSONDecodeError:
                    obj = None
                yield i, obj, line

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for _n, obj, _raw in self.records():
            if obj is not None:
                yield obj

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def _tail(self) -> tuple[int, str]:
        """(last_seq, last_hash) over well-formed records."""
        last_seq, last_hash = 0, GENESIS
        for obj in self:
            last_seq, last_hash = obj["seq"], obj["hash"]
        return last_seq, last_hash

    # ---- writing ------------------------------------------------------
    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self._Lock(self.lock_path):
            seq, prev = self._tail()
            seq += 1
            body = {"seq": seq, "ts": time.time(), "kind": kind, "payload": payload, "prev": prev}
            body["hash"] = _hash_body(body)
            with self.path.open("a") as f:
                f.write(json.dumps(body) + "\n")
                f.flush()
            return body

    # ---- verification -------------------------------------------------
    def audit(self, checkpoint: bool = False) -> LedgerReport:
        issues: list[str] = []
        prev = GENESIS
        expected = 1
        count = 0
        last_seq, last_hash = 0, GENESIS
        for n, obj, raw in self.records():
            if obj is None:
                issues.append(f"line {n}: malformed record skipped")
                continue
            if obj["seq"] != expected:
                issues.append(f"line {n}: sequence {obj['seq']} != expected {expected}")
            if obj["prev"] != prev:
                issues.append(f"line {n}: prev hash does not match chain")
            body = {k: v for k, v in obj.items() if k != "hash"}
            if _hash_body(body) != obj["hash"]:
                issues.append(f"line {n}: hash mismatch (record altered)")
            prev = obj["hash"]
            last_seq, last_hash = obj["seq"], obj["hash"]
            expected = obj["seq"] + 1
            count += 1

        cp_status = "none"
        if checkpoint:
            cp_status = self._checkpoint_status(count, last_seq, last_hash)
            if cp_status in ("truncated", "mismatched", "missing"):
                issues.append(f"checkpoint: {cp_status}")

        return LedgerReport(ok=not issues, count=count, issues=issues,
                            last_seq=last_seq, last_hash=last_hash,
                            checkpoint_status=cp_status)

    def verify(self, checkpoint: bool = False) -> bool:
        return self.audit(checkpoint=checkpoint).ok

    # ---- trusted checkpoint ------------------------------------------
    def checkpoint(self) -> dict:
        """Write an out-of-band anchor of the current head. A later reader that
        trusts this file can detect deleted trailing records."""
        seq, h = self._tail()
        count = len(self)
        cp = {"count": count, "seq": seq, "hash": h,
              "digest": hashlib.sha256(f"{count}:{seq}:{h}".encode()).hexdigest()}
        self.checkpoint_path.write_text(json.dumps(cp, sort_keys=True))
        return cp

    def _checkpoint_status(self, count: int, last_seq: int, last_hash: str) -> str:
        if not self.checkpoint_path.exists():
            return "missing"
        try:
            cp = json.loads(self.checkpoint_path.read_text())
        except Exception:
            return "mismatched"
        if count < cp["count"] or last_seq < cp["seq"]:
            return "truncated"
        if last_hash != cp["hash"] or count != cp["count"]:
            return "mismatched"
        return "ok"

    def verify_checkpoint(self) -> tuple[bool, str]:
        count = len(self)
        seq, h = self._tail()
        status = self._checkpoint_status(count, seq, h)
        return status == "ok", status

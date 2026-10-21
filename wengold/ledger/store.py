"""The Ledger: an append-only, hash-chained record of the program.

Every run, revision, verdict and waiver is appended and chained to the previous
entry, so the record is tamper-evident and each change starts from what is
already proven. Status is always derived from the ledger, never stored as a flag.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterator

GENESIS = "0" * 64


class Ledger:
    def __init__(self, path: str | Path = "ledger.tof") -> None:
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text("")

    def _last_hash(self) -> str:
        last = GENESIS
        for line in self.path.read_text().splitlines():
            if line.strip():
                last = json.loads(line)["hash"]
        return last

    def append(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        seq = sum(1 for _ in self) + 1
        prev = self._last_hash()
        body = {"seq": seq, "ts": time.time(), "kind": kind, "payload": payload, "prev": prev}
        body["hash"] = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.path.open("a") as f:
            f.write(json.dumps(body) + "\n")
        return body

    def __iter__(self) -> Iterator[dict[str, Any]]:
        for line in self.path.read_text().splitlines():
            if line.strip():
                yield json.loads(line)

    def verify(self) -> bool:
        prev = GENESIS
        for entry in self:
            if entry["prev"] != prev:
                return False
            body = {k: v for k, v in entry.items() if k != "hash"}
            if hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest() != entry["hash"]:
                return False
            prev = entry["hash"]
        return True

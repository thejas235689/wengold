"""Cryptographic reviewer attestations and external ledger anchors.

A public-key registry outside the project defines trusted reviewers. A reviewer
signs a canonical, evidence-bound decision with their Ed25519 private key.
Public keys alone do not prove corporate identity: an administrator must vet
reviewer identities and protect the trust directory separately.

An anchor must be stored in a path outside the project, ideally on an independent,
write-protected storage system. A path on the same physical disk is not an
independent timestamp or an external trust service.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path

from .ide_server import Refused
from .ledger.store import Ledger

def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()

def review_claim(job: dict, reviewer: str, decision: str) -> dict:
    return {"v": 1, "purpose": "wengold-engineering-evidence-review",
            "job_id": job["id"], "reviewer": reviewer,
            "decision": decision, "source_sha256": job["source_sha256"],
            "result_sha256": job["result_sha256"]}

def verify_review_signature(job: dict, reviewer: str, decision: str,
                            signature: str, trust_dir: str) -> str:
    try:
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.exceptions import InvalidSignature
    except ImportError:
        raise Refused("cryptography package required for signed review", 503) from None
    if not re.fullmatch(r"[A-Za-z0-9_.-]{2,100}", reviewer) or reviewer.startswith("."):
        raise Refused("invalid reviewer identifier", 400)
    directory = Path(trust_dir).resolve()
    if not directory.is_dir():
        raise Refused("trusted reviewer directory not configured", 403)
    public_path = directory / (reviewer + ".pub")
    if public_path.is_symlink() or not public_path.is_file():
        raise Refused("reviewer not enrolled in trusted key registry", 403)
    try:
        pub = load_pem_public_key(public_path.read_bytes())
        if not isinstance(pub, Ed25519PublicKey):
            raise ValueError("expected Ed25519 public key")
        raw = base64.b64decode(signature, validate=True)
        pub.verify(raw, canonical(review_claim(job, reviewer, decision)))
    except (InvalidSignature, ValueError, TypeError, OSError) as exc:
        raise Refused("review signature could not be verified", 403) from exc
    return hashlib.sha256(public_path.read_bytes()).hexdigest()

def sign_claim(job: dict, reviewer: str, decision: str, private_key_path: str) -> str:
    """CLI helper: private key stays on reviewer machine, never in project JSON."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = load_pem_private_key(Path(private_key_path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("expected Ed25519 private key")
    return base64.b64encode(key.sign(canonical(review_claim(job, reviewer, decision)))).decode()

def export_anchor(ledger_file: str | Path, independent_dir: str | Path) -> dict:
    ledger_file = Path(ledger_file).resolve()
    external = Path(independent_dir).resolve()
    if ledger_file.parent == external or ledger_file.parent in external.parents:
        raise Refused("anchor destination must be outside project directory", 403)
    if not external.is_dir() or external.is_symlink():
        raise Refused("anchor destination must be an existing separate directory", 403)
    report = Ledger(ledger_file).audit()
    if not report.ok:
        raise Refused("ledger is not valid: refuse to anchor", 409)
    anchor = {"format": "wengold-ledger-anchor-v1", "created_utc": int(time.time()),
              "ledger_file": ledger_file.name, "count": report.count,
              "last_seq": report.last_seq, "last_hash": report.last_hash,
              "ledger_sha256": hashlib.sha256(ledger_file.read_bytes()).hexdigest()}
    path = external / ("wengold-anchor-" + str(anchor["created_utc"]) + "-"
                       + anchor["last_hash"][:16] + ".json")
    # Never overwrite an existing anchor. Storage-level retention is user's duty.
    with path.open("x", encoding="utf-8") as f:
        json.dump(anchor, f, sort_keys=True)
        f.write("\n")
    return {"path": str(path), "anchor": anchor}

def verify_anchor(ledger_file: str | Path, anchor_file: str | Path) -> dict:
    ledger_file = Path(ledger_file)
    anchor = json.loads(Path(anchor_file).read_text(encoding="utf-8"))
    report = Ledger(ledger_file).audit()
    if anchor.get("format") != "wengold-ledger-anchor-v1" or not report.ok:
        return {"ok": False, "reason": "invalid anchor or local ledger"}
    # A later ledger may contain additional events. The anchored prefix must match.
    records = list(Ledger(ledger_file))
    count = anchor["count"]
    if not isinstance(count, int) or count < 0 or count > len(records):
        return {"ok": False, "reason": "anchor references nonexistent records"}
    digest = records[count - 1]["hash"] if count else "0" * 64
    ok = digest == anchor["last_hash"]
    return {"ok": ok, "anchored_count": count,
            "current_count": len(records), "reason": "anchored prefix verified" if ok else "anchored history altered"}

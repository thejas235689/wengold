"""Durable queue recovery, signature verification and external anchor tests."""
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from wengold.ide_server import Refused
from wengold.studio_durable import DurableQueue
from wengold.studio_attest import export_anchor, verify_anchor, review_claim, verify_review_signature
from wengold.ledger.store import Ledger


def test_multiworker_atomic_claim_and_persistence(tmp_path):
    (tmp_path / "mod.sv").write_text("module mod; endmodule\n")
    first = DurableQueue(tmp_path)
    ids = [first.submit("syntax", "mod.sv")["id"] for _ in range(12)]
    other = DurableQueue(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda n: (first if n % 2 else other).claim("worker-" + str(n)),
                                range(12)))
    assert len({j["id"] for j in claimed if j}) == 12
    assert {j["id"] for j in claimed} == set(ids)
    for job in claimed:
        assert first.finish(job, "worker-" + str(claimed.index(job)), {"status": "clean"})
    reopened = DurableQueue(tmp_path)
    assert all(reopened.get(i)["status"] == "completed" for i in ids)


def test_expired_lease_is_fenced_and_retried(tmp_path):
    (tmp_path / "mod.sv").write_text("module mod; endmodule\n")
    q = DurableQueue(tmp_path)
    job_id = q.submit("syntax", "mod.sv")["id"]
    old = q.claim("old-worker")
    with q.connect() as db:
        db.execute("UPDATE jobs SET lease_until=? WHERE id=?", (time.time() - 1, job_id))
    current = q.claim("new-worker")
    assert current["attempt"] == old["attempt"] + 1
    assert not q.finish(old, "old-worker", {"status": "forged"})
    assert q.finish(current, "new-worker", {"status": "clean"})
    assert q.get(job_id)["status"] == "completed"


def test_anchor_detects_modified_prefix(tmp_path):
    project = tmp_path / "design"
    external = tmp_path / "independent"
    project.mkdir()
    external.mkdir()
    ledger_path = project / "evidence.jsonl"
    ledger = Ledger(ledger_path)
    ledger.append("proof", {"status": "unknown"})
    anchor = export_anchor(ledger_path, external)
    assert verify_anchor(ledger_path, anchor["path"])["ok"]
    ledger.append("review", {"decision": "reject"})
    assert verify_anchor(ledger_path, anchor["path"])["ok"]
    # Ledger audit and independently retained anchor both reject tampering.
    ledger_path.write_text(ledger_path.read_text().replace("unknown", "proof"))
    assert not verify_anchor(ledger_path, anchor["path"])["ok"]
    with pytest.raises(Refused):
        export_anchor(ledger_path, project)


def test_review_signature_rejects_wrong_identity_and_payload(tmp_path):
    crypto = pytest.importorskip("cryptography")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PrivateFormat, PublicFormat, NoEncryption,
    )
    from wengold.studio_attest import sign_claim
    key = Ed25519PrivateKey.generate()
    trusted = tmp_path / "trust"
    trusted.mkdir()
    (trusted / "reviewer.pub").write_bytes(key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo))
    private = tmp_path / "reviewer.private"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    job = {"id": "job-a", "source_sha256": "a" * 64, "result_sha256": "b" * 64}
    sig = sign_claim(job, "reviewer", "accept", str(private))
    assert len(verify_review_signature(job, "reviewer", "accept", sig, str(trusted))) == 64
    with pytest.raises(Refused):
        verify_review_signature({**job, "result_sha256": "c" * 64}, "reviewer", "accept", sig, str(trusted))
    with pytest.raises(Refused):
        verify_review_signature(job, "impostor", "accept", sig, str(trusted))
    with pytest.raises(Refused):
        verify_review_signature(job, "reviewer", "reject", sig, str(trusted))

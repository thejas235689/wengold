"""The ledger must survive malformed records, sequence gaps and truncation."""
import json

from wengold.ledger.store import Ledger


def test_malformed_record_is_flagged(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    led.append("a", {})
    with led.path.open("a") as f:
        f.write("{not json\n")
    led.append("b", {})
    audit = led.audit()
    assert audit.ok is False
    assert any("malformed" in i for i in audit.issues)
    assert len(led) == 2                      # well-formed records still readable


def test_sequence_gap_is_flagged(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    led.append("a", {})
    led.append("b", {})
    lines = led.path.read_text().splitlines()
    bad = json.loads(lines[1])
    bad["seq"] = 9
    lines[1] = json.dumps(bad)
    led.path.write_text("\n".join(lines) + "\n")
    audit = led.audit()
    assert audit.ok is False
    assert any("sequence" in i for i in audit.issues)


def test_checkpoint_detects_truncation(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    led.append("a", {})
    led.append("b", {})
    led.append("c", {})
    led.checkpoint()
    assert led.verify(checkpoint=True) is True

    # delete the trailing records — a plain hash chain cannot see this
    lines = led.path.read_text().splitlines()
    led.path.write_text(lines[0] + "\n")
    audit = led.audit(checkpoint=True)
    assert audit.ok is False
    assert audit.checkpoint_status == "truncated"


def test_checkpoint_reports_mismatch_on_append(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    led.append("a", {})
    led.checkpoint()
    led.append("b", {})                        # head moved past the checkpoint
    ok, status = led.verify_checkpoint()
    assert ok is False
    assert status == "mismatched"


def test_concurrent_appends_stay_consistent(tmp_path):
    led = Ledger(tmp_path / "l.tof")
    for i in range(25):
        led.append("n", {"i": i})
    audit = led.audit()
    assert audit.ok is True
    assert audit.count == 25
    assert [r["seq"] for r in led] == list(range(1, 26))

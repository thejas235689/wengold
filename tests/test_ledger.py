"""The ledger is append-only and tamper-evident."""
import json
from wengold.ledger.store import Ledger


def test_append_and_verify(tmp_path):
    led = Ledger(tmp_path / "ledger.tof")
    led.append("run", {"revision": "r1"})
    led.append("verdict", {"result": "sec_acl_test", "verdict": "pass"})
    assert sum(1 for _ in led) == 2
    assert led.verify() is True


def test_tamper_is_detected(tmp_path):
    path = tmp_path / "ledger.tof"
    led = Ledger(path)
    led.append("run", {"revision": "r1"})
    led.append("run", {"revision": "r2"})
    lines = path.read_text().splitlines()
    bad = json.loads(lines[0]); bad["payload"]["revision"] = "r9"
    lines[0] = json.dumps(bad)
    path.write_text("\n".join(lines) + "\n")
    assert Ledger(path).verify() is False


def test_chain_links_prev(tmp_path):
    led = Ledger(tmp_path / "ledger.tof")
    a = led.append("a", {})
    b = led.append("b", {})
    assert b["prev"] == a["hash"]

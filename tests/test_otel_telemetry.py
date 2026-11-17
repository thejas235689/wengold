"""OTLP export preserves WENGOLD evidence and correlates all signals."""
import json

import pytest

from wengold.otel_telemetry import build_otlp_bundle, write_otlp_bundle


REPORT = {
    "status": "diagnostic_candidates_not_proven",
    "source": "waves/tb.vcd",
    "times": [0, 5, 10, 15],
    "samples": 4,
    "summary": {
        "rtl_signals": 2,
        "testbench_signals": 3,
        "unclassified": 1,
        "ambiguous": 0,
        "findings": 1,
        "errors": 1,
        "warnings": 0,
    },
    "findings": [{
        "rule": "scoreboard_mismatch",
        "domain": "testbench",
        "severity": "error",
        "title": "Expected/actual mismatch observed",
        "sample_index": 2,
        "time": 10,
        "signals": ["tb.env.scoreboard.data_expected",
                    "tb.env.scoreboard.data_actual"],
        "observed": "expected=7; actual=5",
        "assessment": "candidate",
        "source": "observed VCD samples",
    }],
}


def _value(attributes, key):
    row = next(item for item in attributes if item["key"] == key)
    return row["value"]


def test_bundle_correlates_trace_log_and_metric_signals():
    bundle = build_otlp_bundle(
        REPORT,
        transactions=[{
            "protocol": "AXI4",
            "operation": "read",
            "transaction_id": "0x2a",
            "start_time": 5,
            "end_time": 15,
            "address": "0x80001000",
            "response": "OKAY",
            "beats": 4,
            "status": "ok",
            "attributes": {"burst": "INCR"},
        }],
        run_id="sim-42",
        run_start_unix_ns=1_000_000_000,
        time_unit_ns="1",
        time_unit_label="ns",
    )

    spans = bundle["traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"]
    root = next(span for span in spans if span["name"] == "wengold.simulation.run")
    finding_span = next(span for span in spans
                        if span["name"] == "wave_debug.scoreboard_mismatch")
    tx_span = next(span for span in spans if span["name"] == "axi4.read")

    assert root["traceId"] == finding_span["traceId"] == tx_span["traceId"]
    assert finding_span["parentSpanId"] == root["spanId"]
    assert tx_span["parentSpanId"] == root["spanId"]
    assert finding_span["startTimeUnixNano"] == "1000000010"
    assert tx_span["endTimeUnixNano"] == "1000000015"
    assert _value(tx_span["attributes"], "wengold.transaction.id") == {
        "stringValue": "0x2a"
    }
    assert _value(tx_span["attributes"], "wengold.protocol.name") == {
        "stringValue": "axi4"
    }

    records = bundle["logs"]["resourceLogs"][0]["scopeLogs"][0]["logRecords"]
    assert len(records) == 1
    assert records[0]["traceId"] == root["traceId"]
    assert records[0]["spanId"] == finding_span["spanId"]
    assert records[0]["severityText"] == "ERROR"

    metrics = bundle["metrics"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    findings_metric = next(m for m in metrics
                           if m["name"] == "wengold.wave_debug.findings")
    assert findings_metric["sum"]["dataPoints"][0]["asInt"] == "1"
    tx_metric = next(m for m in metrics
                     if m["name"] == "wengold.traffic.transactions")
    assert tx_metric["sum"]["dataPoints"][0]["asInt"] == "1"
    assert bundle["metadata"]["run_id"] == "sim-42"


def test_ps_timescale_keeps_raw_simulation_time_and_rounds_to_otlp_ns():
    bundle = build_otlp_bundle(
        REPORT,
        run_id="ps-run",
        run_start_unix_ns=2_000_000_000,
        time_unit_ns="0.001",
        time_unit_label="ps",
    )
    finding = bundle["traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"][1]
    assert finding["startTimeUnixNano"] == "2000000000"
    assert _value(finding["attributes"], "wengold.simulation.time") == {
        "stringValue": "10"
    }
    assert bundle["metadata"]["simulation_time_unit"] == "ps"


def test_invalid_transaction_time_order_is_rejected():
    with pytest.raises(ValueError, match="ends before it starts"):
        build_otlp_bundle(
            REPORT,
            transactions=[{
                "protocol": "AXI4",
                "operation": "write",
                "transaction_id": "3",
                "start_time": 15,
                "end_time": 5,
            }],
            run_id="bad-run",
            run_start_unix_ns=1_000,
        )


def test_bundle_writes_separate_otlp_payloads(tmp_path):
    bundle = build_otlp_bundle(REPORT, run_id="export-test",
                               run_start_unix_ns=9_000_000)
    target = write_otlp_bundle(tmp_path / "nested" / "telemetry.json", bundle)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert set(("traces", "metrics", "logs", "metadata")) == set(loaded)
    assert loaded["metadata"]["trace_id"] == bundle["metadata"]["trace_id"]
    assert not (tmp_path / "nested" / "telemetry.json.tmp").exists()


def test_export_rejects_invalid_time_unit():
    with pytest.raises(ValueError, match="time_unit_ns must be positive"):
        build_otlp_bundle(REPORT, time_unit_ns=0)

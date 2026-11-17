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



def test_dynatrace_export_sends_binary_otlp_protobuf(monkeypatch):
    pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
    pytest.importorskip("opentelemetry.proto.collector.metrics.v1.metrics_service_pb2")
    pytest.importorskip("opentelemetry.proto.collector.logs.v1.logs_service_pb2")
    from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
        ExportTraceServiceRequest,
    )
    from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
        ExportMetricsServiceRequest,
    )
    from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
        ExportLogsServiceRequest,
    )
    from wengold.otel_telemetry import send_dynatrace_otlp

    bundle = build_otlp_bundle(REPORT, run_id="dynatrace-export",
                               run_start_unix_ns=5_000_000_000)
    sent = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

        def getcode(self):
            return self.status

    def fake_urlopen(request, timeout):
        sent.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = send_dynatrace_otlp(
        bundle,
        "https://example.live.dynatrace.com/api/v2/otlp",
        "secret-token-never-store",
        timeout=7,
    )

    assert result["status"] == "exported"
    assert result["signals_sent"] == ["traces", "metrics", "logs"]
    assert [row[0].full_url for row in sent] == [
        "https://example.live.dynatrace.com/api/v2/otlp/v1/traces",
        "https://example.live.dynatrace.com/api/v2/otlp/v1/metrics",
        "https://example.live.dynatrace.com/api/v2/otlp/v1/logs",
    ]
    assert all(row[1] == 7 for row in sent)
    assert all(row[0].get_header("Content-type") == "application/x-protobuf"
               for row in sent)
    assert all(row[0].get_header("Authorization") == "Bearer secret-token-never-store"
               for row in sent)
    assert ExportTraceServiceRequest.FromString(sent[0][0].data).resource_spans
    assert ExportMetricsServiceRequest.FromString(sent[1][0].data).resource_metrics
    assert ExportLogsServiceRequest.FromString(sent[2][0].data).resource_logs
    assert "secret-token-never-store" not in json.dumps(result)


def test_dynatrace_export_rejects_insecure_or_signal_specific_urls():
    from wengold.otel_telemetry import send_dynatrace_otlp

    bundle = build_otlp_bundle(REPORT, run_id="url-validation",
                               run_start_unix_ns=5_000_000_000)
    with pytest.raises(ValueError, match="HTTPS"):
        send_dynatrace_otlp(bundle, "http://example.test/api/v2/otlp", "token")
    with pytest.raises(ValueError, match="base URL"):
        send_dynatrace_otlp(bundle, "https://example.test/api/v2/otlp/v1/traces", "token")


def test_dynatrace_export_reports_partial_delivery_without_exposing_token(monkeypatch):
    pytest.importorskip("opentelemetry.proto.collector.trace.v1.trace_service_pb2")
    pytest.importorskip("opentelemetry.proto.collector.metrics.v1.metrics_service_pb2")
    pytest.importorskip("opentelemetry.proto.collector.logs.v1.logs_service_pb2")
    from urllib.error import HTTPError
    from wengold.otel_telemetry import DynatraceExportError, send_dynatrace_otlp

    bundle = build_otlp_bundle(REPORT, run_id="partial-export",
                               run_start_unix_ns=5_000_000_000)
    calls = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b""

        def getcode(self):
            return self.status

    def fake_urlopen(request, timeout):
        calls.append(request.full_url)
        if request.full_url.endswith("/v1/metrics"):
            raise HTTPError(request.full_url, 401, "unauthorized", {}, None)
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(DynatraceExportError) as err:
        send_dynatrace_otlp(bundle, "https://example.test/api/v2/otlp", "very-secret")
    assert err.value.sent_signals == ("traces",)
    assert "very-secret" not in str(err.value)
    assert len(calls) == 2



def test_default_backend_timeline_is_capped_inside_dynatrace_window(monkeypatch):
    import wengold.otel_telemetry as telemetry

    fixed_now = 90_000_000_000_000
    monkeypatch.setattr(telemetry.time, "time_ns", lambda: fixed_now)
    long_report = {
        "source": "long-regression.vcd",
        "times": [0, 7_200_000_000_000],
        "samples": 2,
        "summary": {},
        "findings": [],
    }
    bundle = telemetry.build_otlp_bundle(
        long_report, run_id="long-run", time_unit_ns="1", time_unit_label="ns")
    root = bundle["traces"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    start = int(root["startTimeUnixNano"])
    end = int(root["endTimeUnixNano"])
    assert start == fixed_now - 55 * 60 * 1_000_000_000
    assert fixed_now <= end <= fixed_now + 1
    assert float(bundle["metadata"]["otel_timeline_scale_factor"]) < 1.0
    # The raw VCD value remains available; only the external display window shrinks.
    assert bundle["metadata"]["simulation_time_origin"] == "0"
    assert bundle["metadata"]["simulation_time_unit_ns"] == "1"

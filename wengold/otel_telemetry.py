"""OpenTelemetry JSON export for WENGOLD simulation and traffic evidence.

The decoder/rule engine remains the source of truth. This module maps its
observations into OTLP JSON so local tools or an OpenTelemetry Collector can
forward traces, metrics and logs to a backend such as Dynatrace.

Simulation timestamps are mapped onto a synthetic wall-clock window anchored at
export time. The original simulator time and unit are retained as attributes;
they are never presented as physical elapsed time unless the VCD timescale is
known.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping

__all__ = ["build_otlp_bundle", "write_otlp_bundle"]

_SCOPE_NAME = "wengold.telemetry"
_SCOPE_VERSION = "1.0.0"


def _any_value(value: Any) -> dict:
    """Encode a Python scalar/list as an OTLP AnyValue JSON object."""
    if value is None:
        return {"stringValue": ""}
    if isinstance(value, bool):
        return {"boolValue": value}
    if isinstance(value, int):
        return {"intValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_any_value(v) for v in value]}}
    if isinstance(value, Mapping):
        return {"kvlistValue": {"values": [
            {"key": str(k), "value": _any_value(v)} for k, v in value.items()
        ]}}
    return {"stringValue": str(value)}


def _attrs(values: Mapping[str, Any]) -> list[dict]:
    return [{"key": str(key), "value": _any_value(value)}
            for key, value in sorted(values.items()) if value is not None]


def _hex_id(seed: str, length: int) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:length]


def _decimal(value: Any, field: str) -> Decimal:
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{field} must be numeric") from None
    if not out.is_finite():
        raise ValueError(f"{field} must be finite")
    return out


def _to_unix_ns(sim_time: Any, origin: Decimal, unit_ns: Decimal,
                run_start_unix_ns: int) -> int:
    offset = (_decimal(sim_time, "simulation time") - origin) * unit_ns
    return run_start_unix_ns + int(offset.to_integral_value(rounding=ROUND_HALF_UP))


def _resource() -> dict:
    return {"attributes": _attrs({
        "service.name": "wengold",
        "service.version": "0.68.3",
        "telemetry.sdk.name": "wengold-otel-bridge",
        "telemetry.sdk.language": "python",
        "telemetry.sdk.version": _SCOPE_VERSION,
    })}


def _span(trace_id: str, span_id: str, parent_span_id: str | None,
          name: str, start_ns: int, end_ns: int, attributes: Mapping[str, Any],
          *, status: str = "STATUS_CODE_UNSET",
          events: list[dict] | None = None) -> dict:
    result = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(max(start_ns + 1, end_ns)),
        "attributes": _attrs(attributes),
        "status": {"code": status},
    }
    if parent_span_id:
        result["parentSpanId"] = parent_span_id
    if events:
        result["events"] = events
    return result


def _event(name: str, time_ns: int, attributes: Mapping[str, Any]) -> dict:
    return {"name": name, "timeUnixNano": str(time_ns),
            "attributes": _attrs(attributes)}


def _sum_metric(name: str, unit: str, points: list[dict]) -> dict:
    return {
        "name": name,
        "unit": unit,
        "sum": {
            "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
            "isMonotonic": True,
            "dataPoints": points,
        },
    }


def build_otlp_bundle(report: Mapping[str, Any], *,
                      transactions: Iterable[Mapping[str, Any]] = (),
                      run_id: str | None = None,
                      run_start_unix_ns: int | None = None,
                      time_unit_ns: Any = 1,
                      time_unit_label: str = "tick") -> dict:
    """Build an OTLP JSON bundle from a WENGOLD Wave Debug report.

    Args:
        report: The dictionary returned by wengold.wave_debug.diagnose().
        transactions: Optional decoded bus transactions. Each record accepts
            protocol, operation, transaction_id, start_time, end_time,
            address, response, beats, status and an optional attributes map.
            These records must come from a real protocol decoder/monitor.
        run_id: Stable simulation identifier; generated when omitted.
        run_start_unix_ns: Synthetic Unix-nanosecond anchor. Defaults to now.
        time_unit_ns: Nanoseconds per raw VCD timestamp tick. Pass the parsed
            VCD timescale value (for example Decimal("1") for 1 ns or
            Decimal("0.001") for 1 ps). If unknown, keep the default and set
            time_unit_label="tick"; the original raw times are retained.
        time_unit_label: Original VCD unit label, or "tick"/"cycle" if unknown.

    The returned bundle has three independent OTLP/HTTP request bodies under
    traces, metrics and logs. The metadata field is WENGOLD-only provenance.
    """
    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    run_id = str(run_id or uuid.uuid4().hex)
    if not run_id or len(run_id) > 256:
        raise ValueError("run_id must contain 1..256 characters")
    if run_start_unix_ns is None:
        run_start_unix_ns = time.time_ns()
    if not isinstance(run_start_unix_ns, int) or run_start_unix_ns < 0:
        raise ValueError("run_start_unix_ns must be a non-negative integer")
    unit_ns = _decimal(time_unit_ns, "time_unit_ns")
    if unit_ns <= 0:
        raise ValueError("time_unit_ns must be positive")

    times = list(report.get("times") or [])
    raw_values = [_decimal(v, "report timestamp") for v in times]
    finding_rows = list(report.get("findings") or [])
    tx_rows = list(transactions)
    all_times = raw_values[:]
    for finding in finding_rows:
        if finding.get("time") is not None:
            all_times.append(_decimal(finding["time"], "finding time"))
    for transaction in tx_rows:
        if transaction.get("start_time") is not None:
            all_times.append(_decimal(transaction["start_time"], "transaction start_time"))
        if transaction.get("end_time") is not None:
            all_times.append(_decimal(transaction["end_time"], "transaction end_time"))
    origin = min(all_times) if all_times else Decimal(0)

    def stamp(value: Any) -> int:
        return _to_unix_ns(value, origin, unit_ns, run_start_unix_ns)

    end_time = max(all_times) if all_times else origin
    run_end_ns = stamp(end_time) + max(1, int(unit_ns.to_integral_value(
        rounding=ROUND_HALF_UP)))
    trace_id = _hex_id("wengold:" + run_id, 32)
    root_span_id = _hex_id("wengold:root:" + run_id, 16)
    root_attrs = {
        "wengold.run.id": run_id,
        "wengold.evidence.source": report.get("source", "unknown"),
        "wengold.simulation.time_unit": time_unit_label,
        "wengold.simulation.time_unit_ns": str(unit_ns),
        "wengold.simulation.samples": int(report.get("samples", len(times)) or 0),
        "wengold.findings.count": len(finding_rows),
        "wengold.transactions.count": len(tx_rows),
        "wengold.diagnosis.status": report.get("status", "unknown"),
    }
    spans = [_span(trace_id, root_span_id, None, "wengold.simulation.run",
                   run_start_unix_ns, run_end_ns, root_attrs)]

    log_records = []
    severity_counts: Counter[tuple[str, str]] = Counter()
    finding_span_ids: list[str] = []
    for index, finding in enumerate(finding_rows):
        if not isinstance(finding, Mapping):
            continue
        rule = str(finding.get("rule", "unknown"))
        severity = str(finding.get("severity", "warning")).lower()
        domain = str(finding.get("domain", "unclassified"))
        raw_time = finding.get("time", origin)
        event_ns = stamp(raw_time)
        span_id = _hex_id(f"{run_id}:finding:{index}:{rule}", 16)
        finding_span_ids.append(span_id)
        signals = list(finding.get("signals") or [])
        attrs = {
            "wengold.run.id": run_id,
            "wengold.finding.rule": rule,
            "wengold.finding.severity": severity,
            "wengold.finding.domain": domain,
            "wengold.finding.assessment": finding.get("assessment", "candidate"),
            "wengold.finding.sample_index": finding.get("sample_index"),
            "wengold.simulation.time": str(raw_time),
            "wengold.simulation.time_unit": time_unit_label,
            "wengold.evidence.source": finding.get("source", report.get("source", "unknown")),
            "wengold.evidence.signals": signals,
            "wengold.finding.observation": finding.get("observed", ""),
        }
        title = str(finding.get("title", rule))
        spans.append(_span(
            trace_id, span_id, root_span_id, f"wave_debug.{rule}",
            event_ns, event_ns + 1, attrs,
            status=("STATUS_CODE_ERROR" if severity == "error"
                    else "STATUS_CODE_UNSET"),
            events=[_event("diagnostic.observation", event_ns, {
                "message": title,
                "observed": finding.get("observed", ""),
                "signals": signals,
            })],
        ))
        severity_text = "ERROR" if severity == "error" else "WARN"
        severity_number = 17 if severity == "error" else 13
        log_records.append({
            "timeUnixNano": str(event_ns),
            "observedTimeUnixNano": str(time.time_ns()),
            "severityText": severity_text,
            "severityNumber": severity_number,
            "body": {"stringValue": f"{title}: {finding.get('observed', '')}"},
            "attributes": _attrs(attrs),
            "traceId": trace_id,
            "spanId": span_id,
        })
        severity_counts[(severity, domain)] += 1

    transaction_span_ids: list[str] = []
    tx_counts: Counter[tuple[str, str]] = Counter()
    for index, transaction in enumerate(tx_rows):
        protocol = str(transaction.get("protocol", "unknown")).lower()
        operation = str(transaction.get("operation", "transaction")).lower()
        txid = str(transaction.get("transaction_id", index))
        start_raw = transaction.get("start_time", origin)
        end_raw = transaction.get("end_time", start_raw)
        start_ns, finish_ns = stamp(start_raw), stamp(end_raw)
        if finish_ns < start_ns:
            raise ValueError(f"transaction {txid} ends before it starts")
        span_id = _hex_id(f"{run_id}:transaction:{index}:{protocol}:{txid}", 16)
        transaction_span_ids.append(span_id)
        tx_status = str(transaction.get("status", "unknown")).lower()
        attrs = {
            "wengold.run.id": run_id,
            "wengold.protocol.name": protocol,
            "wengold.transaction.id": txid,
            "wengold.transaction.operation": operation,
            "wengold.transaction.address": transaction.get("address"),
            "wengold.transaction.response": transaction.get("response"),
            "wengold.transaction.beats": transaction.get("beats"),
            "wengold.transaction.status": tx_status,
            "wengold.simulation.start_time": str(start_raw),
            "wengold.simulation.end_time": str(end_raw),
            "wengold.simulation.time_unit": time_unit_label,
        }
        extra = transaction.get("attributes")
        if isinstance(extra, Mapping):
            attrs.update({f"wengold.transaction.{k}": v for k, v in extra.items()})
        spans.append(_span(
            trace_id, span_id, root_span_id, f"{protocol}.{operation}",
            start_ns, finish_ns, attrs,
            status=("STATUS_CODE_ERROR" if tx_status in {"error", "failed", "timeout"}
                    else "STATUS_CODE_UNSET"),
            events=[_event("transaction.completed", finish_ns, {
                "transaction_id": txid, "status": tx_status,
                "protocol": protocol, "operation": operation,
            })],
        ))
        tx_counts[(protocol, operation)] += 1

    resource_spans = [{
        "resource": _resource(),
        "scopeSpans": [{"scope": {"name": _SCOPE_NAME, "version": _SCOPE_VERSION},
                        "spans": spans}],
    }]

    metric_points = [{
        "startTimeUnixNano": str(run_start_unix_ns),
        "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
        "asInt": str(len(finding_rows)),
        "attributes": _attrs({"wengold.run.id": run_id}),
    }]
    metrics = [_sum_metric("wengold.wave_debug.findings", "{finding}", metric_points)]
    sample_count = int(report.get("samples", len(times)) or 0)
    metrics.append(_sum_metric("wengold.simulation.samples", "{sample}", [{
        "startTimeUnixNano": str(run_start_unix_ns),
        "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
        "asInt": str(sample_count),
        "attributes": _attrs({"wengold.run.id": run_id}),
    }]))
    domain_counts = report.get("summary", {}) or {}
    for key in ("rtl_signals", "testbench_signals", "unclassified", "ambiguous"):
        metrics.append(_sum_metric("wengold.wave_debug.signals", "{signal}", [{
            "startTimeUnixNano": str(run_start_unix_ns),
            "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
            "asInt": str(int(domain_counts.get(key, 0) or 0)),
            "attributes": _attrs({"wengold.run.id": run_id,
                                  "wengold.signal.domain": key}),
        }]))
    for (severity, domain), count in sorted(severity_counts.items()):
        metrics.append(_sum_metric("wengold.wave_debug.findings.by_severity", "{finding}", [{
            "startTimeUnixNano": str(run_start_unix_ns),
            "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
            "asInt": str(count),
            "attributes": _attrs({"wengold.run.id": run_id,
                                  "wengold.finding.severity": severity,
                                  "wengold.finding.domain": domain}),
        }]))
    for (protocol, operation), count in sorted(tx_counts.items()):
        metrics.append(_sum_metric("wengold.traffic.transactions", "{transaction}", [{
            "startTimeUnixNano": str(run_start_unix_ns),
            "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
            "asInt": str(count),
            "attributes": _attrs({"wengold.run.id": run_id,
                                  "wengold.protocol.name": protocol,
                                  "wengold.transaction.operation": operation}),
        }]))

    resource_metrics = [{
        "resource": _resource(),
        "scopeMetrics": [{"scope": {"name": _SCOPE_NAME, "version": _SCOPE_VERSION},
                          "metrics": metrics}],
    }]
    resource_logs = [{
        "resource": _resource(),
        "scopeLogs": [{"scope": {"name": _SCOPE_NAME, "version": _SCOPE_VERSION},
                       "logRecords": log_records}],
    }]
    return {
        "traces": {"resourceSpans": resource_spans},
        "metrics": {"resourceMetrics": resource_metrics},
        "logs": {"resourceLogs": resource_logs},
        "metadata": {
            "format": "WENGOLD OTLP JSON bundle",
            "run_id": run_id,
            "trace_id": trace_id,
            "root_span_id": root_span_id,
            "finding_span_ids": finding_span_ids,
            "transaction_span_ids": transaction_span_ids,
            "simulation_time_unit": time_unit_label,
            "simulation_time_unit_ns": str(unit_ns),
            "simulation_time_origin": str(origin),
            "timestamp_mapping": "synthetic Unix time anchored at run_start_unix_ns; raw simulator ticks are retained as attributes",
        },
    }


def write_otlp_bundle(path: str | Path, bundle: Mapping[str, Any]) -> Path:
    """Write the three OTLP signal payloads and provenance to a JSON bundle."""
    target = Path(path).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(target.name + ".tmp")
    try:
        temporary.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target

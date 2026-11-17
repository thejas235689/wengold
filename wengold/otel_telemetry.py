"""OpenTelemetry telemetry model and Dynatrace OTLP/HTTP Protobuf exporter.

The decoder/rule engine remains the source of truth. This module maps its
observations into OTLP JSON-mapped request models for inspection, and can
serialize and send binary Protobuf requests to Dynatrace.

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

__all__ = ["build_otlp_bundle", "write_otlp_bundle", "send_dynatrace_otlp", "DynatraceExportError"]

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
                      traffic_metrics: Mapping[str, Any] | None = None,
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
        traffic_metrics: Optional protocol metrics from a real decoder, such as
            AXI4 accepted transfers, stall cycles, maximum stalls and protocol errors.
        run_id: Stable simulation identifier; generated when omitted.
        run_start_unix_ns: Optional explicit synthetic Unix-nanosecond anchor. If
            omitted, the simulation is placed immediately before export and the
            display window is capped at 55 minutes for Dynatrace time acceptance.
        time_unit_ns: Nanoseconds per raw VCD timestamp tick. Pass the parsed
            VCD timescale value (for example Decimal("1") for 1 ns or
            Decimal("0.001") for 1 ps). If unknown, keep the default and set
            time_unit_label="tick"; the original raw times are retained.
        time_unit_label: Original VCD unit label, or "tick"/"cycle" if unknown.

    The returned bundle has three OTLP Protobuf JSON-mapped request models under
    traces, metrics and logs, plus WENGOLD-only provenance. Use the binary
    sender for Dynatrace; Dynatrace does not accept these JSON request models.
    """
    if not isinstance(report, Mapping):
        raise TypeError("report must be a mapping")
    run_id = str(run_id or uuid.uuid4().hex)
    if not run_id or len(run_id) > 256:
        raise ValueError("run_id must contain 1..256 characters")
    requested_unit_ns = _decimal(time_unit_ns, "time_unit_ns")
    if requested_unit_ns <= 0:
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
    end_time = max(all_times) if all_times else origin
    raw_duration_ns = max(Decimal(0), (end_time - origin) * requested_unit_ns)

    # Dynatrace rejects spans ending more than 10 minutes in the future and
    # older than 60 minutes in the past. For the default UI path, place the
    # simulation window immediately before export and cap its display duration
    # at 55 minutes. For long simulation time ranges, scale only the backend
    # display timeline; every original simulator timestamp and unit is retained
    # unchanged in attributes for real analysis.
    timeline_scale_factor = Decimal(1)
    if run_start_unix_ns is None:
        max_window_ns = Decimal(55 * 60 * 1_000_000_000)
        if raw_duration_ns > max_window_ns and raw_duration_ns > 0:
            timeline_scale_factor = max_window_ns / raw_duration_ns
        run_start_unix_ns = time.time_ns() - int(
            (raw_duration_ns * timeline_scale_factor).to_integral_value(
                rounding=ROUND_HALF_UP))
    if not isinstance(run_start_unix_ns, int) or run_start_unix_ns < 0:
        raise ValueError("run_start_unix_ns must be a non-negative integer")
    unit_ns = requested_unit_ns * timeline_scale_factor

    def stamp(value: Any) -> int:
        return _to_unix_ns(value, origin, unit_ns, run_start_unix_ns)

    run_end_ns = stamp(end_time) + max(1, int(unit_ns.to_integral_value(
        rounding=ROUND_HALF_UP)))
    trace_id = _hex_id("wengold:" + run_id, 32)
    root_span_id = _hex_id("wengold:root:" + run_id, 16)
    root_attrs = {
        "wengold.run.id": run_id,
        "wengold.evidence.source": report.get("source", "unknown"),
        "wengold.simulation.time_unit": time_unit_label,
        "wengold.simulation.time_unit_ns": str(requested_unit_ns),
        "wengold.otel.timeline_scale_factor": float(timeline_scale_factor),
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

    for metric_name, metric_value in sorted((traffic_metrics or {}).items()):
        key = str(metric_name).strip().lower().replace(" ", "_")
        if not key or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789_." for ch in key):
            raise ValueError(f"invalid traffic metric name: {metric_name!r}")
        if isinstance(metric_value, bool) or not isinstance(metric_value, (int, float)):
            raise ValueError(f"traffic metric {key} must be numeric")
        if not Decimal(str(metric_value)).is_finite() or metric_value < 0:
            raise ValueError(f"traffic metric {key} must be finite and non-negative")
        point = {
            "timeUnixNano": str(max(run_start_unix_ns + 1, run_end_ns)),
            "attributes": _attrs({
                "wengold.run.id": run_id,
                "wengold.protocol.name": "axi4",
                "wengold.traffic.metric": key,
            }),
        }
        if key.endswith("_max_stall_cycles"):
            point["asInt" if isinstance(metric_value, int) else "asDouble"] = str(metric_value) if isinstance(metric_value, int) else metric_value
            metrics.append({
                "name": f"wengold.traffic.axi4.{key}",
                "unit": "{cycle}",
                "gauge": {"dataPoints": [point]},
            })
        else:
            point["startTimeUnixNano"] = str(run_start_unix_ns)
            point["asInt" if isinstance(metric_value, int) else "asDouble"] = str(metric_value) if isinstance(metric_value, int) else metric_value
            metrics.append({
                "name": f"wengold.traffic.axi4.{key}",
                "unit": "{count}",
                "sum": {
                    "aggregationTemporality": "AGGREGATION_TEMPORALITY_CUMULATIVE",
                    "isMonotonic": True,
                    "dataPoints": [point],
                },
            })

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
            "simulation_time_unit_ns": str(requested_unit_ns),
            "otel_timeline_scale_factor": str(timeline_scale_factor),
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



class DynatraceExportError(RuntimeError):
    """An OTLP/HTTP export failed; the message never includes the API token."""

    def __init__(self, message: str, sent_signals: tuple[str, ...] = ()):
        super().__init__(message)
        self.sent_signals = sent_signals


def _protobuf_request(signal: str, payload: Mapping[str, Any]):
    """Convert the OTLP JSON mapping into the official binary Protobuf request."""
    try:
        from google.protobuf.json_format import ParseDict
        if signal == "traces":
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
                ExportTraceServiceRequest,
            )
            return ParseDict(payload, ExportTraceServiceRequest())
        if signal == "metrics":
            from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
                ExportMetricsServiceRequest,
            )
            return ParseDict(payload, ExportMetricsServiceRequest())
        if signal == "logs":
            from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
                ExportLogsServiceRequest,
            )
            return ParseDict(payload, ExportLogsServiceRequest())
    except ImportError as exc:
        raise RuntimeError(
            "Dynatrace export requires the optional OTel Protobuf dependency. "
            "Install WENGOLD with: python3 -m pip install -e '.[otel]'"
        ) from exc
    raise ValueError(f"unsupported OTLP signal: {signal}")


def _check_partial_success(signal: str, response_bytes: bytes) -> None:
    """Raise when the OTLP service explicitly reports rejected data."""
    if not response_bytes:
        return
    try:
        if signal == "traces":
            from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
                ExportTraceServiceResponse as Response,
            )
            rejected_field = "rejected_spans"
        elif signal == "metrics":
            from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
                ExportMetricsServiceResponse as Response,
            )
            rejected_field = "rejected_data_points"
        else:
            from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
                ExportLogsServiceResponse as Response,
            )
            rejected_field = "rejected_log_records"
        response = Response()
        response.ParseFromString(response_bytes)
    except ImportError:
        raise
    except Exception as exc:
        # Empty response bodies are valid. Non-empty malformed protobuf
        # responses should not be misreported as a successful export.
        if response_bytes:
            raise DynatraceExportError(
                f"Dynatrace returned an invalid OTLP {signal} response"
            ) from exc
        return
    if response.HasField("partial_success"):
        partial = response.partial_success
        rejected = getattr(partial, rejected_field, 0)
        detail = partial.error_message.strip()
        if rejected or detail:
            raise DynatraceExportError(
                f"Dynatrace partially accepted {signal}: rejected={rejected}; "
                f"{detail or 'server reported rejected telemetry'}"
            )


def send_dynatrace_otlp(bundle: Mapping[str, Any], endpoint: str, api_token: str,
                        *, timeout: float = 15.0) -> dict:
    """Send a WENGOLD bundle to Dynatrace using OTLP/HTTP binary Protobuf.

    endpoint is the OTLP base URL, for example
    https://<environment-id>.live.dynatrace.com/api/v2/otlp.
    api_token is sent only in the Authorization header. It is never written
    to disk, included in return values, or added to telemetry attributes.

    Traces, metrics and logs are posted separately to their documented OTLP
    paths. Direct upload is explicit and sequential; an error reports which
    earlier signal requests were already accepted.
    """
    from urllib.error import HTTPError, URLError
    from urllib.parse import urlsplit
    from urllib.request import Request, urlopen

    if not isinstance(bundle, Mapping):
        raise TypeError("bundle must be a mapping")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("Dynatrace OTLP endpoint is required")
    if not isinstance(api_token, str) or not api_token.strip():
        raise ValueError("Dynatrace API token is required")
    if not 1 <= float(timeout) <= 120:
        raise ValueError("timeout must be between 1 and 120 seconds")

    base = endpoint.strip().rstrip("/")
    parsed = urlsplit(base)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment):
        raise ValueError(
            "Dynatrace endpoint must be an HTTPS OTLP base URL without credentials, "
            "query or fragment"
        )
    if parsed.path.rstrip("/").endswith(("/v1/traces", "/v1/metrics", "/v1/logs")):
        raise ValueError("provide the OTLP base URL, not an individual signal path")
    if not parsed.path.rstrip("/").endswith("/api/v2/otlp"):
        raise ValueError("Dynatrace OTLP base URL must end in /api/v2/otlp")

    signal_models = (
        ("traces", "resourceSpans"),
        ("metrics", "resourceMetrics"),
        ("logs", "resourceLogs"),
    )
    sent: list[str] = []
    results: dict[str, dict[str, Any]] = {}
    for signal, root_key in signal_models:
        payload = bundle.get(signal)
        if not isinstance(payload, Mapping):
            raise ValueError(f"bundle is missing its {signal} OTLP model")
        root_rows = payload.get(root_key, [])
        if not root_rows and signal != "traces":
            continue
        request_message = _protobuf_request(signal, payload)
        body = request_message.SerializeToString()
        url = f"{base}/v1/{signal}"
        request = Request(
            url,
            data=body,
            headers={
                "Authorization": f"Bearer {api_token.strip()}",
                "Content-Type": "application/x-protobuf",
                "Accept": "application/x-protobuf",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=float(timeout)) as response:
                status_code = int(getattr(response, "status", response.getcode()))
                response_body = response.read()
        except HTTPError as exc:
            raise DynatraceExportError(
                f"Dynatrace rejected {signal} with HTTP {exc.code}",
                tuple(sent),
            ) from None
        except URLError as exc:
            raise DynatraceExportError(
                f"Could not reach Dynatrace for {signal}: {exc.reason}",
                tuple(sent),
            ) from None
        if not 200 <= status_code < 300:
            raise DynatraceExportError(
                f"Dynatrace returned HTTP {status_code} for {signal}",
                tuple(sent),
            )
        try:
            _check_partial_success(signal, response_body)
        except DynatraceExportError as exc:
            raise DynatraceExportError(str(exc), tuple(sent)) from None
        sent.append(signal)
        results[signal] = {"status": status_code, "bytes": len(body)}

    return {
        "status": "exported",
        "signals_sent": sent,
        "results": results,
        "endpoint_host": parsed.hostname,
    }

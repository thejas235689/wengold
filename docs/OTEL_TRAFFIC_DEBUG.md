# OpenTelemetry-backed RTL traffic observability

WENGOLD uses OpenTelemetry (OTel) as a **vendor-neutral observability model**.
Dynatrace is one supported backend. The OpenTelemetry layer does not decode
AXI/AHB/APB. WENGOLD protocol adapters and UVM monitors must first reconstruct
clock-accurate transactions from the actual bus handshakes. Wave Debug then
correlates those transactions with real waveform samples, assertions and logs.

## What the current branch adds

- An offline **Export OpenTelemetry bundle** action in the native Wave Debug
  panel, available after a VCD is loaded and analyzed.
- An explicit **Send via Dynatrace OTLP** action. The user must provide a
  Dynatrace OTLP base URL and platform token; the action sends only when clicked.
- OTLP JSON-mapped request models for traces, metrics and logs, plus
  WENGOLD-only provenance metadata. The offline JSON file is an inspection and
  interchange artifact; it is **not** the wire payload accepted by Dynatrace.
- A binary OTLP/HTTP Protobuf sender, enabled by the optional `otel` extra.
- Trace correlation: the simulation is a root span; each Wave Debug finding
  and each supplied, decoder-produced bus transaction is a child span.
  Diagnostic logs carry the matching Trace ID and Span ID.
- VCD time-unit preservation. Raw simulation timestamps and the declared unit
  are attached to findings and transactions. If a VCD has no timescale, it is
  labelled `tick`; the exporter does not claim that a tick is a nanosecond.
- A standard-library-only local bundle builder. Network requests occur only
  when the Dynatrace send action is explicitly activated.

Install the optional binary Protobuf support:

```bash
python3 -m pip install -e '.[otel]'
```

## Telemetry model

| WENGOLD evidence | OpenTelemetry representation |
| --- | --- |
| Simulation / regression run | Root span `wengold.simulation.run` |
| Decoded AXI/AHB/APB transaction | Child span such as `axi4.read` or `apb.write` |
| Wave Debug rule result | Child span `wave_debug.<rule>` |
| Diagnostic record | Log linked with the finding span's Trace ID and Span ID |
| Signal/sample/finding/transaction totals | Sum metrics with `wengold.*` attributes |

Correlation attributes include `wengold.run.id`, `wengold.protocol.name`,
`wengold.transaction.id`, `wengold.finding.rule`, and the original raw
simulator timestamp/unit. These are WENGOLD domain attributes, not claims that
OpenTelemetry defines AMBA protocol semantics.

### Transaction adapter input contract

`build_otlp_bundle()` accepts records produced by an actual decoder or UVM
monitor. Populate:

- `protocol`: AXI4, AXI4-Lite, AHB, or APB
- `operation`: read or write
- `transaction_id`: protocol ID where that protocol has one
- `start_time` / `end_time`: raw simulator timestamps
- `address`, `response`, `beats`, and `status`
- `attributes`: optional protocol fields such as burst, size, protection,
  QoS, source/destination and channel details

Protocols without a transaction ID require a decoder-generated transaction
key that is explicitly marked as synthetic. Signal-name heuristics must not be
used to fabricate a completed bus transaction.

## Data path

~~~text
VCD / FST / simulator monitor / UVM logs
                 |
        time-aware ingestion adapters
                 |
   protocol transaction model (AXI/AHB/APB)
                 |
     Wave Debug + deterministic rule checks
                 |
      OTel traces / metrics / correlated logs
                 |
        offline JSON bundle OR binary OTLP
                 |
       OpenTelemetry Collector (optional)
                 |
       Dynatrace or another observability backend
~~~

The current branch implements the Wave Debug-to-telemetry bridge, binary
Dynatrace upload path and generic transaction-to-span contract. It does **not**
yet include AXI4, AXI4-Lite, AHB or APB decoders, FST ingestion in this
telemetry path, automatic UVM log/transaction ingestion, or always-on streaming.
Those are the next protocol-adapter milestones.

## Dynatrace connection

Dynatrace requires OTLP over HTTP with **binary Protobuf** payloads. Its
documented signal paths are:

- traces: `/v1/traces`
- metrics: `/v1/metrics`
- logs: `/v1/logs`

For Dynatrace SaaS, the base endpoint is:

```text
https://<environment-id>.live.dynatrace.com/api/v2/otlp
```

For an Environment ActiveGate, the documented base endpoint is:

```text
https://<activegate-host>:9999/e/<environment-id>/api/v2/otlp
```

The sender appends each signal path and posts an `application/x-protobuf`
request. Dynatrace's current endpoint documentation states that JSON is not
supported for Protobuf ingest. Therefore the offline JSON archive must not
be posted directly to these endpoints.

The UI token field expects a **Dynatrace platform token** and sends it as
`Authorization: Bearer <token>`. The documented scopes are
`openpipeline:traces:ingest`, `openpipeline:metrics:ingest`, and
`openpipeline:logs:ingest`. Grant only the scopes required by the signals
being sent. The token is masked in the UI, kept in memory for the active
session, and never added to the export file or telemetry attributes.

For sustained or large regressions, the production architecture should route
binary OTLP through an OpenTelemetry Collector for batching, retries,
encryption, filtering and forwarding. The current Wave Debug UI sender targets
Dynatrace directly; a configurable Collector endpoint and Collector pipeline
are not yet wired into this branch. Keep future Collector credentials in its
secret-management mechanism.

## Time, limits and evidence integrity

OTLP span times are Unix nanoseconds. Simulator timestamps are a separate
clock domain. WENGOLD retains the raw simulator value and the declared VCD unit
as attributes and maps those values onto a synthetic Unix-time window for
timeline display. This mapping is not a wall-clock measurement and must not be
used for latency/throughput signoff. Use clock-edge-based decoder intervals
with a confirmed simulator timescale for real bus latency metrics.

Dynatrace documents trace span end-time acceptance bounds (60 minutes in the
past to 10 minutes in the future), along with per-span attribute/event limits
and ActiveGate request-size limits. Large regression uploads should use the
Collector and batching, rather than sending an unbounded single request.

Wave Debug findings remain diagnostic candidates. An error-status span means
the deterministic rule engine reported an error-severity observation; it does
not prove RTL causality or override assertion/formal results. AI-generated
explanations remain hypotheses. A transaction should only be marked as
protocol-failed when a deterministic protocol checker or assertion supplies
that evidence.

## Tests

```bash
python3 -m pytest -q tests/test_wave.py tests/test_wave_debug.py tests/test_otel_telemetry.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
```



## AXI4 traffic decoder

In the Linux desktop app, load and analyze a waveform, set the AXI4 interface
prefix (for example tb.dut.axi or tb.dut.m_axi), optionally set the full ACLK
hierarchy path, and press **Decode AXI4 traffic**. The stall threshold defaults
to 8 sampled rising-edge cycles. Completed read/write transactions appear in
the AXI4 transaction table. Select a transaction to cross-probe its address
channel and move the waveform to the transaction's start sample. Decoder
findings are added to the shared Wave Debug findings table.

The decoder requires these full AXI4 channels:

- AW: AWVALID, AWREADY, AWADDR, AWID, AWLEN
- W: WVALID, WREADY, WDATA, WLAST
- B: BVALID, BREADY, BID, BRESP
- AR: ARVALID, ARREADY, ARADDR, ARID, ARLEN
- R: RVALID, RREADY, RID, RDATA, RLAST, RRESP

ARESETn and burst/size/cache/protection/QoS/region/user sidebands are optional.
Signal discovery accepts dotted hierarchy names and flattened underscore names.
When more than one AXI interface is present, use an explicit interface prefix
or a logical-name-to-full-signal mapping rather than letting the decoder guess.

A VALID/READY transfer is counted only when both are known high at a rising
ACLK sample. A signal that is X/Z/unobserved is not treated as zero. When
VALID is high and READY is low, captured channel payload fields must remain
stable through the handshake; changes, unknown payload values, or VALID
deassertion before READY are reported as protocol findings. All
VALID-without-READY cycles contribute to stall metrics; a consecutive stall
reaching the configured threshold produces a backpressure warning. A warning
records observed wait time; it does not by itself claim that the DUT is faulty,
because backpressure can be intentionally applied by a legal receiver.

The decoder result can be exported with the same simulation trace:

```python
from wengold.axi4_telemetry import decode_axi4
from wengold.otel_telemetry import build_otlp_bundle

traffic = decode_axi4(wave, prefix="tb.dut.axi", max_stall_cycles=8)
combined_report = dict(wave_debug_report)
combined_report["findings"] = (
    list(wave_debug_report.get("findings", [])) + traffic["findings"]
)
bundle = build_otlp_bundle(
    combined_report,
    transactions=traffic["transactions"],
    traffic_metrics=traffic["metrics"],
    time_unit_ns=wave.get("time_unit_ns") or 1,
    time_unit_label=wave.get("time_unit_label") or "tick",
)
```

Only transactions completed before the end of the captured waveform are
exported as transaction spans. Outstanding requests are reported as
incomplete findings rather than fabricated completed transactions.

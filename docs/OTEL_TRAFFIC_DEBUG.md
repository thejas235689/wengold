# OpenTelemetry-backed traffic observability

WENGOLD uses OpenTelemetry (OTel) as a **vendor-neutral telemetry contract**.
Dynatrace is a supported destination, not a dependency of the RTL decoder or
the local debugger. OpenTelemetry does not decode AXI/AHB/APB; WENGOLD protocol
adapters must first turn real, clock-aligned bus handshakes into transaction
records. The telemetry bridge then exports those records and existing
Wave Debug observations as correlated OTLP signals.

## What this change adds

- The native **Wave Debug** panel has an explicit **Export OpenTelemetry bundle**
  action after a real VCD has been loaded and analyzed.
- The exported JSON contains three independent OTLP/HTTP bodies: traces,
  metrics, and logs, plus WENGOLD-only provenance metadata.
- A simulation is represented by a root span. Each Wave Debug finding is a
  child span and a correlated log record. Decoded bus transactions can also
  become child spans under the same trace.
- The exporter uses the VCD timescale when available. Raw simulator timestamps
  and the time unit remain attached to each finding/transaction. If the VCD
  lacks a timescale, the exporter labels the unit tick; it does not claim
  that those ticks are physical nanoseconds.
- The core exporter uses only the Python standard library. It does not contact
  Dynatrace, upload RTL, or require a Dynatrace account.

## Telemetry model

| WENGOLD evidence | OpenTelemetry representation |
| --- | --- |
| Simulation / regression run | Root span wengold.simulation.run |
| Decoded AXI/AHB/APB transaction | Child span such as axi4.read or apb.write |
| Wave Debug rule result | Child span wave_debug.[rule] |
| Diagnostic record | Log linked with the finding span's Trace ID and Span ID |
| Signal count, sample count, findings and transaction counts | Sum metrics with wengold.* attributes |

The stable correlation keys are wengold.run.id, the OTLP traceId/spanId,
wengold.transaction.id, wengold.protocol.name, wengold.finding.rule, and the
original simulator timestamp. These custom wengold.* attributes intentionally
avoid pretending that semiconductor bus protocol fields are already
standardized OpenTelemetry semantic conventions.

### Transaction adapter input contract

build_otlp_bundle() accepts transaction dictionaries produced by a real
decoder or UVM monitor. The first adapter should populate:

- protocol: AXI4, AXI4-Lite, AHB, or APB
- operation: read, write, or a protocol-specific operation
- transaction_id: protocol ID where the protocol has one
- start_time / end_time: raw simulator time values
- address, response, beats, and status
- attributes: optional protocol-specific fields such as burst, size,
  protection, QoS, source/destination or channel information

For protocols without transaction IDs, WENGOLD must use a decoder-generated
transaction key and preserve the fact that it is a synthetic key. Do not infer
a complete transaction from signal names alone.

## Data path

~~~text
VCD / FST / simulator monitor / UVM logs
                 |
        time-accurate adapters
                 |
       protocol transaction model
       (AXI4 / AXI4-Lite / AHB / APB)
                 |
       Wave Debug + rule engine
                 |
      OTel trace / metric / log model
                 |
           OTLP JSON bundle
                 |
        OpenTelemetry Collector
                 |
       Dynatrace or another backend
~~~

The current branch implements the Wave Debug to OTLP bundle stage and the
generic transaction-to-span contract. It does **not yet include** AXI4,
AXI4-Lite, AHB, or APB decoders, automatic UVM log ingestion, FST parsing,
continuous live export, or direct Dynatrace upload. Those are subsequent
features and must be implemented/tested as independent adapters.

## Dynatrace / Collector use

Dynatrace accepts OpenTelemetry Protocol (OTLP) signals directly over
OTLP/HTTP, and supports routing them through an OpenTelemetry Collector.
The generated bundle separates the three request bodies because the standard
OTLP signal endpoints are distinct:

- traces: /v1/traces
- metrics: /v1/metrics
- logs: /v1/logs

Configure an OpenTelemetry Collector with the appropriate Dynatrace OTLP
endpoint and ingest credentials, then map the bundle's traces, metrics,
and logs objects to the corresponding OTLP exporters. Keep API tokens in
the collector's secret-management mechanism or protected environment, never
in source control or the exported bundle. Start with a test project and
review what simulation metadata is permitted to leave the workstation.

No Dynatrace-specific code is required in WENGOLD. This keeps local debugging
usable offline and lets teams switch observability backends without changing
their protocol decoders.

## Time and evidence integrity

OTel span timestamps are Unix nanoseconds. Simulator time is a separate domain.
WENGOLD maps raw simulator ticks onto a synthetic Unix-time window anchored
at export time so the timeline is ordered in an observability backend; every
span also retains the original raw timestamp and time unit. This mapping is a
visual correlation aid, not wall-clock simulation duration or performance
measurement. Do not use it for throughput/latency signoff until a simulator
timescale and clock-edge-based transaction interval are confirmed.

Wave Debug findings remain diagnostic candidates. A span marked with error
status records the rule engine's severity; it does not prove RTL causality or
override assertion/formal results. AI-generated explanations remain
hypotheses. A transaction should only be marked as protocol-failed when a
deterministic protocol checker or assertion supplies that evidence.

## Tests

~~~bash
python3 -m pytest -q tests/test_wave.py tests/test_wave_debug.py tests/test_otel_telemetry.py
QT_QPA_PLATFORM=offscreen python3 -m pytest -q tests/test_native_studio.py
~~~

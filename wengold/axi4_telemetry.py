"""Cycle-accurate AXI4 transaction reconstruction from normalized waveforms.

The decoder samples only rising ACLK edges and accepts a transfer only when
VALID and READY are both known high on that edge. AXI4 write-data ordering,
per-ID read ordering, and response IDs are respected. It does not infer a
transaction from signal names or from a VALID assertion without READY.
"""
from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Mapping

__all__ = ["AXI4_REQUIRED", "discover_axi4_signal_map", "decode_axi4"]

AXI4_REQUIRED = (
    "AWVALID", "AWREADY", "AWADDR", "AWID", "AWLEN",
    "WVALID", "WREADY", "WDATA", "WLAST",
    "BVALID", "BREADY", "BID", "BRESP",
    "ARVALID", "ARREADY", "ARADDR", "ARID", "ARLEN",
    "RVALID", "RREADY", "RID", "RDATA", "RLAST", "RRESP",
)

AXI4_OPTIONAL = (
    "ARESETn", "AWBURST", "AWLOCK", "AWSIZE", "AWCACHE", "AWPROT",
    "AWQOS", "AWREGION", "AWUSER", "WSTRB", "WUSER", "BUSER",
    "ARBURST", "ARLOCK", "ARSIZE", "ARCACHE", "ARPROT", "ARQOS",
    "ARREGION", "ARUSER", "RUSER",
)

_BURST_NAMES = {0: "FIXED", 1: "INCR", 2: "WRAP", 3: "RESERVED"}
_RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}
_CHANNELS = {
    "AW": ("AWVALID", "AWREADY"),
    "W": ("WVALID", "WREADY"),
    "B": ("BVALID", "BREADY"),
    "AR": ("ARVALID", "ARREADY"),
    "R": ("RVALID", "RREADY"),
}


def _index_signals(wave: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    signals = wave.get("signals")
    if not isinstance(signals, list):
        raise ValueError("waveform must contain a signals list")
    result = {}
    for item in signals:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        if name in result:
            raise ValueError(f"duplicate waveform signal name: {name}")
        result[name] = item
    return result


def discover_axi4_signal_map(wave: Mapping[str, Any], prefix: str | None = None,
                             signal_map: Mapping[str, str] | None = None) -> dict[str, str]:
    """Resolve AXI channel names to full hierarchical waveform signal names.

    Prefer an explicit logical-name to full-name mapping. With prefix set,
    both dotted hierarchy names and underscore-flattened names are accepted.
    Without prefix, only a unique leaf/suffix match is accepted; multiple AXI
    interfaces must therefore be selected explicitly.
    """
    available = _index_signals(wave)
    folded = {name.casefold(): name for name in available}
    explicit = dict(signal_map or {})
    resolved: dict[str, str] = {}
    requested = AXI4_REQUIRED + AXI4_OPTIONAL
    norm_prefix = (prefix or "").strip().rstrip("._")
    for logical in requested:
        if logical in explicit:
            target = explicit[logical]
            if target not in available:
                raise ValueError(
                    f"signal_map maps {logical} to missing waveform signal {target!r}")
            resolved[logical] = target
            continue
        key = logical.casefold()
        candidates = set()
        if norm_prefix:
            for candidate in (
                f"{norm_prefix}.{logical.lower()}",
                f"{norm_prefix}_{logical.lower()}",
                f"{norm_prefix}.{logical}",
                f"{norm_prefix}_{logical}",
            ):
                actual = folded.get(candidate.casefold())
                if actual:
                    candidates.add(actual)
            prefix_dot = norm_prefix.casefold() + "."
            prefix_us = norm_prefix.casefold() + "_"
            for name in available:
                lowered = name.casefold()
                if lowered.startswith(prefix_dot) and lowered[len(prefix_dot):] == key:
                    candidates.add(name)
                if lowered.startswith(prefix_us) and lowered[len(prefix_us):] == key:
                    candidates.add(name)
        else:
            for name in available:
                leaf = name.rsplit(".", 1)[-1].casefold()
                if leaf == key or leaf.endswith("_" + key):
                    candidates.add(name)
        if len(candidates) == 1:
            resolved[logical] = next(iter(candidates))
        elif len(candidates) > 1:
            raise ValueError(
                f"ambiguous AXI4 signal {logical}: {sorted(candidates)}; "
                "supply prefix or signal_map")
        elif logical in AXI4_REQUIRED:
            raise ValueError(
                f"missing required AXI4 signal {logical}; provide an interface "
                "prefix or an explicit signal_map")
    return resolved


def _known_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip().lower().replace("_", "")
        if not text or any(ch in text for ch in "xz?"):
            return None
        try:
            return int(text, 0)
        except ValueError:
            try:
                return int(text, 2)
            except ValueError:
                return None
    return None


def _burst(value: int | None) -> str:
    return _BURST_NAMES.get(value, "UNKNOWN")


def _response(value: int | None) -> str:
    return _RESP_NAMES.get(value, "UNKNOWN")


def decode_axi4(wave: Mapping[str, Any], *,
                prefix: str | None = None,
                signal_map: Mapping[str, str] | None = None,
                clock: str | None = None,
                max_stall_cycles: int = 8,
                max_findings: int = 1000,
                max_transactions: int = 10000) -> dict:
    """Decode real AXI4 transfers from rising-edge waveform samples.

    The required signal set includes all five AXI4 channels and enough
    information to associate beats/responses with IDs. User/sideband signals
    are optional. AW/W ordering follows AXI4 (no write-data interleaving);
    B responses are matched by BID and reads by RID. A protocol issue is
    recorded when the captured evidence violates an expected relationship.
    """
    if not isinstance(max_stall_cycles, int) or max_stall_cycles < 1:
        raise ValueError("max_stall_cycles must be a positive integer")
    if not isinstance(max_findings, int) or not 1 <= max_findings <= 10000:
        raise ValueError("max_findings must be between 1 and 10000")
    if not isinstance(max_transactions, int) or not 1 <= max_transactions <= 100000:
        raise ValueError("max_transactions must be between 1 and 100000")

    names = _index_signals(wave)
    resolved = discover_axi4_signal_map(wave, prefix, signal_map)
    clk_name = clock or wave.get("clock") or resolved.get("ACLK")
    if not clk_name or clk_name not in names:
        raise ValueError(
            "AXI4 clock is not identified; pass clock='<full signal name>' "
            "or ensure the waveform clock is selected")
    times = list(wave.get("times") or range(int(wave.get("cycles", 0))))
    if not times:
        raise ValueError("waveform has no timestamped samples")
    sample_count = len(times)

    values: dict[str, list[Any]] = {}
    for logical, actual in resolved.items():
        vals = list(names[actual].get("values") or [])
        if len(vals) < sample_count:
            vals.extend([None] * (sample_count - len(vals)))
        values[logical] = vals[:sample_count]
    clk_values = list(names[clk_name].get("values") or [])
    if len(clk_values) < sample_count:
        clk_values.extend([None] * (sample_count - len(clk_values)))

    findings: list[dict] = []
    transactions: list[dict] = []
    finding_counts: dict[str, int] = defaultdict(int)
    stall_cycles: dict[str, int] = defaultdict(int)
    stall_max: dict[str, int] = defaultdict(int)
    stall_count: dict[str, int] = defaultdict(int)
    beats_by_channel: dict[str, int] = defaultdict(int)
    protocol_errors = 0
    reset_cycles = 0
    rising_edges = 0
    transaction_drops = 0
    unknown_controls = [0]

    def issue(rule: str, title: str, index: int, signals: list[str],
              observed: str, severity: str = "error",
              details: Mapping[str, Any] | None = None) -> None:
        nonlocal protocol_errors
        finding_counts[rule] += 1
        if severity == "error":
            protocol_errors += 1
        if len(findings) >= max_findings:
            return
        row = {
            "rule": rule,
            "title": title,
            "severity": severity,
            "domain": "rtl",
            "assessment": "deterministic_protocol_observation",
            "time": times[index],
            "sample_index": index,
            "signals": signals,
            "observed": observed,
            "source": "cycle-accurate AXI4 waveform decoder",
        }
        if details:
            row["details"] = dict(details)
        findings.append(row)

    def sig(logical: str) -> str:
        return resolved.get(logical, "")

    def val(logical: str, index: int) -> int | None:
        seq = values.get(logical)
        return _known_int(seq[index]) if seq is not None else None

    def make_transaction(kind: str, ident: int, addr: int | None, length: int,
                         index: int, fields: Mapping[str, Any]) -> dict:
        return {
            "protocol": "axi4",
            "operation": kind,
            "transaction_id": str(ident),
            "id": ident,
            "address": None if addr is None else hex(addr),
            "start_time": times[index],
            "end_time": times[index],
            "expected_beats": length + 1,
            "beats": 0,
            "status": "pending",
            "attributes": dict(fields),
            "_start_index": index,
            "_errors": [],
        }

    def finish_transaction(tx: dict, index: int, response: str | None = None) -> None:
        nonlocal transaction_drops
        tx["end_time"] = times[index]
        tx["status"] = "protocol_error" if tx["_errors"] else "ok"
        if response:
            tx["response"] = response
            if response in ("SLVERR", "DECERR"):
                tx["status"] = "error"
        tx["attributes"]["observed_beats"] = tx["beats"]
        tx["attributes"]["expected_beats"] = tx["expected_beats"]
        tx["attributes"]["error_count"] = len(tx["_errors"])
        tx["attributes"]["start_sample_index"] = tx.get("_start_index")
        tx["attributes"]["completion_index"] = index
        tx.pop("_start_index", None)
        tx.pop("_errors", None)
        if len(transactions) < max_transactions:
            transactions.append(tx)
        else:
            transaction_drops += 1

    def tx_issue(tx: dict, rule: str, title: str, index: int,
                 signals: list[str], observed: str) -> None:
        tx["_errors"].append(rule)
        issue(rule, title, index, signals, observed, details={
            "transaction_id": tx["transaction_id"],
            "address": tx["address"],
        })

    pending_aw = deque()
    awaiting_b: dict[int, deque] = defaultdict(deque)
    pending_reads: dict[int, deque] = defaultdict(deque)
    stalls: dict[str, dict] = {}

    def update_stall(channel: str, valid: int | None, ready: int | None,
                     index: int) -> None:
        current = stalls.get(channel)
        valid_name, ready_name = _CHANNELS[channel]
        signals = [sig(valid_name), sig(ready_name)]
        if valid is None or ready is None:
            if current:
                stalls.pop(channel, None)
            issue("unknown_handshake_control",
                  f"Unknown {channel} handshake control",
                  index, signals,
                  f"VALID={valid!r}, READY={ready!r}")
            unknown_controls[0] += 1
            return
        if valid == 1 and ready == 0:
            if current is None:
                current = {"start_index": index, "cycles": 0}
                stalls[channel] = current
            current["cycles"] += 1
            stall_cycles[channel] += 1
            stall_max[channel] = max(stall_max[channel], current["cycles"])
            return
        if current is not None:
            duration = current["cycles"]
            if valid == 0:
                issue("valid_dropped_before_ready",
                      f"{channel}VALID dropped before handshake",
                      index, signals,
                      f"VALID was deasserted after {duration} stalled cycle(s) without VALID && READY")
            elif duration >= max_stall_cycles:
                stall_count[channel] += 1
                issue(f"axi4_{channel.lower()}_backpressure",
                      f"AXI4 {channel} channel backpressure",
                      current["start_index"], signals,
                      f"{channel} channel stalled for {duration} rising-edge cycle(s); "
                      f"handshake/resolution at sample {index}",
                      severity="warning",
                      details={"stall_cycles": duration,
                               "stall_end_time": times[index]})
            stalls.pop(channel, None)

    previous_clock = None
    for index in range(sample_count):
        clock_value = _known_int(clk_values[index])
        rising = previous_clock == 0 and clock_value == 1
        previous_clock = clock_value
        if not rising:
            continue
        rising_edges += 1

        resetn = val("ARESETn", index) if "ARESETn" in values else 1
        if resetn is None:
            issue("unknown_reset",
                  "AXI4 reset value is unknown",
                  index, [sig("ARESETn")],
                  "ARESETn is X/Z/unobserved at a rising ACLK edge")
            continue
        if resetn == 0:
            reset_cycles += 1
            outstanding = list(pending_aw)
            outstanding += [tx for q in awaiting_b.values() for tx in q]
            outstanding += [tx for q in pending_reads.values() for tx in q]
            for tx in outstanding:
                issue("reset_aborted_transaction",
                      "AXI4 transaction aborted by reset",
                      index, [sig("ARESETn")],
                      f"{tx['operation']} ID={tx['transaction_id']} was outstanding at reset")
            pending_aw.clear()
            awaiting_b.clear()
            pending_reads.clear()
            stalls.clear()
            continue

        for channel, (valid_name, ready_name) in _CHANNELS.items():
            update_stall(channel, val(valid_name, index),
                         val(ready_name, index), index)

        awvalid, awready = val("AWVALID", index), val("AWREADY", index)
        if awvalid == 1 and awready == 1:
            awid, awaddr, awlen = (val("AWID", index), val("AWADDR", index),
                                   val("AWLEN", index))
            if awid is None or awlen is None:
                issue("unknown_aw_fields", "AXI4 AW transfer has unknown ID/LEN",
                      index, [sig("AWID"), sig("AWLEN")],
                      f"AWID={awid!r}, AWLEN={awlen!r}")
            else:
                attrs = {
                    "burst": _burst(val("AWBURST", index)) if "AWBURST" in values else "UNSPECIFIED",
                    "size_bytes_log2": val("AWSIZE", index),
                    "lock": val("AWLOCK", index),
                    "cache": val("AWCACHE", index),
                    "prot": val("AWPROT", index),
                    "qos": val("AWQOS", index),
                    "region": val("AWREGION", index),
                }
                tx = make_transaction("write", awid, awaddr, awlen, index, attrs)
                if awaddr is None:
                    tx_issue(tx, "unknown_aw_address", "AXI4 AWADDR is unknown",
                             index, [sig("AWADDR")], "AWADDR is X/Z/unobserved on an accepted AW transfer")
                if attrs["burst"] == "UNKNOWN" and "AWBURST" in values:
                    tx_issue(tx, "unknown_aw_burst", "AXI4 AWBURST is unknown",
                             index, [sig("AWBURST")], "AWBURST is X/Z/unobserved")
                if attrs["burst"] == "RESERVED":
                    tx_issue(tx, "reserved_aw_burst", "Reserved AWBURST encoding",
                             index, [sig("AWBURST")], "AWBURST=2'b11")
                pending_aw.append(tx)
                beats_by_channel["AW"] += 1

        wvalid, wready = val("WVALID", index), val("WREADY", index)
        if wvalid == 1 and wready == 1:
            beats_by_channel["W"] += 1
            if not pending_aw:
                issue("orphan_w_beat", "AXI4 W beat without an accepted AW",
                      index, [sig("WVALID"), sig("WREADY"), sig("WLAST")],
                      "WVALID && WREADY but no outstanding write address")
            else:
                tx = pending_aw[0]
                tx["beats"] += 1
                beat_index = tx["beats"]
                wlast = val("WLAST", index)
                expected_last = beat_index == tx["expected_beats"]
                data = val("WDATA", index)
                if data is None:
                    tx["attributes"]["unknown_data_beats"] = (
                        tx["attributes"].get("unknown_data_beats", 0) + 1)
                elif "first_data" not in tx["attributes"]:
                    tx["attributes"]["first_data"] = hex(data)
                tx["attributes"]["last_data"] = None if data is None else hex(data)
                if "WSTRB" in values:
                    strobe = val("WSTRB", index)
                    if strobe is not None:
                        tx["attributes"]["last_strobe"] = hex(strobe)
                if beat_index > tx["expected_beats"] and not tx["attributes"].get("burst_overrun_reported"):
                    tx_issue(tx, "write_burst_overrun", "AXI4 write contains more W beats than AWLEN",
                             index, [sig("AWLEN"), sig("WLAST")],
                             f"observed beat {beat_index} exceeds expected {tx['expected_beats']}")
                    tx["attributes"]["burst_overrun_reported"] = True
                if wlast is None:
                    tx_issue(tx, "unknown_wlast", "AXI4 WLAST is unknown",
                             index, [sig("WLAST")], "WLAST is X/Z/unobserved on an accepted W beat")
                elif (wlast == 1) != expected_last:
                    rule = "early_wlast" if wlast == 1 else "missing_wlast"
                    tx_issue(tx, rule, "AXI4 WLAST does not match AWLEN",
                             index, [sig("AWLEN"), sig("WLAST")],
                             f"beat {beat_index}/{tx['expected_beats']}, WLAST={wlast}")
                if wlast == 1:
                    pending_aw.popleft()
                    awaiting_b[tx["id"]].append(tx)

        bvalid, bready = val("BVALID", index), val("BREADY", index)
        if bvalid == 1 and bready == 1:
            bid, bresp = val("BID", index), val("BRESP", index)
            if bid is None:
                issue("unknown_bid", "AXI4 B response has unknown BID",
                      index, [sig("BID")], "BID is X/Z/unobserved on an accepted B response")
            elif not awaiting_b[bid]:
                if any(tx["id"] == bid for tx in pending_aw):
                    issue("b_before_wlast", "AXI4 B response arrived before WLAST",
                          index, [sig("BID"), sig("WLAST")],
                          f"BID={bid}; W data for that ID is not complete")
                else:
                    issue("orphan_b_response", "AXI4 B response has no completed write",
                          index, [sig("BID"), sig("BRESP")],
                          f"BID={bid} has no completed write awaiting a response")
            else:
                tx = awaiting_b[bid].popleft()
                response = _response(bresp)
                if bresp is None:
                    tx_issue(tx, "unknown_bresp", "AXI4 BRESP is unknown",
                             index, [sig("BRESP")], "BRESP is X/Z/unobserved")
                elif bresp >= 2:
                    tx_issue(tx, "write_response_error", "AXI4 write response reported an error",
                             index, [sig("BRESP")], f"BRESP={response}")
                finish_transaction(tx, index, response)
                beats_by_channel["B"] += 1

        arvalid, arready = val("ARVALID", index), val("ARREADY", index)
        if arvalid == 1 and arready == 1:
            arid, araddr, arlen = (val("ARID", index), val("ARADDR", index),
                                   val("ARLEN", index))
            if arid is None or arlen is None:
                issue("unknown_ar_fields", "AXI4 AR transfer has unknown ID/LEN",
                      index, [sig("ARID"), sig("ARLEN")],
                      f"ARID={arid!r}, ARLEN={arlen!r}")
            else:
                attrs = {
                    "burst": _burst(val("ARBURST", index)) if "ARBURST" in values else "UNSPECIFIED",
                    "size_bytes_log2": val("ARSIZE", index),
                    "lock": val("ARLOCK", index),
                    "cache": val("ARCACHE", index),
                    "prot": val("ARPROT", index),
                    "qos": val("ARQOS", index),
                    "region": val("ARREGION", index),
                }
                tx = make_transaction("read", arid, araddr, arlen, index, attrs)
                if araddr is None:
                    tx_issue(tx, "unknown_ar_address", "AXI4 ARADDR is unknown",
                             index, [sig("ARADDR")], "ARADDR is X/Z/unobserved on an accepted AR transfer")
                if attrs["burst"] == "UNKNOWN" and "ARBURST" in values:
                    tx_issue(tx, "unknown_ar_burst", "AXI4 ARBURST is unknown",
                             index, [sig("ARBURST")], "ARBURST is X/Z/unobserved")
                if attrs["burst"] == "RESERVED":
                    tx_issue(tx, "reserved_ar_burst", "Reserved ARBURST encoding",
                             index, [sig("ARBURST")], "ARBURST=2'b11")
                pending_reads[arid].append(tx)
                beats_by_channel["AR"] += 1

        rvalid, rready = val("RVALID", index), val("RREADY", index)
        if rvalid == 1 and rready == 1:
            rid, rresp, rlast = (val("RID", index), val("RRESP", index),
                                 val("RLAST", index))
            rdata = val("RDATA", index)
            if rid is None:
                issue("unknown_rid", "AXI4 R beat has unknown RID",
                      index, [sig("RID")], "RID is X/Z/unobserved on an accepted R beat")
            elif not pending_reads[rid]:
                issue("orphan_r_beat", "AXI4 R beat has no outstanding AR",
                      index, [sig("RID"), sig("RVALID"), sig("RREADY")],
                      f"RID={rid} has no accepted read address awaiting data")
            else:
                tx = pending_reads[rid][0]
                tx["beats"] += 1
                beat_index = tx["beats"]
                expected_last = beat_index == tx["expected_beats"]
                if beat_index > tx["expected_beats"] and not tx["attributes"].get("burst_overrun_reported"):
                    tx_issue(tx, "read_burst_overrun", "AXI4 read contains more R beats than ARLEN",
                             index, [sig("ARLEN"), sig("RLAST")],
                             f"observed beat {beat_index} exceeds expected {tx['expected_beats']}")
                    tx["attributes"]["burst_overrun_reported"] = True
                if rdata is None:
                    tx["attributes"]["unknown_data_beats"] = (
                        tx["attributes"].get("unknown_data_beats", 0) + 1)
                elif "first_data" not in tx["attributes"]:
                    tx["attributes"]["first_data"] = hex(rdata)
                tx["attributes"]["last_data"] = None if rdata is None else hex(rdata)
                tx["attributes"].setdefault("response_beats", []).append(_response(rresp))
                if rlast is None:
                    tx_issue(tx, "unknown_rlast", "AXI4 RLAST is unknown",
                             index, [sig("RLAST")], "RLAST is X/Z/unobserved on an accepted R beat")
                elif (rlast == 1) != expected_last:
                    rule = "early_rlast" if rlast == 1 else "missing_rlast"
                    tx_issue(tx, rule, "AXI4 RLAST does not match ARLEN",
                             index, [sig("ARLEN"), sig("RLAST")],
                             f"beat {beat_index}/{tx['expected_beats']}, RLAST={rlast}")
                if rresp is None:
                    tx_issue(tx, "unknown_rresp", "AXI4 RRESP is unknown",
                             index, [sig("RRESP")], "RRESP is X/Z/unobserved")
                elif rresp >= 2:
                    tx_issue(tx, "read_response_error", "AXI4 read response reported an error",
                             index, [sig("RRESP")], f"RRESP={_response(rresp)}")
                beats_by_channel["R"] += 1
                if rlast == 1:
                    pending_reads[rid].popleft()
                    finish_transaction(tx, index, _response(rresp))

    for tx in list(pending_aw):
        issue("incomplete_write_data",
              "AXI4 write data did not complete before end of capture",
              tx.get("_start_index", sample_count - 1),
              [sig("AWVALID"), sig("WVALID"), sig("WLAST")],
              f"write ID={tx['transaction_id']}: {tx['beats']}/{tx['expected_beats']} beat(s) accepted")
    for queue in awaiting_b.values():
        for tx in queue:
            issue("missing_b_response", "AXI4 write has no B response before end of capture",
                  tx.get("_start_index", sample_count - 1),
                  [sig("BVALID"), sig("BREADY"), sig("BID")],
                  f"write ID={tx['transaction_id']} completed WLAST but has no B response")
    for queue in pending_reads.values():
        for tx in queue:
            issue("incomplete_read_data", "AXI4 read did not complete before end of capture",
                  tx.get("_start_index", sample_count - 1),
                  [sig("RVALID"), sig("RREADY"), sig("RLAST")],
                  f"read ID={tx['transaction_id']}: {tx['beats']}/{tx['expected_beats']} beat(s) accepted")
    for channel, stall in stalls.items():
        duration = stall["cycles"]
        if duration >= max_stall_cycles:
            stall_count[channel] += 1
            issue(f"axi4_{channel.lower()}_backpressure",
                  f"AXI4 {channel} channel backpressure at end of capture",
                  stall["start_index"],
                  [sig(_CHANNELS[channel][0]), sig(_CHANNELS[channel][1])],
                  f"{channel} channel remained stalled for {duration} rising-edge cycle(s)",
                  severity="warning",
                  details={"stall_cycles": duration, "capture_ended_during_stall": True})

    if transaction_drops:
        issue("transaction_output_limit",
              "AXI4 transaction output limit reached",
              sample_count - 1, [],
              f"{transaction_drops} completed transaction(s) omitted after max_transactions")

    metrics: dict[str, int] = {
        "transactions": len(transactions),
        "protocol_errors": protocol_errors,
        "stall_cycles_total": sum(stall_cycles.values()),
        "rising_edges": rising_edges,
        "reset_cycles": reset_cycles,
        "unknown_handshake_controls": unknown_controls[0],
        "transaction_drops": transaction_drops,
    }
    for channel in _CHANNELS:
        metrics[f"{channel.lower()}_stall_cycles"] = stall_cycles[channel]
        metrics[f"{channel.lower()}_max_stall_cycles"] = stall_max[channel]
        metrics[f"{channel.lower()}_stall_events"] = stall_count[channel]
        metrics[f"{channel.lower()}_accepted_transfers"] = beats_by_channel[channel]

    return {
        "protocol": "AXI4",
        "status": "decoded_with_issues" if protocol_errors or findings else "decoded",
        "clock": clk_name,
        "interface_prefix": prefix,
        "signal_map": dict(resolved),
        "sampled_rising_edges": rising_edges,
        "transactions": transactions,
        "findings": findings,
        "metrics": metrics,
        "limits": [
            "AXI4 W channel has no WID; W beats are associated in accepted AW order.",
            "Read responses are associated by RID and preserved in same-ID order.",
            "VALID/READY transfers are sampled only at rising ACLK edges.",
            "Unknown X/Z control samples are reported, never treated as zero.",
            "Transactions still outstanding at capture end are incomplete, not completed.",
            "User sidebands are included only when present in the waveform.",
        ],
    }

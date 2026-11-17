"""Clocked APB and AXI4/AXI4-Lite observations from digital traces.

VCD records end-of-timestep values. Sample the stable values just before each
known rising edge, and report same-tick control changes as ambiguous instead of
guessing simulator scheduling. This is not a protocol conformance checker.
"""
from __future__ import annotations

from collections import defaultdict, deque

from .wave_inspect import logic_at, render_value

AXI_FIELDS = {
    "AW": ("AWADDR", "AWID", "AWLEN", "AWSIZE", "AWBURST"),
    "W": ("WDATA", "WSTRB", "WLAST"),
    "B": ("BID", "BRESP"),
    "AR": ("ARADDR", "ARID", "ARLEN", "ARSIZE", "ARBURST"),
    "R": ("RDATA", "RID", "RRESP", "RLAST"),
}
APB_FIELDS = ("PADDR", "PWRITE", "PWDATA", "PRDATA", "PSLVERR", "PSTRB")


def decode(trace, protocol, prefix="", clock_name="", reset_name=""):
    if protocol not in ("APB", "AXI4", "AXI4-Lite"):
        raise ValueError("Choose APB, AXI4 or AXI4-Lite")
    signals = {s["name"]: s for s in trace["signals"]}
    by_fold = defaultdict(list)
    for name, sig in signals.items():
        by_fold[name.casefold()].append(sig)

    def find(name, required=False, bit=False):
        matches = ([signals[name]] if name in signals else by_fold.get(name.casefold(), []))
        if len(matches) > 1:
            raise ValueError(f"Ambiguous trace signal {name}")
        if matches:
            if bit and matches[0]["width"] != 1:
                raise ValueError(f"{name} must be a one-bit signal")
            return matches[0]
        if required:
            raise ValueError(f"Missing trace signal {name}")
        return None

    apb = protocol == "APB"
    lite = protocol == "AXI4-Lite"
    prefix = prefix.strip()
    clock = find(clock_name.strip() or prefix + ("PCLK" if apb else "ACLK"), True, True)
    reset = find(reset_name.strip(), True, True) if reset_name.strip() else find(
        prefix + ("PRESETn" if apb else "ARESETn"), bit=True)
    if apb:
        keys = ("PSEL", "PENABLE", "PREADY")
        gates = {"APB": [find(prefix + k, True, True) for k in keys]}
        fields = {"APB": {k: find(prefix + k, bit=k in ("PWRITE", "PSLVERR")) for k in APB_FIELDS}}
    else:
        gates, fields = {}, {}
        for lane, names in AXI_FIELDS.items():
            valid, ready = [find(prefix + lane + k, bit=True) for k in ("VALID", "READY")]
            if valid and ready:
                gates[lane] = [valid, ready]
                fields[lane] = {k: find(prefix + k, bit=k in ("WLAST", "RLAST")) for k in names}
        if not gates:
            raise ValueError("No complete AXI VALID/READY channel pair matched the prefix")
    events, transactions = [], []
    counters = defaultdict(int)
    stalls = defaultdict(int)
    writes, reads = defaultdict(deque), defaultdict(deque)
    reset_edges = 0
    uncertain_pairs = set()
    apb_start = None

    def key(lane, captured):
        addr_key, ret_key = ("AWID", "BID") if lane in ("AW", "B") else ("ARID", "RID")
        if lite:
            return "—"
        # Do not assume ID zero if full AXI IDs were not captured.
        k = addr_key if lane in ("AW", "AR") else ret_key
        return captured.get(k)

    def break_pairing(lane):
        # A missed address or response can shift a FIFO of same-ID operations.
        # Don't report a false latency after losing alignment. A known reset
        # reestablishes the empty baseline.
        if lane in ("AW", "B"):
            uncertain_pairs.add("write")
            writes.clear()
        elif lane in ("AR", "R"):
            uncertain_pairs.add("read")
            reads.clear()

    for edge in range(1, trace["cycles"]):
        if (logic_at(clock, edge - 1), logic_at(clock, edge)) != ("0", "1"):
            continue
        before = edge - 1
        if reset:
            old_reset, new_reset = logic_at(reset, before), logic_at(reset, edge)
            if old_reset != "1" or new_reset != "1":
                if "0" in (old_reset, new_reset) and not (
                        {old_reset, new_reset} & {"x", "z"}):
                    uncertain_pairs.clear()
                elif not apb:
                    uncertain_pairs.update(("read", "write"))
                stalls.clear()
                writes.clear()
                reads.clear()
                reset_edges += 1
                apb_start = None
                continue
        for lane, control in gates.items():
            old = tuple(logic_at(sig, before) for sig in control)
            new = tuple(logic_at(sig, edge) for sig in control)
            if old[0] == new[0] == "0":
                stalls[lane] = 0
                if apb:
                    apb_start = None
                continue
            if apb and old[:2] == new[:2] == ("1", "0"):
                stalls[lane] = 0
                apb_start = trace["times"][edge]
                continue
            if old != new or any(v not in ("0", "1") for v in old):
                counters["ambiguous_control"] += 1
                if not apb:
                    break_pairing(lane)
                stalls.pop(lane, None)
                if apb:
                    apb_start = None
                continue
            if old[-1] == "0":
                stalls[lane] += 1
                continue
            captured = {}
            ambiguous = []
            for field, sig in fields[lane].items():
                if sig is None:
                    continue
                prev, curr = logic_at(sig, before), logic_at(sig, edge)
                if prev != curr:
                    ambiguous.append(field)
                elif not any(x in prev for x in "xz"):
                    captured[field] = render_value(sig, before, "Hex")
                else:
                    ambiguous.append(field)
            item = {"sample": edge, "tick": trace["times"][edge], "lane": lane,
                    "fields": captured, "ambiguous": ambiguous, "wait": stalls.pop(lane, 0)}
            events.append(item)
            if apb:
                typ = captured.get("PWRITE")
                transactions.append({"kind": "Write" if typ == "0x1" else
                                     "Read" if typ == "0x0" else "Direction unknown",
                                     "id": "—", "start": apb_start, "end": item["tick"],
                                     "addr": captured.get("PADDR"), "sample": edge})
                apb_start = None
            elif lane in ("AW", "AR"):
                group = "write" if lane == "AW" else "read"
                ident = key(lane, captured)
                if ident is None:
                    break_pairing(lane)
                elif group not in uncertain_pairs:
                    (writes if lane == "AW" else reads)[ident].append(item)
            elif lane == "R" and not lite and "RLAST" not in captured:
                break_pairing(lane)
            elif lane == "B" or (lane == "R" and (lite or captured.get("RLAST") == "0x1")):
                ident = key(lane, captured)
                if ident is None:
                    break_pairing(lane)
                queue = (writes if lane == "B" else reads).get(ident)
                start = queue.popleft() if queue else None
                if start:
                    transactions.append({"kind": "Write response" if lane == "B" else "Read completion",
                                         "id": ident, "start": start["tick"], "end": item["tick"],
                                         "addr": start["fields"].get("AWADDR" if lane == "B" else "ARADDR"),
                                         "sample": edge})
                else:
                    counters["unpaired_response"] += 1
    return {"events": events, "transactions": transactions, "lanes": list(gates),
            "missing_lanes": [] if apb else [name for name in AXI_FIELDS if name not in gates],
            "skipped_control": counters["ambiguous_control"], "reset_edges": reset_edges,
            "unpaired_responses": counters["unpaired_response"],
            "pending_addresses": sum(map(len, writes.values())) + sum(map(len, reads.values())),
            "pairing_uncertain": sorted(uncertain_pairs),
            "times": trace["times"], "timescale": trace.get("timescale"),
            "reset": reset["name"] if reset else None}

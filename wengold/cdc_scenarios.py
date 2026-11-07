"""Clause 5 — output collateral requirements for integration-level RDC verification.

Clause 5 is different in kind from the rest of the standard. Clauses 4, 6, 7 and 8
define a format and its rules; Clause 5 defines **six integration scenarios** and, for
each, what an IP must capture in its output collateral so that RDC can be verified at
the integration level without reading the IP's RTL.

So the question this answers is not "is the file valid" — `cdc_standard.check` does
that — but **"which of the six scenarios does this collateral actually support, and
what is missing from the ones it does not"**.

What the standard's own examples require
----------------------------------------
Every predicate below is read off the example the standard prints for the scenario,
not off an intuition about what "should" be needed. In particular:

  * **§5.4** (internal data source) — Example 34 declares **one** port, `rdcq0_i`,
    `-direction input -type rdc_control -blocking_polarity low
    -associated_to_reset rst1_n_i -associated_to_clocks clk0_i
    -rdc_data_from_reset rst0_n_i`. It does **not** put `-rdc_control` on an input
    data port: the gating is internal, and the data port is not declared at all. A
    predicate that demanded `-rdc_control` on a data port therefore rejected a
    collateral built to the standard's own example — the tool contradicting the
    standard. It no longer does.
  * **§5.5** (external data source) — Example 35 declares `rdcq0_i` (input,
    `rdc_control`, `-blocking_polarity low`, **no** `-rdc_data_from_reset`) *and*
    `data0_i` (`-direction input -type data -rdc_control rdcq0_i`). The pairing of
    a data port with a control, in the same direction, is what distinguishes it.
  * **§5.6** (external gating) — Example 36 pairs output `data0_o`
    (`-rdc_control rdcq0_o`) with output `rdcq0_o`, which carries
    `-blocking_polarity low` **and** `-rdc_data_from_reset rst0_n_i`.
  * **§5.7** (internal gating) — Example 37 is `data0_o` with
    `-associated_from_reset rst1_n_i` and **no** control at all.

Two things follow, and both are enforced here:

  * a scenario is never granted without the evidence its example carries
    (`-blocking_polarity` is mandatory — Clause 5: "The -blocking_polarity
    attribute shall be specified whenever an rdc_control signal is associated with
    a port for RDC handling" — and a control must exist, be `-type rdc_control`, and
    for §5.6 carry `-rdc_data_from_reset`);
  * a scenario is never denied when the standard's own example satisfies it.

Direction and pairing are resolved per scenario
-----------------------------------------------
§5.4/§5.5 are input-port scenarios and §5.6 is an output-port scenario, and each
example declares its control in the same direction as the port it gates. So the
control a data port names is resolved *by name, type and direction*, and a control
declared for the output side is not evidence for an input-port scenario (or the
reverse).

`-rdc_control`, not `-cdc_control`
----------------------------------
Clause 5 defines `-rdc_control` as "the RDC control or net that is associated with
the data port to avoid a timing violation on RDC". `-cdc_control` is the CDC
attribute; accepting it here let a pure CDC pairing satisfy an RDC scenario. It is
no longer accepted as RDC evidence.

What this does not do
---------------------
It does not verify the scenarios. Each one carries checks the standard requires —
minimum pulse width, reset sequencing, control setup/hold, and the structural
conditions on an rdc_control signal (Clause 5.4/5.5 integration requirement a) — and
those are verification obligations, not collateral properties. `cdc_sva` emits the
assertions for the ones that can be asserted at a port boundary; whether they pass is
a run, not a parse.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Scenario", "check_scenarios", "render"]

_INPUT = {"input", "in"}
_OUTPUT = {"output", "out"}


@dataclass
class Scenario:
    """One Clause 5 scenario and what the collateral does or does not provide."""
    clause: str
    name: str
    covered: bool
    evidence: str = ""
    missing: list[str] = field(default_factory=list)

    def render(self) -> str:
        mark = "yes" if self.covered else "no "
        head = f"  [{mark}] {self.clause} {self.name}"
        lines = [head]
        if self.evidence:
            lines.append(f"        {self.evidence}")
        for m in self.missing:
            lines.append(f"        missing: {m}")
        return "\n".join(lines)


def _all(col) -> list:
    """`Collateral.ports` is a dict keyed by port name, not a list."""
    ports = getattr(col, "ports", None) or {}
    return list(ports.values()) if isinstance(ports, dict) else list(ports)


def _ports(col, kind=None, direction=None):
    for p in _all(col):
        if kind and p.type != kind:
            continue
        if direction and p.direction not in (direction, direction[0]):
            continue
        yield p


def _attr(port, name: str) -> str:
    """A raw attribute value, stripped, or "" when absent."""
    raw = getattr(port, "raw", None) or {}
    return (raw.get(name) or "").strip()


def _rdc_control_ref(port) -> str:
    """The RDC control a data port names.

    Only `-rdc_control` counts. `-cdc_control` is the CDC attribute (Clause 5 defines
    `-rdc_control` as "the RDC control or net that is associated with the data port to
    avoid a timing violation on RDC"), and accepting it here let a pure CDC pairing
    satisfy an RDC scenario.
    """
    return _attr(port, "rdc_control")


def _any_control(port) -> str:
    """Either control attribute — used only to disqualify a port from §5.7."""
    return _rdc_control_ref(port) or _attr(port, "cdc_control")


def _data_ports(col, direction):
    return [p for p in _ports(col, "data", direction)]


def _seq_name(seq) -> str:
    """`Collateral.resets` holds dicts, not objects."""
    if isinstance(seq, dict):
        return seq.get("name") or "?"
    return getattr(seq, "name", "?")


def _seq_signals(seq) -> list:
    """The resets an assertion sequence orders, in order.

    Clause 5: "assert_sequence: Specifies the required order in which multiple reset
    signals shall be asserted." Example 33 is
    `-assert_sequence {rst1_n_i rst0_n_i}`.
    """
    if isinstance(seq, dict):
        raw = seq.get("assert_sequence") or ""
    else:
        raw = getattr(seq, "assert_sequence", "") or ""
    raw = raw.strip().strip("{}").strip()
    return raw.split()


def _seq_order(seq) -> str:
    return " ".join(_seq_signals(seq)) or "(no -assert_sequence)"


def _by_name(col) -> dict:
    return {p.name: p for p in _all(col)}


def check_scenarios(col) -> list[Scenario]:
    """Which of the six Clause 5 scenarios this collateral supports."""
    out: list[Scenario] = []
    ports = _all(col)
    by_name = _by_name(col)
    seqs = list(getattr(col, "reset_sequences", None)
                or getattr(col, "resets", None) or [])

    # ---- §5.2 Scenario 1: input interface drives an internal synchroniser
    # Example 32: `-logic internal sync` on the receiving input port.
    cands = [p for p in _data_ports(col, "input")
             if "sync" in (p.logic or "") and p.associated_to_reset]
    if cands:
        out.append(Scenario(
            "§5.2", "input interface drives an internal synchroniser", True,
            evidence=f"{cands[0].name} declares -logic \"{cands[0].logic}\" and "
                     f"-associated_to_reset"))
    else:
        missing = []
        if not [p for p in _data_ports(col, "input") if p.logic]:
            missing.append("-logic on an input data port (the synchroniser "
                           "attribute is what makes the RDC resolved)")
        if not [p for p in _data_ports(col, "input") if p.associated_to_reset]:
            missing.append("-associated_to_reset on the receiving port")
        out.append(Scenario(
            "§5.2", "input interface drives an internal synchroniser", False,
            missing=missing or ["an input data port"]))

    # ---- §5.3 Scenario 2: IP-level reset sequence
    #
    # Clause 5.3's integration requirement is "The reset sequence shall be specified
    # in the IP collateral", and Clause 5 defines `assert_sequence` as "the required
    # order in which multiple reset signals shall be asserted" (Example 33:
    # `-assert_sequence {rst1_n_i rst0_n_i}`). A sequence declaration that states no
    # order — no `-assert_sequence`, or one naming a single reset — does not specify
    # a sequence, so it is not evidence for this scenario.
    ordered = [s for s in seqs if len(_seq_signals(s)) >= 2]
    if ordered:
        out.append(Scenario(
            "§5.3", "IP-level reset sequence", True,
            evidence=(f"{_seq_name(ordered[0])} = "
                      f"{{{_seq_order(ordered[0])}}} "
                      f"({len(_seq_signals(ordered[0]))} resets, in order)")))
    else:
        if not seqs:
            miss = ["set_reset_assertion_sequence -assert_sequence, which is how "
                    "the required reset order is expressed"]
        else:
            miss = [f"{_seq_name(seqs[0])} specifies no order: -assert_sequence must "
                    f"name the multiple reset signals in the order they are "
                    f"asserted (Example 33: -assert_sequence {{rst1_n_i rst0_n_i}}), "
                    f"not {'an empty list' if not _seq_signals(seqs[0]) else 'a single reset'}"]
        out.append(Scenario("§5.3", "IP-level reset sequence", False, missing=miss))

    # ---- §5.4 Scenario 3: interface RDC control for safe internal RDC
    #
    # Example 34 — the whole of it:
    #     accellera_cdc::set_port -name rdcq0_i -direction input
    #       -type rdc_control -blocking_polarity low
    #       -associated_to_reset rst1_n_i -associated_to_clocks clk0_i
    #       -rdc_data_from_reset rst0_n_i
    # One port, no data port, and therefore no `-rdc_control` anywhere. The evidence
    # for §5.4 is the input rdc_control port carrying `-rdc_data_from_reset` (the
    # internal reset it blocks — Clause 5.4 integration requirement b) and
    # `-blocking_polarity` (Clause 5: "The -blocking_polarity attribute shall be
    # specified whenever an rdc_control signal is associated with a port for RDC
    # handling").
    input_controls = [p for p in ports
                      if p.type == "rdc_control" and p.direction in _INPUT]
    with_source_reset = [p for p in input_controls if _attr(p, "rdc_data_from_reset")]
    s54 = [p for p in with_source_reset if _attr(p, "blocking_polarity")]
    if s54:
        c = s54[0]
        out.append(Scenario(
            "§5.4", "interface RDC control, safe internal RDC", True,
            evidence=(f"{c.name} is -direction input -type rdc_control with "
                      f"-rdc_data_from_reset {_attr(c, 'rdc_data_from_reset')} and "
                      f"-blocking_polarity {_attr(c, 'blocking_polarity')}")))
    else:
        miss = []
        if not input_controls:
            miss.append("an input port declared -type rdc_control (Example 34 "
                        "declares rdcq0_i that way; an output control, or a port "
                        "declared only -type cdc_control, is not evidence for this "
                        "input-port scenario)")
        else:
            if not with_source_reset:
                miss.append("-rdc_data_from_reset on the input rdc_control port — "
                            "the internal reset it blocks, which is what makes this "
                            "scenario distinct from §5.5 (Example 34: "
                            "-rdc_data_from_reset rst0_n_i)")
            if not [p for p in input_controls if _attr(p, "blocking_polarity")]:
                miss.append("-blocking_polarity on "
                            f"{input_controls[0].name}: Clause 5 requires it "
                            "whenever an rdc_control signal is associated with a "
                            "port for RDC handling (Example 34: "
                            "-blocking_polarity low)")
        out.append(Scenario("§5.4", "interface RDC control, safe internal RDC",
                            False, missing=miss))

    # ---- §5.5 Scenario 4: interface RDC control for safe interface RDC crossing
    #
    # Example 35 pairs an input data port with a control, in the same direction:
    #     data0_i: -direction input -type data -rdc_control rdcq0_i
    #     rdcq0_i: -direction input -type rdc_control -blocking_polarity low
    #              (no -rdc_data_from_reset: the reset it blocks is external)
    # Each of those is checked: the control must exist, be -type rdc_control, be an
    # input, carry -blocking_polarity, and carry no -rdc_data_from_reset.
    s55 = None
    s55_miss: list[str] = []
    input_data = _data_ports(col, "input")
    referencing = [p for p in input_data if _rdc_control_ref(p)]
    if not referencing:
        if [p for p in input_data if _attr(p, "cdc_control")]:
            s55_miss.append("-rdc_control on the input data port; -cdc_control "
                            "describes a CDC pairing and does not satisfy an RDC "
                            "scenario (Example 35: -rdc_control rdcq0_i)")
        else:
            s55_miss.append("-rdc_control on the input data port it blocks "
                            "(Example 35: data0_i with -rdc_control rdcq0_i)")
    for p in referencing:
        ref = _rdc_control_ref(p)
        ctl = by_name.get(ref)
        why = []
        if ctl is None:
            why.append(f"{p.name} names -rdc_control {ref}, which is not declared "
                       f"(the standard requires every referenced declaration to "
                       f"exist)")
        else:
            if ctl.type != "rdc_control":
                why.append(f"{p.name} names -rdc_control {ref}, declared -type "
                           f"{ctl.type or '(none)'}; §5.5 needs -type rdc_control "
                           f"(Example 35: rdcq0_i)")
            if ctl.direction not in _INPUT:
                why.append(f"{ref} is -direction {ctl.direction or '(none)'}; §5.5 "
                           f"is an input-port scenario and Example 35 declares its "
                           f"control -direction input")
            if _attr(ctl, "rdc_data_from_reset"):
                why.append(f"{ref} carries -rdc_data_from_reset "
                           f"{_attr(ctl, 'rdc_data_from_reset')}; with the internal "
                           f"reset named the modelling is §5.4, not §5.5")
            if not _attr(ctl, "blocking_polarity"):
                why.append(f"-blocking_polarity on {ref}: Clause 5 requires it "
                           f"whenever an rdc_control signal is associated with a "
                           f"port for RDC handling (Example 35: "
                           f"-blocking_polarity low)")
        if why:
            s55_miss.extend(why)
        elif s55 is None:
            s55 = (p, ctl)
    if s55:
        p, ctl = s55
        out.append(Scenario(
            "§5.5", "interface RDC control, safe interface RDC crossing", True,
            evidence=(f"{p.name} is -direction input -type data with -rdc_control "
                      f"{ctl.name}; {ctl.name} is -direction input -type "
                      f"rdc_control with -blocking_polarity "
                      f"{_attr(ctl, 'blocking_polarity')} and no "
                      f"-rdc_data_from_reset, so the reset it blocks is external")))
    else:
        out.append(Scenario("§5.5",
                            "interface RDC control, safe interface RDC crossing",
                            False, missing=s55_miss or ["an input data port"]))

    # ---- §5.6 Scenario 5: output interface RDC control for safe split RDC
    #
    # Example 36 pairs output data0_o (-rdc_control rdcq0_o) with output rdcq0_o,
    # which carries both -blocking_polarity low and -rdc_data_from_reset rst0_n_i.
    # All three are required here: the control must exist, be -type rdc_control, be
    # an output, and carry -rdc_data_from_reset and -blocking_polarity.
    s56 = None
    s56_miss: list[str] = []
    output_data = _data_ports(col, "output")
    gated = [p for p in output_data if _rdc_control_ref(p)]
    if not gated:
        if [p for p in output_data if _attr(p, "cdc_control")]:
            s56_miss.append("-rdc_control on the output data port; -cdc_control "
                            "describes a CDC pairing and does not satisfy an RDC "
                            "scenario (Example 36: -rdc_control rdcq0_o)")
        else:
            s56_miss.append("-rdc_control on the output data port it blocks "
                            "(Example 36: data0_o with -rdc_control rdcq0_o)")
    for p in gated:
        ref = _rdc_control_ref(p)
        ctl = by_name.get(ref)
        why = []
        if ctl is None:
            why.append(f"{p.name} names -rdc_control {ref}, which is not declared "
                       f"(the standard requires every referenced declaration to "
                       f"exist)")
        else:
            if ctl.type != "rdc_control":
                why.append(f"{p.name} names -rdc_control {ref}, declared -type "
                           f"{ctl.type or '(none)'}; §5.6 needs -type rdc_control "
                           f"(Example 36: rdcq0_o)")
            if ctl.direction not in _OUTPUT:
                why.append(f"{ref} is -direction {ctl.direction or '(none)'}; §5.6 "
                           f"is an output-port scenario and Example 36 declares its "
                           f"control -direction output")
            if not _attr(ctl, "rdc_data_from_reset"):
                why.append(f"-rdc_data_from_reset on {ref} — the source reset it "
                           f"blocks (Example 36: -rdc_data_from_reset rst0_n_i)")
            if not _attr(ctl, "blocking_polarity"):
                why.append(f"-blocking_polarity on {ref}: Clause 5 requires it "
                           f"whenever an rdc_control signal is associated with a "
                           f"port for RDC handling (Example 36: "
                           f"-blocking_polarity low)")
        if why:
            s56_miss.extend(why)
        elif s56 is None:
            s56 = (p, ctl)
    if s56:
        p, ctl = s56
        out.append(Scenario(
            "§5.6", "output interface RDC control, safe split RDC", True,
            evidence=(f"{p.name} is -direction output -type data gated by "
                      f"-rdc_control {ctl.name}; {ctl.name} is -direction output "
                      f"-type rdc_control with -rdc_data_from_reset "
                      f"{_attr(ctl, 'rdc_data_from_reset')} and -blocking_polarity "
                      f"{_attr(ctl, 'blocking_polarity')}")))
    else:
        out.append(Scenario("§5.6", "output interface RDC control, safe split RDC",
                            False, missing=s56_miss or ["an output data port"]))

    # ---- §5.7 Scenario 6: output interface prequalified for safe RDC crossing
    #
    # Example 37: `data0_o` with -associated_from_reset rst1_n_i and no control at
    # all. Any control attribute disqualifies it — a port that names a control is
    # §5.6's modelling, not this one.
    prequalified = [p for p in _data_ports(col, "output")
                    if not _any_control(p) and p.associated_from_reset]
    if prequalified:
        p = prequalified[0]
        out.append(Scenario(
            "§5.7", "output interface prequalified for safe RDC crossing", True,
            evidence=(f"{p.name} declares -associated_from_reset "
                      f"{p.associated_from_reset[0] if p.associated_from_reset else '?'} "
                      f"and no -rdc_control")))
    else:
        out.append(Scenario(
            "§5.7", "output interface prequalified for safe RDC crossing", False,
            missing=["an output data port with -associated_from_reset and no "
                     "-rdc_control — being in the receiving reset domain is what "
                     "prequalifies it"]))

    return out


def render(scenarios: list[Scenario]) -> str:
    if not scenarios:
        return "  no Clause 5 scenarios assessed"
    covered = [s for s in scenarios if s.covered]
    lines = [f"  Clause 5 — RDC collateral: {len(covered)} of {len(scenarios)} "
             f"scenario(s) supported"]
    lines.append("")
    for s in scenarios:
        lines.append(s.render())
    lines.append("")
    lines.append("  a supported scenario means the collateral carries what the "
                 "standard requires")
    lines.append("  for integration-level RDC verification. It does NOT mean the "
                 "scenario's")
    lines.append("  checks pass — minimum pulse width, reset sequencing and control "
                 "setup/hold")
    lines.append("  are verification obligations, not collateral properties.")
    return "\n".join(lines)

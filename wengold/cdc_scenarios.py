"""Clause 5 — output collateral requirements for integration-level RDC verification.

Clause 5 is different in kind from the rest of the standard. Clauses 4, 6, 7 and 8
define a format and its rules; Clause 5 defines **six integration scenarios** and, for
each, what an IP must capture in its output collateral so that RDC can be verified at
the integration level without reading the IP's RTL.

So the question this answers is not "is the file valid" — `cdc_standard.check` does
that — but **"which of the six scenarios does this collateral actually support, and
what is missing from the ones it does not"**.

All six are distinguishable, and my first version said two pairs were not
-----------------------------------------------------------------------
The first version of this module reported §5.4/§5.5 and §5.6/§5.7 as pairs, claiming
they differed in design intent rather than in attributes. **That was wrong**, and I
had asserted it without reading the standard's examples. They differ in the
collateral:

  * **§5.4** (internal data source) — the `rdc_control` port carries
    `-rdc_data_from_reset`, naming the reset *inside* the IP that it blocks.
  * **§5.5** (external data source) — the same modelling *without* that attribute,
    because the reset it blocks belongs to the integration, not the IP.
  * **§5.6** (external gating) — the output data port carries `-rdc_control`.
  * **§5.7** (internal gating) — the output carries `-associated_from_reset` and
    **no** control: being in the receiving reset domain is what prequalifies it.

What this does not do
---------------------
It does not verify the scenarios. Each one carries checks the standard requires —
minimum pulse width, reset sequencing, control setup/hold — and those are
verification obligations, not collateral properties. `cdc_sva` emits the assertions
for the ones that can be asserted at a port boundary; whether they pass is a run, not
a parse.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["Scenario", "check_scenarios", "render"]


@dataclass
class Scenario:
    """One Clause 5 scenario and what the collateral does or does not provide."""
    clause: str
    name: str
    covered: bool
    evidence: str = ""
    missing: list[str] = field(default_factory=list)
    also: str = ""          # the indistinguishable sibling, if any

    def render(self) -> str:
        mark = "yes" if self.covered else "no "
        head = f"  [{mark}] {self.clause} {self.name}"
        lines = [head]
        if self.evidence:
            lines.append(f"        {self.evidence}")
        for m in self.missing:
            lines.append(f"        missing: {m}")
        if self.also:
            lines.append(f"        {self.also}")
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


def _control_of(port) -> str:
    """The control signal a data port declares, or ""."""
    return (port.raw.get("rdc_control") or port.raw.get("cdc_control") or "").strip()


def _data_ports(col, direction):
    return [p for p in _ports(col, "data", direction)]


def _seq_name(seq) -> str:
    """`Collateral.resets` holds dicts, not objects."""
    if isinstance(seq, dict):
        return seq.get("name") or "?"
    return getattr(seq, "name", "?")


def _seq_order(seq) -> str:
    if isinstance(seq, dict):
        return seq.get("assert_sequence") or "?"
    return getattr(seq, "assert_sequence", "?")


def check_scenarios(col) -> list[Scenario]:
    """Which of the six Clause 5 scenarios this collateral supports."""
    out: list[Scenario] = []
    ports = _all(col)
    seqs = list(getattr(col, "reset_sequences", None)
                or getattr(col, "resets", None) or [])

    # ---- §5.2 Scenario 1: input interface drives an internal synchroniser
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
    if seqs:
        out.append(Scenario(
            "§5.3", "IP-level reset sequence", True,
            evidence=(f"{len(seqs)} set_reset_assertion_sequence declaration(s), "
                      f"e.g. {_seq_name(seqs[0])} "
                      f"= {_seq_order(seqs[0])}")))
    else:
        out.append(Scenario(
            "§5.3", "IP-level reset sequence", False,
            missing=["set_reset_assertion_sequence -assert_sequence, which is how "
                     "the required reset order is expressed"]))

    # ---- §5.4 and §5.5: input port blocked by an RDC control
    #
    # They ARE distinguishable, and my first version said they were not. The
    # standard's own examples differ: in §5.4 (internal data source) the
    # `rdc_control` port carries `-rdc_data_from_reset` naming the internal reset
    # it blocks; in §5.5 (external data source) it does not, because the reset it
    # blocks belongs to the integration, not the IP.
    controls = [p for p in ports if p.type in ("rdc_control", "cdc_control")]
    blocked_inputs = [p for p in _data_ports(col, "input") if _control_of(p)]
    internal_controls = [p for p in controls if p.raw.get("rdc_data_from_reset")]

    if blocked_inputs and internal_controls:
        out.append(Scenario(
            "§5.4", "interface RDC control, safe internal RDC", True,
            evidence=(f"{blocked_inputs[0].name} blocked by {_control_of(blocked_inputs[0])}; "
                      f"{internal_controls[0].name} declares -rdc_data_from_reset "
                      f"{internal_controls[0].raw.get('rdc_data_from_reset')}")))
    else:
        miss = []
        if not blocked_inputs:
            miss.append("-rdc_control on the input data port it blocks")
        if not internal_controls:
            miss.append("-rdc_data_from_reset on the rdc_control port — the "
                        "internal reset it blocks, which is what makes this "
                        "scenario distinct from §5.5")
        out.append(Scenario("§5.4", "interface RDC control, safe internal RDC",
                            False, missing=miss))

    if blocked_inputs and controls and not internal_controls:
        out.append(Scenario(
            "§5.5", "interface RDC control, safe interface RDC crossing", True,
            evidence=(f"{blocked_inputs[0].name} blocked by "
                      f"{_control_of(blocked_inputs[0])}; the control declares no "
                      f"-rdc_data_from_reset, so the reset it blocks is external")))
    else:
        miss = []
        if not blocked_inputs:
            miss.append("-rdc_control on the input data port it blocks")
        if internal_controls:
            miss.append("no -rdc_data_from_reset on the rdc_control port — with it "
                        "declared the modelling is §5.4, not §5.5")
        elif not controls:
            miss.append("a port declared -type rdc_control (or cdc_control)")
        out.append(Scenario("§5.5",
                            "interface RDC control, safe interface RDC crossing",
                            False, missing=miss))

    # ---- §5.6 and §5.7: output port, external or internal gating
    #
    # Also distinguishable: §5.6 blocks the output with an `-rdc_control`; §5.7
    # relies on the output already being in the receiving reset domain
    # (`-associated_from_reset`) with no control at all.
    gated_outputs = [p for p in _data_ports(col, "output") if _control_of(p)]
    prequalified = [p for p in _data_ports(col, "output")
                    if not _control_of(p) and p.associated_from_reset]

    if gated_outputs:
        out.append(Scenario(
            "§5.6", "output interface RDC control, safe split RDC", True,
            evidence=(f"{gated_outputs[0].name} is gated by "
                      f"{_control_of(gated_outputs[0])}")))
    else:
        miss = []
        if not controls:
            miss.append("a port declared -type rdc_control (or cdc_control)")
        if not gated_outputs:
            miss.append("-rdc_control on the output data port it blocks")
        out.append(Scenario("§5.6", "output interface RDC control, safe split RDC",
                            False, missing=miss))

    if prequalified:
        out.append(Scenario(
            "§5.7", "output interface prequalified for safe RDC crossing", True,
            evidence=(f"{prequalified[0].name} declares -associated_from_reset "
                      f"{prequalified[0].associated_from_reset[0] if prequalified[0].associated_from_reset else '?'} "
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

"""Clause 5 — output collateral requirements for integration-level RDC verification.

Clause 5 is different in kind from the rest of the standard. Clauses 4, 6, 7 and 8
define a format and its rules; Clause 5 defines **six integration scenarios** and, for
each, what an IP must capture in its output collateral so that RDC can be verified at
the integration level without reading the IP's RTL.

So the question this answers is not "is the file valid" — `cdc_standard.check` does
that — but **"which of the six scenarios does this collateral actually support, and
what is missing from the ones it does not"**.

What can and cannot be told apart
---------------------------------
The six scenarios are distinguished partly by modelling and partly by *design
intent*. Two pairs are indistinguishable from collateral alone:

  * §5.4 and §5.5 both model an input port blocked by an RDC control. They differ in
    whether the data source is internal or external to the IP — which the collateral
    expresses as a reset association, not as a distinct attribute.
  * §5.6 and §5.7 both model an output port with an RDC control. They differ in
    whether the output is gated internally or externally.

This module reports those as **pairs** and says so. Claiming to distinguish them
would be inventing a rule the standard does not give, and a wrong "scenario 4
covered" is worse than an honest "3 or 4".

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

    # ---- §5.4 / §5.5: input port blocked by an RDC control
    controls = [p for p in ports if p.type in ("rdc_control", "cdc_control")]
    blocked_inputs = [p for p in _data_ports(col, "input")
                      if p.raw.get("rdc_control") or p.raw.get("cdc_control")]
    if controls and blocked_inputs:
        ev = (f"{blocked_inputs[0].name} is blocked by "
              f"{blocked_inputs[0].raw.get('rdc_control') or blocked_inputs[0].raw.get('cdc_control')}")
        out.append(Scenario("§5.4", "interface RDC control, safe internal RDC", True,
                            evidence=ev,
                            also="indistinguishable from §5.5 without design intent"))
    else:
        miss = []
        if not controls:
            miss.append("a port declared -type rdc_control (or cdc_control)")
        if not blocked_inputs:
            miss.append("-rdc_control on the input data port it blocks")
        out.append(Scenario("§5.4", "interface RDC control, safe internal RDC", False,
                            missing=miss,
                            also="indistinguishable from §5.5 without design intent"))

    # ---- §5.6 / §5.7: output port with an RDC control
    blocked_outputs = [p for p in _data_ports(col, "output")
                       if p.raw.get("rdc_control") or p.raw.get("cdc_control")]
    if controls and blocked_outputs:
        out.append(Scenario("§5.6", "output interface RDC control, safe split RDC",
                            True,
                            evidence=f"{blocked_outputs[0].name} is gated by an RDC "
                                     f"control",
                            also="indistinguishable from §5.7 without design intent"))
    else:
        miss = []
        if not controls:
            miss.append("a port declared -type rdc_control (or cdc_control)")
        if not blocked_outputs:
            miss.append("-rdc_control on the output data port it blocks")
        out.append(Scenario("§5.6", "output interface RDC control, safe split RDC",
                            False, missing=miss,
                            also="indistinguishable from §5.7 without design intent"))

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

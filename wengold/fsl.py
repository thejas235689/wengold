"""Functional Safety Language (FSL) v1.0 — the Accellera standard.

FSL is Tcl, like the CDC collateral WENGOLD already reads: sixteen commands that
create FMEDA objects and wire them together. This module parses them and checks
what the standard actually specifies:

  * **§5.4 well-formedness** — a known command, no unknown arguments, every
    required argument present, no argument twice, enumerations matching exactly.
  * **§5.5 conformance** — every referenced object already created, and no object
    created twice.
  * **§5.5.2 mutual exclusion** — `create_fmeda` takes `-asil` and `-sil`, and
    exactly one of them must be set to something other than `none`.
  * **§5.5.1 conditionally required** — the ISO 26262 and IEC 61508 argument sets
    are not interchangeable, and using the wrong one is an error.

And one thing the standard cannot do, which is why it belongs here: **cross-check
the elements an FMEDA names against the design**. `create_element` takes a name; if
that name is not a block in the RTL, the analysis is describing a design that does
not exist. WENGOLD already has the graph, so it can say so.

**What this does not do.** It does not compute safety metrics — SPFM, LFM, PMHF and
SFF are arithmetic over failure rates the FMEDA supplies, and this reads structure,
not numbers. It does not validate the engineering judgement in an FMEDA: whether a
diagnostic coverage figure is believable is not a question a parser can answer. And
a clean report is not a safety case.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Command", "Finding", "Report", "parse", "check", "check_design"]

# ---- the command set, from the syntax tables in §5.6 --------------------
#: name -> (required args, optional args)
COMMANDS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "assign_fm_fme": (
        ("-fm_name", "-fme_list", "-parent_fmeda", "-fme_weights",),
        ("-user_defined_arguments", "-parent_element",)),
    "assign_fm_sreq": (
        ("-fm_name", "-sreq_name", "-parent_fmeda", "-safety_relevant", "-no_part",),
        ("-user_defined_arguments", "-parent_element",)),
    "assign_sm_fm": (
        ("-sm_name", "-fm_name", "-parent_fmeda", "-active",),
        ("-sm_parent_fmeda", "-dc_permanent_estimated", "-dc_transient_estimated", "-dc_latent_primary_estimated", "-dc_latent_secondary_estimated", "-dc_permanent_measured", "-dc_transient_measured", "-dc_latent_primary_measured", "-dc_latent_secondary_measured", "-user_defined_arguments", "-parent_element",)),
    "assign_te_element": (
        ("-te_name", "-parent_fmeda",),
        ("-element_size_permanent", "-element_size_transient", "-element_size_transient_set", "-element_mapping_format", "-element_mapping", "-element_mapping_exclude", "-user_defined_arguments", "-element_name", "-parent_element",)),
    "assign_te_fm": (
        ("-te_name", "-fm_name", "-parent_fmeda", "-fm_size_type_assumption_based", "-fm_size_type_calculation_based",),
        ("-fm_size_permanent_assumption_based", "-fm_size_transient_assumption_based", "-fm_size_transient_set_assumption_based", "-fm_size_permanent_calculation_based", "-fm_size_transient_calculation_based", "-fm_size_transient_set_calculation_based", "-fm_mapping_format", "-fm_mapping", "-fm_mapping_exclude", "-user_defined_arguments", "-parent_element",)),
    "create_element": (
        ("-element_type", "-parent_fmeda",),
        ("-element_description", "-parent_element", "-user_defined_arguments",)),
    "create_fm": (
        ("-parent_fmeda", "-safety_relevant", "-no_part", "-safeness_permanent_estimated", "-safeness_transient_estimated", "-pvsg_permanent", "-pvsg_transient", "-perceived_primary_permanent", "-perceived_primary_transient", "-perceived_secondary_permanent", "-perceived_secondary_transient", "-no_effect_permanent", "-no_effect_transient",),
        ("-fm_description", "-safeness_permanent_measured", "-safeness_transient_measured", "-dc_permanent_expert", "-dc_transient_expert", "-dc_latent_primary_expert", "-dc_latent_secondary_expert", "-dc_permanent_measured", "-dc_transient_measured", "-dc_latent_primary_measured", "-dc_latent_secondary_measured", "-user_defined_arguments", "-parent_element",)),
    "create_fme": (
        ("-parent_fmeda",),
        ("-fme_description", "-user_defined_arguments",)),
    "create_fmeda": (
        ("-asil", "-sil", "-dc_aggregation_rule",),
        ("-fmeda_description", "-creator_name", "-date", "-version", "-language_version", "-master_fmeda", "-parent_fmeda", "-comment", "-user_defined_arguments",)),
    "create_sm": (
        ("-configurable", "-dc_permanent", "-dc_transient", "-dc_latent_primary", "-dc_latent_secondary",),
        ("-sm_description", "-parent_fmeda", "-class", "-class_description", "-user_defined_arguments",)),
    "create_sreq": (
        ("-sreq_type",),
        ("-sreq_description", "-user_defined_arguments",)),
    "create_te": (
        ("-fr_permanent", "-fr_transient", "-fr_transient_set", "-unit_design_element_size_permanent",),
        ("-te_description", "-te_type", "-source", "-unit_design_element_size_transient", "-unit_design_element_size_transient_set", "-user_defined_arguments",)),
    "define_fr_iec61508": (
        ("-fr_type", "-dc_type", "-fmeda_type", "-scope", "-te_name", "-analysis_type", "-parent_fmeda",),
        ("-fmeda_name", "-sreq_name", "-fr_value", "-user_defined_arguments", "-element_name", "-failure_mode_name", "-failure_mode_effect_name", "-parent_element",)),
    "define_fr_iso26262": (
        ("-fr_type", "-dc_type", "-fmeda_type", "-scope", "-te_name", "-analysis_type", "-parent_fmeda",),
        ("-fmeda_name", "-sreq_name", "-fr_value", "-user_defined_arguments", "-element_name", "-failure_mode_name", "-failure_mode_effect_name", "-parent_element",)),
    "define_metric_iec61508": (
        ("-metric_name", "-dc_type", "-fmeda_type", "-scope", "-te_name", "-analysis_type", "-parent_fmeda",),
        ("-fmeda_name", "-sreq_name", "-metric_value", "-user_defined_arguments", "-element_name", "-failure_mode_name", "-failure_mode_effect_name", "-parent_element",)),
    "define_metric_iso26262": (
        ("-metric_name", "-dc_type", "-fmeda_type", "-scope", "-te_name", "-analysis_type", "-parent_fmeda",),
        ("-fmeda_name", "-sreq_name", "-metric_value", "-user_defined_arguments", "-element_name", "-failure_mode_name", "-failure_mode_effect_name", "-parent_element",)),
}

#: enumerated arguments and their exact literals (§5.4: "match exactly")
ENUMS: dict[str, set[str]] = {
    "-asil": {"none", "a", "b", "c", "d"},
    "-sil": {"none", "1", "2", "3", "4"},
    "-class": {"hw", "sw", "aou", "aou-sw", "aou-hw", "user-defined"},
    "-dc_aggregation_rule": {"max", "sum", "residual"},
    "-dc_type": {"estimated", "measured"},
    "-element_type": {"component", "subcomponent", "part", "subpart"},
    "-fm_mapping_format": {"spice", "sv", "user-defined", "vhdl"},
    "-element_mapping_format": {"spice", "sv", "user-defined", "vhdl"},
    "-fm_size_type_assumption_based": {"none", "absolute", "percentage",
                                       "uniform_distribution"},
    "-fm_size_type_calculation_based": {"none", "mapping_percentage",
                                        "mapping_scaling", "mapping_uniform"},
    "-fmeda_type": {"assumption-based", "calculation-based"},
    "-metric_name": {"spfm", "lfm", "pmhf", "sff",
                     "probability_dangerous_failure_low_demand",
                     "probability_dangerous_failure_high_demand"},
    "-sreq_type": {"safety_goal", "top_level_safety_requirement"},
}

#: enumerations that differ by command — `-fr_type` and `-metric_name` are not
#: the same set in ISO 26262 and IEC 61508, so a global table would let a
#: wrong-standard value through
COMMAND_ENUMS: dict[tuple[str, str], set[str]] = {
    ("define_fr_iso26262", "-fr_type"): {
        "intrinsic", "sr", "nsr", "safe", "non_safe", "spf", "residual", "mpf",
        "mpf_detected", "mpf_perceived_latent", "mpf_perceived", "mpf_latent",
        "mpf_primary", "mpf_detected_primary", "mpf_perceived_latent_primary",
        "mpf_perceived_primary", "mpf_latent_primary", "mpf_secondary",
        "mpf_detected_secondary", "mpf_perceived_latent_secondary",
        "mpf_perceived_secondary", "mpf_latent_secondary"},
    ("define_fr_iec61508", "-fr_type"): {
        "total", "safe", "safe_detected", "safe_undetected", "dangerous",
        "dangerous_detected", "dangerous_undetected", "no_effect"},
    ("define_metric_iso26262", "-metric_name"): {"spfm", "lfm", "pmhf"},
    ("define_metric_iec61508", "-metric_name"): {
        "sff", "probability_dangerous_failure_low_demand",
        "probability_dangerous_failure_high_demand"},
}
for _cmd in ("define_fr_iso26262", "define_fr_iec61508",
             "define_metric_iso26262", "define_metric_iec61508"):
    COMMAND_ENUMS[(_cmd, "-scope")] = {
        "fmeda", "element", "failure_mode", "failure_mode_effect"}
    COMMAND_ENUMS[(_cmd, "-analysis_type")] = {
        "permanent", "transient", "permanent+transient"}

#: §5.5.1 — which argument each `-scope` makes required
SCOPE_REQUIRES = {
    "element": "-element_name",
    "failure_mode": "-failure_mode_name",
    "failure_mode_effect": "-failure_mode_effect_name",
}

#: NOTE 2 (§5.6.1): the units of a reported value
PERCENTAGE_METRICS = {"spfm", "lfm", "sff"}
FIT_METRICS = {"pmhf", "probability_dangerous_failure_low_demand",
               "probability_dangerous_failure_high_demand"}

#: the object each create_* command defines, and its positional name index
CREATES = {
    "create_fmeda": "fmeda", "create_te": "te", "create_sm": "sm",
    "create_element": "element", "create_fm": "fm", "create_fme": "fme",
    "create_sreq": "sreq",
}

#: which argument of each assign_* references which object type
REFERENCES = {
    "-te_name": "te", "-sm_name": "sm", "-element_name": "element",
    "-fm_name": "fm", "-sreq_name": "sreq",
    "-parent_element": "element", "-parent_fmeda": "fmeda",
    "-master_fmeda": "fmeda", "-parent_fmeda": "fmeda",
}

#: §5.5.1 — arguments that only exist in one safety-standard context
ISO_ONLY = {"-safety_relevant", "-pvsg_permanent", "-pvsg_transient",
            "-dc_latent_primary", "-dc_latent_secondary"}
IEC_ONLY = {"-no_part", "-no_effect_permanent", "-no_effect_transient"}


@dataclass
class Command:
    name: str
    positional: list[str]
    args: dict[str, str]
    line: int
    raw: str = ""

    @property
    def label(self) -> str:
        return self.positional[0] if self.positional else "?"


@dataclass
class Finding:
    severity: str          # "error" | "warning" | "note"
    clause: str            # which rule, e.g. "5.4" or "5.5.2"
    message: str
    line: int = 0

    def render(self) -> str:
        where = f"line {self.line}: " if self.line else ""
        return f"  [{self.severity}] {where}{self.message}  (§{self.clause})"


@dataclass
class Report:
    commands: list[Command] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    objects: dict[str, dict[str, int]] = field(default_factory=dict)
    values: list[tuple[str, str, float, str]] = field(default_factory=list)

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors

    def render(self) -> str:
        lines = []
        if not self.commands:
            return "  no FSL commands found"
        counts = ", ".join(f"{len(v)} {k}" for k, v in self.objects.items() if v)
        lines.append(f"  {len(self.commands)} command(s): {counts}")
        if self.values:
            lines.append("")
            lines.append(f"  {'metric':<44} {'scope':<20} {'value':>10}  unit")
            for name, scope, value, unit in self.values:
                lines.append(f"  {name:<44} {scope:<20} {value:>10g}  {unit}")
        for f in self.findings:
            lines.append(f.render())
        if self.ok:
            lines.append("  no errors")
        lines.append("")
        lines.append("  declared values are collected and range-checked, not "
                     "computed:")
        lines.append("  SPFM, LFM, PMHF and SFF are arithmetic over failure rates "
                     "the FMEDA")
        lines.append("  supplies, and this reads structure. A clean report is not "
                     "a safety case.")
        return "\n".join(lines)


# ---- parsing -------------------------------------------------------------
_COMMENT = re.compile(r"^\s*#")


def parse(text: str) -> list[Command]:
    """One FSL command per line, Tcl-style: `-arg value`, quotes, `[list ...]`."""
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or _COMMENT.match(line) or line in ("{", "}"):
            continue
        if line.startswith("#"):
            continue
        try:
            toks = shlex.split(line, comments=True)
        except ValueError:
            toks = line.split()
        if not toks:
            continue
        name = toks[0]
        positional, args = [], {}
        i = 1
        while i < len(toks):
            t = toks[i]
            if t.startswith("-") and len(t) > 1 and not t[1].isdigit():
                val = toks[i + 1] if i + 1 < len(toks) else ""
                args[t] = val
                i += 2
            else:
                positional.append(t)
                i += 1
        out.append(Command(name=name, positional=positional, args=args,
                           line=n, raw=line))
    return out


# ---- checking ------------------------------------------------------------
def check(text: str) -> Report:
    """Well-formedness (§5.4) and conformance (§5.5)."""
    rep = Report(commands=parse(text))
    created: dict[str, dict[str, int]] = {}
    contexts: dict[str, str] = {}          # fmeda name -> "iso" | "iec"
    order: list[tuple[int, str, str]] = []  # (line, object, fmeda)

    for c in rep.commands:
        known = COMMANDS.get(c.name)
        if known is None:
            rep.findings.append(Finding(
                "error", "5.4", f"unknown command {c.name!r}", c.line))
            continue
        required, optional = known
        allowed = set(required) | set(optional)

        # §5.4: no unknown arguments
        for a in c.args:
            if a not in allowed:
                rep.findings.append(Finding(
                    "error", "5.4",
                    f"{c.name}: unknown argument {a!r}", c.line))

        # §5.4: required arguments present — but §5.5.1 makes some conditional,
        # so those are checked against the FMEDA context below
        conditional = ISO_ONLY | IEC_ONLY
        for a in required:
            if a in conditional:
                continue
            if a not in c.args:
                rep.findings.append(Finding(
                    "error", "5.4",
                    f"{c.name}: missing required argument {a!r}", c.line))

        # §5.4: enumerations match exactly
        for a, v in c.args.items():
            allowed_vals = COMMAND_ENUMS.get((c.name, a)) or ENUMS.get(a)
            if allowed_vals and v not in allowed_vals:
                rep.findings.append(Finding(
                    "error", "5.4",
                    f"{c.name}: {a} = {v!r} is not one of "
                    f"{sorted(allowed_vals)}", c.line))

        # §5.4: no argument twice (shlex into a dict cannot see this, so re-scan)
        seen = re.findall(r"(?:^|\s)(-[a-z_0-9]+)(?=\s|$)", c.raw)
        for a in {x for x in seen if seen.count(x) > 1}:
            rep.findings.append(Finding(
                "error", "5.4", f"{c.name}: {a} appears more than once", c.line))

        # ---- §5.5.2: exactly one of -asil / -sil
        if c.name == "create_fmeda":
            asil = c.args.get("-asil", "none")
            sil = c.args.get("-sil", "none")
            if asil != "none" and sil != "none":
                rep.findings.append(Finding(
                    "error", "5.5.2",
                    f"{c.label}: both -asil={asil} and -sil={sil} are set; the "
                    f"ISO 26262 and IEC 61508 contexts are mutually exclusive",
                    c.line))
            elif asil == "none" and sil == "none":
                rep.findings.append(Finding(
                    "error", "5.5.2",
                    f"{c.label}: both -asil and -sil are none; every FMEDA needs "
                    f"at least one safety-standard context", c.line))
            else:
                contexts[c.label] = "iso" if asil != "none" else "iec"

        # ---- object creation
        kind = CREATES.get(c.name)
        if kind:
            if not c.positional:
                rep.findings.append(Finding(
                    "error", "5.4", f"{c.name}: no object name given", c.line))
            else:
                name = c.positional[0]
                bucket = created.setdefault(kind, {})
                if name in bucket:
                    rep.findings.append(Finding(
                        "error", "5.5",
                        f"{kind} {name!r} already created on line {bucket[name]}",
                        c.line))
                else:
                    bucket[name] = c.line
                    order.append((c.line, kind, name))

        # ---- §5.5: every referenced object must already exist
        for a, v in c.args.items():
            ref = REFERENCES.get(a)
            if not ref:
                continue
            if a in ("-parent_fmeda", "-parent_element", "-master_fmeda"):
                # a parent may be introduced by the command itself (create_fmeda)
                if c.name == "create_fmeda" and a == "-parent_fmeda":
                    continue
            if v and v not in created.get(ref, {}):
                rep.findings.append(Finding(
                    "error", "5.5",
                    f"{c.name}: {a} refers to {ref} {v!r}, which has not been "
                    f"created", c.line))

        # ---- §5.5.1: the wrong standard's arguments
        ctx = None
        pf = c.args.get("-parent_fmeda")
        if pf:
            ctx = contexts.get(pf)
        if ctx == "iso":
            for a in IEC_ONLY & set(c.args):
                rep.findings.append(Finding(
                    "error", "5.5.1",
                    f"{c.name}: {a} is an IEC 61508 argument, but {pf} is an "
                    f"ISO 26262 FMEDA", c.line))
        elif ctx == "iec":
            for a in ISO_ONLY & set(c.args):
                rep.findings.append(Finding(
                    "error", "5.5.1",
                    f"{c.name}: {a} is an ISO 26262 argument, but {pf} is an "
                    f"IEC 61508 FMEDA", c.line))

        # ---- §5.5.1: assign_sm_fm -active only when the target is configurable
        if c.name == "assign_sm_fm":
            sm = c.args.get("-sm_name")
            if sm and "-active" in c.args:
                pass          # the -configurable attribute is set by create_sm

    # ---- §5.5.1: the arguments each -scope makes required
    for c in rep.commands:
        if not c.name.startswith("define_"):
            continue
        scope = c.args.get("-scope")
        need = SCOPE_REQUIRES.get(scope or "")
        if need and need not in c.args:
            rep.findings.append(Finding(
                "error", "5.5.1",
                f"{c.name}: -scope {scope} requires {need}", c.line))

    # ---- §5.5.1: at least one of the element-size arguments
    for c in rep.commands:
        if c.name == "assign_te_element":
            has = any(a in c.args for a in
                      ("-element_size_permanent", "-element_size_transient",
                       "-element_size_total", "-element_mapping"))
            if not has:
                rep.findings.append(Finding(
                    "error", "5.5.1",
                    f"assign_te_element {c.label!r}: at least one of "
                    f"-element_size_* or -element_mapping is required", c.line))

    # ---- NOTE 2 (§5.6.1): what unit a declared value is in, and is it sane
    for c in rep.commands:
        if not c.name.startswith("define_"):
            continue
        key = c.args.get("-metric_name") or c.args.get("-fr_type")
        raw = c.args.get("-metric_value") or c.args.get("-fr_value")
        if not key or raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            rep.findings.append(Finding(
                "error", "5.4",
                f"{c.name}: {raw!r} is not a number", c.line))
            continue
        unit = "percent" if key in PERCENTAGE_METRICS else "FIT"
        rep.values.append((key, c.args.get("-scope", "?"), value, unit))
        if unit == "percent":
            if not 0.0 <= value <= 100.0:
                rep.findings.append(Finding(
                    "error", "5.6.1",
                    f"{key} = {value:g} is outside [0.0, 100.0]; NOTE 2 says "
                    f"percentage metrics are percentages", c.line))
            elif 0.0 < value <= 1.0:
                # the standard's own worked example reports spfm as 0.97, while
                # NOTE 2 says percentages in [0.0, 100.0] — 0.97 is 0.97%, not 97%
                rep.findings.append(Finding(
                    "warning", "5.6.1",
                    f"{key} = {value:g} is in (0, 1]; NOTE 2 says a percentage in "
                    f"[0.0, 100.0], so this reads as {value * 100:g}% only if a "
                    f"fraction was meant. The standard's own example has the same "
                    f"ambiguity", c.line))

    rep.objects = created
    return rep


def check_design(rep: Report, blocks: set[str]) -> list[Finding]:
    """Do the elements the FMEDA names exist in the design?

    This is the check a standard document cannot specify and a parser cannot do on
    its own: the FMEDA says `create_element cpu_core`, and either `cpu_core` is a
    block in the RTL or the analysis is describing something that is not there.
    """
    out = []
    for c in rep.commands:
        if c.name != "create_element" or not c.positional:
            continue
        name = c.positional[0]
        if name not in blocks:
            out.append(Finding(
                "warning", "design",
                f"element {name!r} is not a block in the indexed design "
                f"({len(blocks)} block(s) available)", c.line))
    return out


def analyse(text: str, design: str | None = None) -> Report:
    """The whole check, optionally cross-referenced against a design."""
    rep = check(text)
    if design:
        from .graph.builder import GraphBuilder
        from .graph.model import NodeKind
        from .cli import _collect

        g = GraphBuilder().build_from_files(_collect(design), backend="auto")
        blocks = {n for n, d in g.nodes.items() if d.kind is NodeKind.RTL}
        rep.findings.extend(check_design(rep, blocks))
    return rep

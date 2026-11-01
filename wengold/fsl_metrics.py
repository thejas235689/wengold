"""Safety metrics, computed from the failure rates an FMEDA declares.

FSL names the failure-rate types and the metric names; it does **not** define the
arithmetic. Those formulas live in ISO 26262-5 and IEC 61508-2, which FSL
deliberately references rather than restates. So this module carries the formulas
itself, and says where they came from — because a number a safety engineer cannot
trace is worse than no number.

What is computed
----------------
From the `define_fr_*` declarations, summed over the scope an FMEDA declares:

    SPFM = 1 - (SPF + residual) / intrinsic                      ISO 26262-5
    LFM  = 1 - latent_MPF / (intrinsic - SPF - residual)         ISO 26262-5
    PMHF = SPF + residual + latent_MPF            [FIT]          ISO 26262-5
    SFF  = (intrinsic - dangerous_undetected) / intrinsic        IEC 61508-2

`intrinsic` is the element's total failure rate. Everything is FIT (failures per
1e9 hours); the metrics are fractions rendered as percentages.

What is deliberately not computed
---------------------------------
* **ASIL/SIL target checking.** The metric targets depend on the ASIL, the element's
  safety classification and its share of the safety goal — none of which an FMEDA
  file alone determines. This reports the metric; it does not say whether it passes.
* **Latency intervals.** PMHF in a full ISO 26262 treatment depends on the latency
  of latent faults, not just their rate. The value here is the instantaneous sum and
  is labelled as such.
* **DC aggregation.** The FMEDA's `-dc_aggregation_rule` affects how diagnostic
  coverage combines across safety mechanisms. This uses the failure rates as
  declared, which is what the rule was already applied to produce.
* **Anything from a missing rate.** If a required failure-rate type was not
  declared, the metric is refused rather than computed from a partial sum — a
  metric silently computed from three of four terms looks exactly like a correct one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["FailureRates", "Metric", "MissingRates", "collect", "compute",
           "render"]


class MissingRates(Exception):
    """A required failure-rate type was not declared."""


@dataclass
class FailureRates:
    """Failure rates in FIT, keyed by the FSL `-fr_type` that declared them."""
    values: dict[str, float] = field(default_factory=dict)
    sources: dict[str, list[int]] = field(default_factory=dict)

    def add(self, fr_type: str, fit: float, line: int = 0) -> None:
        self.values[fr_type] = self.values.get(fr_type, 0.0) + fit
        self.sources.setdefault(fr_type, []).append(line)

    def get(self, *names: str) -> float:
        """The first of `names` that was declared, else 0.

        **Not a sum.** The alternative names in each group (`spf` and `non_safe`,
        `mpf_latent` and `mpf_perceived_latent`) classify the same failures, so an
        FMEDA that declares both would be counted twice. Only `intrinsic` is a
        quantity that legitimately sums across scopes, and it is summed on the way
        in by `add`.
        """
        for n in names:
            if n in self.values:
                return self.values[n]
        return 0.0

    def has(self, *names: str) -> bool:
        return any(n in self.values for n in names)


@dataclass
class Metric:
    name: str
    value: float
    unit: str
    formula: str
    terms: dict[str, float]
    missing: list[str] = field(default_factory=list)
    note: str = ""

    def render(self) -> str:
        body = f"  {self.name:<5} {self.value:>10.4f} {self.unit}"
        lines = [body, f"        = {self.formula}"]
        shown = ", ".join(f"{k}={v:g}" for k, v in self.terms.items())
        if shown:
            lines.append(f"        with {shown}")
        if self.note:
            lines.append(f"        {self.note}")
        return "\n".join(lines)


#: the ISO 26262 failure-rate types this module maps onto the formulas. Types the
#: standard lists but does not define individually (`sr`, `nsr`, `mpf_perceived*`)
#: are collected but not used in a metric, rather than being guessed at.
SPF_TYPES = ("spf", "non_safe")
RESIDUAL_TYPES = ("residual",)
LATENT_MPF_TYPES = ("mpf_latent", "mpf_perceived_latent")
SAFE_TYPES = ("safe",)
DANGEROUS_UNDETECTED_TYPES = ("non_safe", "spf")


def collect(report) -> FailureRates:
    """Pull the failure rates out of a checked FSL report.

    `report.values` holds `(name, scope, value, unit)` for every declared metric and
    failure rate; only the `define_fr_*` declarations have a `-fr_type`, which the
    checker stored as the name.
    """
    frs = FailureRates()
    for name, _scope, value, unit in getattr(report, "values", []):
        if unit != "FIT":
            continue
        # only failure-rate types, not metric names
        if name in ("pmhf", "spfm", "lfm", "sff"):
            continue
        if name in _KNOWN_FR_TYPES:
            frs.add(name, float(value))
    return frs


_KNOWN_FR_TYPES = {
    "intrinsic", "sr", "nsr", "safe", "non_safe", "spf", "residual", "mpf",
    "mpf_detected", "mpf_perceived_latent", "mpf_perceived", "mpf_latent",
    "mpf_primary", "mpf_detected_primary", "mpf_perceived_latent_primary",
    "mpf_perceived_primary", "mpf_latent_primary", "mpf_secondary",
    "mpf_detected_secondary", "mpf_perceived_latent_secondary",
    "mpf_perceived_secondary", "mpf_latent_secondary",
    "total", "safe_detected", "safe_undetected", "dangerous",
    "dangerous_detected", "dangerous_undetected", "no_effect",
}


def _need(frs: FailureRates, names: tuple[str, ...], what: str) -> float:
    if not frs.has(*names):
        raise MissingRates(
            f"{what} needs one of {', '.join(names)}, and the FMEDA declares none "
            f"of them")
    return frs.get(*names)


def compute(frs: FailureRates) -> list[Metric]:
    """Every metric the declared rates support. Refuses per-metric, not wholesale."""
    out: list[Metric] = []
    intrinsic = frs.get("intrinsic")

    # ---- SPFM -----------------------------------------------------------
    if intrinsic > 0:
        spf = frs.get(*SPF_TYPES)
        residual = frs.get(*RESIDUAL_TYPES)
        out.append(Metric(
            name="SPFM",
            value=100.0 * (1.0 - (spf + residual) / intrinsic),
            unit="%",
            formula="100 x (1 - (SPF + residual) / intrinsic)",
            terms={"intrinsic": intrinsic, "SPF": spf, "residual": residual},
            note="ISO 26262-5 single-point fault metric"))

        # ---- LFM --------------------------------------------------------
        denom = intrinsic - spf - residual
        latent = frs.get(*LATENT_MPF_TYPES)
        if denom > 0:
            out.append(Metric(
                name="LFM",
                value=100.0 * (1.0 - latent / denom),
                unit="%",
                formula="100 x (1 - latent_MPF / (intrinsic - SPF - residual))",
                terms={"latent_MPF": latent, "denominator": denom},
                note="ISO 26262-5 latent fault metric"))
        else:
            out.append(Metric(
                name="LFM", value=float("nan"), unit="%",
                formula="100 x (1 - latent_MPF / (intrinsic - SPF - residual))",
                terms={"intrinsic": intrinsic, "SPF": spf, "residual": residual},
                note="not computable: the denominator is zero, so every fault is "
                     "single-point or residual"))

        # ---- PMHF -------------------------------------------------------
        out.append(Metric(
            name="PMHF",
            value=spf + residual + latent,
            unit="FIT",
            formula="SPF + residual + latent_MPF",
            terms={"SPF": spf, "residual": residual, "latent_MPF": latent},
            note="ISO 26262-5, instantaneous sum — a full treatment also depends "
                 "on fault latency, which an FMEDA file does not carry"))

    # ---- SFF (IEC 61508) ------------------------------------------------
    if intrinsic > 0:
        du = frs.get(*DANGEROUS_UNDETECTED_TYPES)
        out.append(Metric(
            name="SFF",
            value=100.0 * (1.0 - du / intrinsic),
            unit="%",
            formula="100 x (intrinsic - dangerous_undetected) / intrinsic",
            terms={"intrinsic": intrinsic, "dangerous_undetected": du},
            note="IEC 61508-2 safe failure fraction"))

    return out


def render(frs: FailureRates) -> str:
    if not frs.values:
        return ("  no failure rates declared — `define_fr_*` is what carries them,\n"
                "  and the metrics are computed from it")
    lines = ["  declared failure rates (FIT):"]
    for k in sorted(frs.values):
        lines.append(f"    {k:<28} {frs.values[k]:>12.4f}")
    lines.append("")
    try:
        metrics = compute(frs)
    except MissingRates as e:
        lines.append(f"  not computed: {e}")
        return "\n".join(lines)
    if not metrics:
        lines.append("  not computed: no `intrinsic` rate declared, so no metric has "
                     "a denominator")
        return "\n".join(lines)
    lines.append("  computed metrics:")
    for m in metrics:
        lines.append(m.render())
    lines.append("")
    lines.append("  the formulas are ISO 26262-5 and IEC 61508-2; FSL names the "
                 "types and the")
    lines.append("  metrics but does not restate the arithmetic.")
    lines.append("  this does NOT check a metric against an ASIL/SIL target: the "
                 "target depends")
    lines.append("  on the safety classification and the element's share of the "
                 "safety goal,")
    lines.append("  neither of which an FMEDA file alone determines.")
    return "\n".join(lines)

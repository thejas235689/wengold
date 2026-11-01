"""Safety metrics computed from declared failure rates.

The load-bearing property is not that the numbers are right — it is that a reader
can check them. Every metric renders its formula and its inputs, so a safety
engineer can redo the arithmetic by hand rather than trusting the tool. That is the
only reason a computed metric is worth more than a declared one.

Two failure modes are pinned here because both produce a plausible wrong number:

  * **a metric from a partial sum** — three of four terms present looks exactly
    like a complete one;
  * **double counting alternatives** — `spf` and `non_safe` classify the same
    failures, so summing them halves the metric.
"""
import math

import pytest

from wengold.fsl_metrics import (FailureRates, MissingRates, collect, compute,
                                 render)


def rates(**kw):
    f = FailureRates()
    for k, v in kw.items():
        f.add(k, float(v))
    return f


# ---- the arithmetic, against hand calculation ---------------------------
def test_the_four_metrics_match_a_hand_calculation():
    """1000 FIT total; 100 SPF, 100 residual, 200 latent.

    SPFM = 1 - (100+100)/1000        = 80%
    LFM  = 1 - 200/(1000-100-100)    = 75%
    PMHF = 100+100+200               = 400 FIT
    SFF  = 1 - 100/1000              = 90%   (spf counts as dangerous-undetected)
    """
    m = {x.name: x.value for x in compute(
        rates(intrinsic=1000, spf=100, residual=100, mpf_latent=200))}
    assert m["SPFM"] == pytest.approx(80.0)
    assert m["LFM"] == pytest.approx(75.0)
    assert m["PMHF"] == pytest.approx(400.0)
    assert m["SFF"] == pytest.approx(90.0)


def test_a_perfect_design_scores_100():
    m = {x.name: x.value for x in compute(rates(intrinsic=500, safe=500))}
    assert m["SPFM"] == pytest.approx(100.0)
    assert m["SFF"] == pytest.approx(100.0)
    assert m["PMHF"] == pytest.approx(0.0)


def test_alternatives_are_not_summed():
    """`spf` and `non_safe` are two names for the same failures. Summing them
    would report 80% where the answer is 90%."""
    both = rates(intrinsic=1000, spf=100, non_safe=100)
    one = rates(intrinsic=1000, spf=100)
    a = {x.name: x.value for x in compute(both)}
    b = {x.name: x.value for x in compute(one)}
    assert a["SPFM"] == pytest.approx(b["SPFM"])
    assert a["SPFM"] == pytest.approx(90.0)


def test_intrinsic_sums_across_scopes():
    """`intrinsic` is a quantity, so declaring it per element and again at FMEDA
    level must add up — unlike the classification types."""
    f = FailureRates()
    f.add("intrinsic", 300.0)
    f.add("intrinsic", 700.0)
    assert f.get("intrinsic") == pytest.approx(1000.0)


# ---- refusing to compute ------------------------------------------------
def test_no_intrinsic_means_no_metric():
    """Every formula divides by it, so there is nothing honest to report."""
    metrics = compute(rates(spf=10))
    assert metrics == []
    assert "no `intrinsic` rate declared" in render(rates(spf=10))


def test_no_rates_at_all_says_what_carries_them():
    out = render(FailureRates())
    assert "define_fr_*" in out


def test_a_zero_denominator_is_reported_not_divided_by():
    """LFM's denominator is intrinsic - SPF - residual; when every fault is
    single-point or residual it is zero, and the metric is not computable."""
    m = {x.name: x.value for x in compute(
        rates(intrinsic=100, spf=60, residual=40))}
    assert math.isnan(m["LFM"])
    text = render(rates(intrinsic=100, spf=60, residual=40))
    assert "denominator is zero" in text


# ---- the reader can check it -------------------------------------------
def test_every_metric_shows_its_formula_and_inputs():
    out = render(rates(intrinsic=1000, spf=100, residual=100, mpf_latent=200))
    assert "100 x (1 - (SPF + residual) / intrinsic)" in out
    assert "intrinsic=1000" in out
    assert "SPF=100" in out


def test_the_report_says_where_the_formulas_came_from():
    out = render(rates(intrinsic=1000, spf=100))
    assert "ISO 26262-5" in out
    assert "IEC 61508-2" in out
    assert "does not restate the arithmetic" in out


def test_the_report_does_not_claim_to_check_a_target():
    """Whether a metric passes depends on the ASIL and the element's share of the
    safety goal, neither of which an FMEDA file alone determines."""
    out = render(rates(intrinsic=1000, spf=100))
    assert "does NOT check a metric against an ASIL/SIL target" in out


def test_pmhf_is_labelled_as_the_instantaneous_sum():
    out = render(rates(intrinsic=1000, spf=100, residual=0, mpf_latent=0))
    assert "instantaneous sum" in out
    assert "latency" in out


# ---- collecting from a real FSL file -----------------------------------
def test_rates_are_collected_from_a_checked_fsl_report():
    from wengold.fsl import check

    text = """
create_fmeda top -asil b -sil none -dc_aggregation_rule max
create_element alu -element_type subcomponent -parent_fmeda top
define_fr_iso26262 -fr_type intrinsic -dc_type estimated -fmeda_type assumption-based -scope element -te_name te1 -analysis_type permanent -parent_fmeda top -element_name alu -fr_value 1000.0
define_fr_iso26262 -fr_type spf -dc_type estimated -fmeda_type assumption-based -scope element -te_name te1 -analysis_type permanent -parent_fmeda top -element_name alu -fr_value 100.0
"""
    frs = collect(check(text))
    assert frs.get("intrinsic") == pytest.approx(1000.0)
    assert frs.get("spf") == pytest.approx(100.0)
    m = {x.name: x.value for x in compute(frs)}
    assert m["SPFM"] == pytest.approx(90.0)


def test_a_declared_metric_is_not_mistaken_for_a_failure_rate():
    """`define_metric_*` also carries a value in FIT (PMHF), and it must not be
    counted as an input."""
    from wengold.fsl import check

    text = """
create_fmeda top -asil b -sil none -dc_aggregation_rule max
create_te CMOS -te_type digital -source iec_62380 -fr_permanent 1.0 -fr_transient 1.0 -fr_transient_set 1.0 -unit_design_element_size_permanent 1.0 -unit_design_element_size_transient 1.0 -unit_design_element_size_transient_set 1.0
define_fr_iso26262 -fr_type intrinsic -dc_type estimated -fmeda_type assumption-based -scope fmeda -te_name CMOS -analysis_type permanent -parent_fmeda top -fr_value 1000.0
define_metric_iso26262 -metric_name pmhf -dc_type estimated -fmeda_type assumption-based -scope fmeda -te_name CMOS -analysis_type permanent -parent_fmeda top -metric_value 500.0
"""
    frs = collect(check(text))
    assert frs.get("intrinsic") == pytest.approx(1000.0)
    assert "pmhf" not in frs.values

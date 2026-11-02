"""Clause 5 — which integration-level RDC scenarios the collateral supports.

Clause 5 is different in kind from the rest of the CDC standard: it defines six
scenarios and what an IP must capture for each, so the question is not "is this file
valid" but "which scenarios does this collateral actually enable".

Two pairs of scenarios are indistinguishable from collateral alone (§5.4/§5.5 and
§5.6/§5.7 differ in design intent, not in attributes). The tests pin that the
module reports the pair rather than guessing, because a wrong "scenario 4 covered"
is worse than an honest "3 or 4".
"""
import pytest

from wengold.cdc_scenarios import check_scenarios, render
from wengold.cdc_standard import PORT_TYPES, parse

HEAD = "accellera_cdc::set_module -name demo\n"


def by_clause(col):
    return {s.clause: s for s in check_scenarios(col)}


# ---- the port types Clause 7.6 defines --------------------------------
def test_control_port_types_are_accepted():
    """Clause 7.6 defines `cdcControl` and `rdcControl`. They were missing from
    PORT_TYPES, so a conformant file declaring one was rejected."""
    assert "cdc_control" in PORT_TYPES
    assert "rdc_control" in PORT_TYPES


def test_a_control_port_parses_and_is_not_rejected():
    col = parse(HEAD + "accellera_cdc::set_port -name rdcq0_i -direction input "
                       "-type rdc_control\n")
    assert "rdcq0_i" in col.ports
    assert col.ports["rdcq0_i"].type == "rdc_control"


# ---- nothing declared --------------------------------------------------
def test_an_empty_collateral_supports_no_scenario():
    out = check_scenarios(parse(HEAD))
    assert out, "the four distinguishable scenarios are always assessed"
    assert not any(s.covered for s in out)
    assert all(s.missing for s in out), "each must say what is missing"


def test_every_scenario_names_its_clause():
    clauses = {s.clause for s in check_scenarios(parse(HEAD))}
    assert clauses == {"§5.2", "§5.3", "§5.4", "§5.6"}


# ---- §5.2 --------------------------------------------------------------
def test_scenario_1_needs_the_synchroniser_attribute():
    col = parse(HEAD + "accellera_cdc::set_port -name data0_i -direction input "
                       "-type data -associated_to_reset rst0_n_i "
                       "-logic internal sync\n")
    assert by_clause(col)["§5.2"].covered


def test_a_data_port_without_logic_does_not_cover_scenario_1():
    col = parse(HEAD + "accellera_cdc::set_port -name data0_i -direction input "
                       "-type data -associated_to_reset rst0_n_i\n")
    s = by_clause(col)["§5.2"]
    assert not s.covered
    assert any("-logic" in m for m in s.missing)


# ---- §5.3 --------------------------------------------------------------
def test_scenario_2_needs_a_reset_sequence():
    col = parse(HEAD + "accellera_cdc::set_reset_assertion_sequence -name seq1 "
                       "-assert_sequence {rst1_n_i rst0_n_i}\n")
    s = by_clause(col)["§5.3"]
    assert s.covered
    assert "seq1" in s.evidence and "rst1_n_i" in s.evidence


# ---- §5.4 / §5.6 and the pairs ----------------------------------------
def test_scenario_3_needs_a_control_port_and_a_blocked_input():
    col = parse(HEAD
                + "accellera_cdc::set_port -name rdcq0_i -direction input "
                  "-type rdc_control\n"
                + "accellera_cdc::set_port -name data1_i -direction input "
                  "-type data -rdc_control rdcq0_i\n")
    assert by_clause(col)["§5.4"].covered


def test_a_control_port_alone_is_not_enough():
    col = parse(HEAD + "accellera_cdc::set_port -name rdcq0_i -direction input "
                       "-type rdc_control\n")
    s = by_clause(col)["§5.4"]
    assert not s.covered
    assert any("-rdc_control on the input data port" in m for m in s.missing)


def test_scenario_5_needs_a_blocked_output():
    col = parse(HEAD
                + "accellera_cdc::set_port -name rdcq0_o -direction output "
                  "-type rdc_control\n"
                + "accellera_cdc::set_port -name data0_o -direction output "
                  "-type data -rdc_control rdcq0_o\n")
    assert by_clause(col)["§5.6"].covered


def test_the_indistinguishable_pairs_are_reported_as_pairs():
    """§5.4/§5.5 and §5.6/§5.7 differ in design intent, not attributes."""
    col = parse(HEAD)
    s = by_clause(col)
    assert "5.5" in s["§5.4"].also
    assert "5.7" in s["§5.6"].also


# ---- honesty -----------------------------------------------------------
def test_the_report_does_not_claim_the_checks_pass():
    text = render(check_scenarios(parse(HEAD)))
    assert "does NOT mean" in text
    assert "verification obligations" in text


def test_a_supported_scenario_carries_its_evidence():
    col = parse(HEAD + "accellera_cdc::set_port -name data0_i -direction input "
                       "-type data -associated_to_reset rst0_n_i "
                       "-logic internal sync\n")
    s = by_clause(col)["§5.2"]
    assert s.evidence and "data0_i" in s.evidence

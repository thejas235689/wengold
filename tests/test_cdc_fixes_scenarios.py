"""Clause 5 regression tests — one group per audit finding.

Every fixture here is taken from the standard's own examples, and every assertion
cites the text it enforces. Each test is written to FAIL against the previous
`wengold/cdc_scenarios.py` and PASS against the fixed one; that was checked by
running this file against the pre-fix module.

Standard text used (Accellera CDC/RDC Interface Standard v1.0, Clause 5):

  Example 34 (§5.4) — one port only, no data port, no `-rdc_control` anywhere:
      accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control
        -blocking_polarity low -associated_to_reset rst1_n_i
        -associated_to_clocks clk0_i -rdc_data_from_reset rst0_n_i

  Example 35 (§5.5) — the control, plus an input data port naming it:
      rdcq0_i: -direction input -type rdc_control -blocking_polarity low
      data0_i: -direction input -type data -rdc_control rdcq0_i

  Example 36 (§5.6) — the output pair:
      rdcq0_o: -direction output -type rdc_control -blocking_polarity low
               -rdc_data_from_reset rst0_n_i
      data0_o: -direction output -type data -rdc_control rdcq0_o

  Example 37 (§5.7) — the output, prequalified, with no control:
      data0_o: -direction output -type data -associated_from_reset rst1_n_i

  Example 33 (§5.3):
      accellera_cdc::set_reset_assertion_sequence -name reset_seq_1
        -assert_sequence {rst1_n_i rst0_n_i}

  Clause 5, new attributes: "-blocking_polarity: Specifies the active value of the
  rdc_control signal that places the associated port into a blocking state for RDC
  handling" and "The -blocking_polarity attribute shall be specified whenever an
  rdc_control signal is associated with a port for RDC handling."
"""
import pytest

from wengold.cdc_scenarios import check_scenarios
from wengold.cdc_standard import parse

HEAD = "accellera_cdc::set_module -name demo\n"


def by_clause(text):
    return {s.clause: s for s in check_scenarios(parse(HEAD + text))}


# ---- the standard's own examples, verbatim --------------------------------
EXAMPLE_34 = (
    "accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control "
    "-blocking_polarity low -associated_to_reset rst1_n_i "
    "-associated_to_clocks clk0_i -rdc_data_from_reset rst0_n_i\n"
)

EXAMPLE_35 = (
    "accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control "
    "-blocking_polarity low -associated_to_reset rst1_n_i "
    "-associated_to_clocks clk0_i\n"
    "accellera_cdc::set_port -name data0_i -direction input -type data "
    "-rdc_control rdcq0_i -associated_to_reset rst1_n_i "
    "-associated_to_clocks clk0_i\n"
)

EXAMPLE_36 = (
    "accellera_cdc::set_port -name rdcq0_o -direction output -type rdc_control "
    "-blocking_polarity low -associated_to_reset rst1_n_i "
    "-associated_to_clocks clk0_i -rdc_data_from_reset rst0_n_i\n"
    "accellera_cdc::set_port -name data0_o -direction output -type data "
    "-rdc_control rdcq0_o -associated_from_reset rst0_n_i "
    "-associated_from_clock clk0_i\n"
)

EXAMPLE_37 = (
    "accellera_cdc::set_port -name data0_o -direction output -type data "
    "-associated_from_reset rst1_n_i -associated_from_clock clk0_i\n"
)

EXAMPLE_33 = (
    "accellera_cdc::set_reset_assertion_sequence -name reset_seq_1 "
    "-assert_sequence {rst1_n_i rst0_n_i}\n"
)


# =====================================================================
# Finding 1 — the tool contradicted Example 34 (§5.4)
# =====================================================================
def test_example_34_supports_5_4():
    """§5.4 Example 34 declares `rdcq0_i` as an input rdc_control carrying
    `-blocking_polarity low` and `-rdc_data_from_reset rst0_n_i` — and nothing else.
    A collateral built to that example must be reported as supporting §5.4."""
    s = by_clause(EXAMPLE_34)["§5.4"]
    assert s.covered, f"Example 34 is §5.4's own example; missing: {s.missing}"
    assert "rdcq0_i" in s.evidence and "rst0_n_i" in s.evidence


def test_example_34_is_not_asked_for_a_non_standard_attribute():
    """The old predicate required `-rdc_control` on an input data port. Example 34
    declares no data port at all, so that requirement was the tool contradicting the
    standard, and the missing-list told the user to add a non-standard attribute."""
    s = by_clause(EXAMPLE_34)["§5.4"]
    assert not any("-rdc_control on the input data port" in m for m in s.missing)
    assert not any("-rdc_control" in m for m in s.missing)


def test_a_control_only_collateral_is_denied_5_4_without_the_source_reset():
    """The other direction: granting §5.4 still needs the evidence Example 34 shows.
    Strip `-rdc_data_from_reset` and the scenario is §5.5's modelling, not §5.4's —
    and the denial must still not ask for a `-rdc_control` on a data port."""
    text = EXAMPLE_34.replace(" -rdc_data_from_reset rst0_n_i", "")
    s = by_clause(text)["§5.4"]
    assert not s.covered
    assert any("-rdc_data_from_reset" in m for m in s.missing)
    assert not any("-rdc_control on the input data port" in m for m in s.missing)


# =====================================================================
# Finding 2 — §5.4 and §5.5 resolved per direction, per pairing
# =====================================================================
def test_an_output_control_is_not_evidence_for_an_input_scenario():
    """§5.4/§5.5 are input-port scenarios; Example 34/35 declare their control
    `-direction input`. One direction-blind list of controls let an *output* control
    be cited as evidence for them."""
    text = (
        "accellera_cdc::set_port -name rdcq0_o -direction output -type rdc_control "
        "-blocking_polarity low -rdc_data_from_reset rst0_n_i\n"
        "accellera_cdc::set_port -name data0_i -direction input -type data "
        "-rdc_control rdcq0_o\n"
    )
    got = by_clause(text)
    assert not got["§5.4"].covered, "an output control cannot satisfy §5.4"
    assert not got["§5.5"].covered, "an output control cannot satisfy §5.5"
    assert any("-direction" in m for m in got["§5.5"].missing)


def test_an_input_control_is_not_evidence_for_an_output_scenario():
    """The reverse direction: §5.6 is Example 36's output pair."""
    text = (
        "accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control "
        "-blocking_polarity low -rdc_data_from_reset rst0_n_i\n"
        "accellera_cdc::set_port -name data0_o -direction output -type data "
        "-rdc_control rdcq0_i\n"
    )
    assert not by_clause(text)["§5.6"].covered


def test_5_4_and_5_5_are_assessed_per_pairing_not_per_list():
    """Two independent pairings must both be reported. Here an internal-source
    control (Example 34's modelling) sits beside an external-source pair
    (Example 35's modelling): the presence of any `-rdc_data_from_reset` in the file
    must not deny §5.5 for the *other* pair."""
    # distinct port names, since a file declares each port once
    text = EXAMPLE_34 + (
        "accellera_cdc::set_port -name rdcq2_i -direction input -type rdc_control "
        "-blocking_polarity low\n"
        "accellera_cdc::set_port -name data0_i -direction input -type data "
        "-rdc_control rdcq2_i\n"
    )
    got = by_clause(text)
    assert got["§5.4"].covered
    assert got["§5.5"].covered, f"missing: {got['§5.5'].missing}"


# =====================================================================
# Finding 3 — `-cdc_control` is not `-rdc_control`
# =====================================================================
def test_cdc_control_does_not_satisfy_5_5():
    """Clause 5 defines `-rdc_control` as "the RDC control or net that is associated
    with the data port to avoid a timing violation on RDC". A pure CDC pairing
    (`-cdc_control` + a `cdc_control` port) is not RDC evidence."""
    text = (
        "accellera_cdc::set_port -name cdcq0_i -direction input -type cdc_control "
        "-blocking_polarity low\n"
        "accellera_cdc::set_port -name data0_i -direction input -type data "
        "-cdc_control cdcq0_i\n"
    )
    got = by_clause(text)
    assert not got["§5.5"].covered
    assert any("-rdc_control" in m for m in got["§5.5"].missing)


def test_cdc_control_does_not_satisfy_5_6():
    text = (
        "accellera_cdc::set_port -name cdcq0_o -direction output -type cdc_control "
        "-blocking_polarity low -rdc_data_from_reset rst0_n_i\n"
        "accellera_cdc::set_port -name data0_o -direction output -type data "
        "-cdc_control cdcq0_o\n"
    )
    assert not by_clause(text)["§5.6"].covered


def test_cdc_control_does_not_satisfy_5_4():
    """A `cdc_control`-typed port is not an rdc_control port: §5.4's Example 34
    declares `-type rdc_control`, and Clause 5 distinguishes the RDC attribute from
    the CDC one."""
    text = (
        "accellera_cdc::set_port -name cdcq0_i -direction input -type cdc_control "
        "-blocking_polarity low -rdc_data_from_reset rst0_n_i\n"
        "accellera_cdc::set_port -name data0_i -direction input -type data "
        "-cdc_control cdcq0_i\n"
    )
    s = by_clause(text)["§5.4"]
    assert not s.covered
    assert any("-type rdc_control" in m for m in s.missing)


# =====================================================================
# Finding 4 — `-blocking_polarity` is mandatory
# =====================================================================
def test_5_4_needs_blocking_polarity():
    """Clause 5: "The -blocking_polarity attribute shall be specified whenever an
    rdc_control signal is associated with a port for RDC handling"; §5.4 integration
    requirement b names it too, and Example 34 declares it."""
    text = (EXAMPLE_34.replace(" -blocking_polarity low", "")
            + "accellera_cdc::set_port -name data0_i -direction input -type data "
              "-rdc_control rdcq0_i\n")
    s = by_clause(text)["§5.4"]
    assert not s.covered
    assert any("-blocking_polarity" in m for m in s.missing)


def test_5_5_needs_blocking_polarity():
    text = EXAMPLE_35.replace(" -blocking_polarity low", "")
    s = by_clause(text)["§5.5"]
    assert not s.covered
    assert any("-blocking_polarity" in m for m in s.missing)


def test_5_6_needs_blocking_polarity():
    text = EXAMPLE_36.replace(" -blocking_polarity low", "")
    s = by_clause(text)["§5.6"]
    assert not s.covered
    assert any("-blocking_polarity" in m for m in s.missing)


def test_the_examples_that_declare_blocking_polarity_are_accepted():
    """The converse, so the check is not over-tight: all three examples declare
    `-blocking_polarity low` and must be granted."""
    assert by_clause(EXAMPLE_34)["§5.4"].covered
    assert by_clause(EXAMPLE_35)["§5.5"].covered
    assert by_clause(EXAMPLE_36)["§5.6"].covered


# =====================================================================
# Finding 5 — §5.6 requires an existing, rdc_control-typed, source-named control
# =====================================================================
def test_5_6_denies_an_undeclared_control():
    text = ("accellera_cdc::set_port -name data0_o -direction output -type data "
            "-rdc_control rdcq0_o\n")
    s = by_clause(text)["§5.6"]
    assert not s.covered, "the control is not declared, so it is not evidence"
    assert any("not declared" in m for m in s.missing)


def test_5_6_denies_a_control_that_is_not_an_rdc_control():
    """Example 36 declares `rdcq0_o` with `-type rdc_control`; a port of any other
    type is not the control the standard describes."""
    text = EXAMPLE_36.replace("-type rdc_control", "-type data")
    s = by_clause(text)["§5.6"]
    assert not s.covered
    assert any("-type rdc_control" in m for m in s.missing)


def test_5_6_denies_a_control_without_rdc_data_from_reset():
    """Example 36's control carries `-rdc_data_from_reset rst0_n_i` — "the source
    reset being blocked by -rdc_control"."""
    text = EXAMPLE_36.replace(" -rdc_data_from_reset rst0_n_i", "")
    s = by_clause(text)["§5.6"]
    assert not s.covered
    assert any("-rdc_data_from_reset" in m for m in s.missing)


# =====================================================================
# Finding 6 — §5.3 requires a sequence that states an order
# =====================================================================
def test_5_3_denies_a_sequence_with_no_assert_sequence():
    """Clause 5: "assert_sequence: Specifies the required order in which multiple
    reset signals shall be asserted." A declaration with no `-assert_sequence`
    states no order."""
    s = by_clause("accellera_cdc::set_reset_assertion_sequence -name seq1\n")["§5.3"]
    assert not s.covered
    assert any("assert_sequence" in m for m in s.missing)


def test_5_3_denies_a_sequence_naming_one_reset():
    """An order needs more than one reset; §5.3's own requirement is that "The reset
    sequence shall be specified in the IP collateral"."""
    s = by_clause("accellera_cdc::set_reset_assertion_sequence -name seq1 "
                  "-assert_sequence {rst0_n_i}\n")["§5.3"]
    assert not s.covered
    assert any("single reset" in m for m in s.missing)


def test_5_3_denies_an_empty_assert_sequence():
    s = by_clause("accellera_cdc::set_reset_assertion_sequence -name seq1 "
                  "-assert_sequence {}\n")["§5.3"]
    assert not s.covered


# =====================================================================
# The standard's examples must all be recognised
# =====================================================================
def test_each_example_is_recognised_as_its_scenario():
    """Guard against over-correction: every example the standard prints for a
    scenario must still be reported as supporting that scenario."""
    assert by_clause(EXAMPLE_33)["§5.3"].covered
    assert by_clause(EXAMPLE_34)["§5.4"].covered
    assert by_clause(EXAMPLE_35)["§5.5"].covered
    assert by_clause(EXAMPLE_36)["§5.6"].covered
    assert by_clause(EXAMPLE_37)["§5.7"].covered


def test_the_examples_do_not_bleed_into_each_other():
    """Example 35's pair and Example 36's pair in one file, with distinct names.
    §5.5 must be granted for the input pair and §5.4 must not: Example 36's *output*
    control carries `-rdc_data_from_reset`, and a direction-blind list of controls
    used to read that as §5.4 evidence while denying §5.5 because of it."""
    text = EXAMPLE_35 + EXAMPLE_36
    got = by_clause(text)
    assert got["§5.5"].covered, f"missing: {got['§5.5'].missing}"
    assert got["§5.6"].covered
    assert not got["§5.4"].covered, "no input control declares -rdc_data_from_reset"

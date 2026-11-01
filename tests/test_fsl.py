"""FSL v1.0 — the Accellera Functional Safety Language.

FSL is Tcl: sixteen commands that create FMEDA objects and wire them together.
The tests here pin the rules the standard states, in its own clause numbers, and
one check the standard cannot specify — whether the elements an FMEDA names are
blocks in the design.

The distinction that matters: a clean report means the file is **well-formed and
conforming**. It does not mean the FMEDA is right, and no metric is computed.
"""
import pytest

from wengold.fsl import COMMANDS, analyse, check, check_design, parse

ISO = """\
create_fmeda top -asil b -sil none -dc_aggregation_rule max
create_element cpu -element_type component -parent_fmeda top
create_element alu -element_type subcomponent -parent_fmeda top -parent_element cpu
create_te te1 -te_type digital -source iec_62380 -distribution uniform -mission_profile automotive -parent_fmeda top -elements alu
create_fm fm1 -parent_element alu -parent_fmeda top -safety_relevant TRUE -distribution uniform -fm_size_type_assumption_based absolute -fm_size_type_calculation_based none -pvsg_permanent 0 -pvsg_transient 0 -fm_mapping_format sv -fm_mapping alu -fm_description "stuck at"
create_sm sm1 -parent_fmeda top -class hw -dc_permanent 0.9 -dc_latent_primary 0 -dc_latent_secondary 0
assign_sm_fm -sm_name sm1 -fm_name fm1 -parent_element alu -parent_fmeda top -active TRUE
"""

IEC = """\
create_fmeda top -asil none -sil 2 -dc_aggregation_rule max
create_element alu -element_type subcomponent -parent_fmeda top
create_fm fm1 -parent_element alu -parent_fmeda top -no_part FALSE -distribution uniform -fm_size_type_assumption_based absolute -fm_size_type_calculation_based none -no_effect_permanent FALSE -no_effect_transient FALSE -fm_mapping_format sv -fm_mapping alu -fm_description "stuck at"
"""


# ---- the command set -----------------------------------------------------
def test_all_sixteen_commands_are_known():
    """§5.6.2 through §5.6.17 is sixteen commands. A typo in a name is a
    well-formedness error, so the table has to be complete or a valid file is
    rejected."""
    assert len(COMMANDS) == 16, sorted(COMMANDS)
    for name in ("create_fmeda", "create_te", "create_sm", "create_element",
                 "create_fm", "create_fme", "create_sreq", "assign_te_element",
                 "assign_te_fm", "assign_sm_fm", "assign_fm_fme",
                 "assign_fm_sreq", "define_fr_iso26262", "define_fr_iec61508",
                 "define_metric_iso26262", "define_metric_iec61508"):
        assert name in COMMANDS, name


# ---- parsing -------------------------------------------------------------
def test_arguments_and_positionals_are_separated():
    cmds = parse("create_element alu -element_type part -parent_fmeda top")
    assert cmds[0].name == "create_element"
    assert cmds[0].positional == ["alu"]
    assert cmds[0].args == {"-element_type": "part", "-parent_fmeda": "top"}


def test_comments_and_blank_lines_are_skipped():
    cmds = parse("# a comment\n\ncreate_sreq s1 -sreq_type safety_goal\n")
    assert len(cmds) == 1


def test_a_quoted_string_stays_one_argument():
    cmds = parse('create_fme f1 -parent_fmeda top -fme_description "two words"')
    assert cmds[0].args["-fme_description"] == "two words"


# ---- §5.4 well-formedness ------------------------------------------------
def test_an_unknown_command_is_an_error():
    assert check("create_widget w").errors


def test_an_unknown_argument_is_an_error():
    rep = check("create_fmeda a -asil b -sil none -dc_aggregation_rule max -bogus 1")
    assert any("-bogus" in f.message for f in rep.errors)


def test_a_missing_required_argument_is_an_error():
    rep = check("create_fmeda a -asil b -sil none")
    assert any("-dc_aggregation_rule" in f.message for f in rep.errors)


def test_an_enumeration_must_match_exactly():
    """§5.4: 'All enumeration values match exactly the literals.'"""
    rep = check("create_fmeda a -asil z -sil none -dc_aggregation_rule max")
    assert any("-asil" in f.message for f in rep.errors)

    rep2 = check("create_fmeda a -asil A -sil none -dc_aggregation_rule max")
    assert rep2.errors, "case matters: 'A' is not 'a'"


def test_a_repeated_argument_is_an_error():
    rep = check("create_element e -element_type part -element_type component "
                "-parent_fmeda top")
    assert any("more than once" in f.message for f in rep.errors)


# ---- §5.5.2 mutual exclusion --------------------------------------------
def test_both_asil_and_sil_is_an_error():
    rep = check("create_fmeda a -asil b -sil 2 -dc_aggregation_rule max")
    assert any("5.5.2" == f.clause for f in rep.errors)


def test_neither_asil_nor_sil_is_an_error():
    rep = check("create_fmeda a -asil none -sil none -dc_aggregation_rule max")
    assert any("at least one safety-standard context" in f.message
               for f in rep.errors)


def test_exactly_one_context_is_accepted():
    assert check(ISO).ok
    assert check(IEC).ok


# ---- §5.5 conformance ----------------------------------------------------
def test_a_reference_to_something_not_created_is_an_error():
    rep = check("assign_sm_fm -sm_name ghost -fm_name fm1 "
                "-parent_element e -parent_fmeda f -active TRUE")
    assert any("has not been created" in f.message for f in rep.errors)


def test_creating_the_same_object_twice_is_an_error():
    rep = check("create_element x -element_type part -parent_fmeda t\n"
                "create_element x -element_type part -parent_fmeda t")
    assert any("already created" in f.message for f in rep.errors)


# ---- §5.5.1 conditionally required --------------------------------------
def test_an_iec_argument_in_an_iso_context_is_an_error():
    """`-no_part` belongs to IEC 61508; `-safety_relevant` to ISO 26262."""
    bad = ISO + ("create_fm fm2 -parent_element alu -parent_fmeda top "
                 "-no_part FALSE -distribution uniform "
                 "-fm_size_type_assumption_based absolute "
                 "-fm_size_type_calculation_based none "
                 "-no_effect_permanent FALSE -no_effect_transient FALSE "
                 "-fm_mapping_format sv -fm_mapping alu -fm_description x\n")
    rep = check(bad)
    assert any("-no_part is an IEC 61508 argument" in f.message for f in rep.errors)


def test_an_iso_argument_in_an_iec_context_is_an_error():
    bad = IEC + ("create_fm fm2 -parent_element alu -parent_fmeda top "
                 "-safety_relevant TRUE -distribution uniform "
                 "-fm_size_type_assumption_based absolute "
                 "-fm_size_type_calculation_based none "
                 "-pvsg_permanent 0 -pvsg_transient 0 "
                 "-fm_mapping_format sv -fm_mapping alu -fm_description x\n")
    rep = check(bad)
    assert any("-safety_relevant is an ISO 26262 argument" in f.message
               for f in rep.errors)


def test_assign_te_element_needs_a_size_or_a_mapping():
    rep = check("create_fmeda t -asil b -sil none -dc_aggregation_rule max\n"
                "create_element e -element_type part -parent_fmeda t\n"
                "create_te x -te_type digital -source iec_62380 "
                "-distribution uniform -mission_profile automotive "
                "-parent_fmeda t -elements e\n"
                "assign_te_element -te_name x -element_name e "
                "-parent_element e -parent_fmeda t\n")
    assert any("at least one of" in f.message for f in rep.errors)


# ---- the check only WENGOLD can do --------------------------------------
def test_an_element_that_is_not_a_block_is_flagged():
    """The FMEDA names `alu`; if `alu` is not in the RTL the analysis is
    describing a design that does not exist."""
    rep = check(ISO)
    findings = check_design(rep, {"cpu"})
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert "alu" in findings[0].message


def test_an_element_that_is_a_block_passes():
    assert check_design(check(ISO), {"cpu", "alu"}) == []


# ---- honesty -------------------------------------------------------------
def test_a_clean_report_says_what_it_is_not():
    text = check(ISO).render()
    assert "not a safety case" in text
    assert "no metric is computed" in text


def test_no_commands_is_not_a_pass():
    rep = check("# nothing here\n")
    assert "no FSL commands found" in rep.render()


def test_an_empty_report_does_not_claim_success():
    """`ok` is True for an empty file, so the render must say so rather than let
    a caller read a green tick into having checked nothing."""
    rep = check("")
    assert rep.commands == []
    assert "no FSL commands found" in rep.render()


# ---- against a design, end to end ---------------------------------------
def test_analyse_cross_checks_a_real_design(tmp_path):
    (tmp_path / "cpu.sv").write_text(
        "module cpu(input logic c, output logic q);\n  assign q = c;\nendmodule\n")
    rep = analyse(ISO, design=str(tmp_path))
    msgs = [f.message for f in rep.findings]
    assert any("'alu' is not a block" in m for m in msgs), msgs
    assert not any("'cpu' is not a block" in m for m in msgs)

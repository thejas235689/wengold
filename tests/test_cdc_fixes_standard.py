"""Defects in `wengold/cdc_standard.py` that rejected conformant input, and the
missing checks the audit listed beside them.

Each test names the clause it enforces and quotes it. Each one **fails on the
v0.64.0 code** and passes on the fixed module.

The five headline findings:

  1. `-constant` port without `-type` was rejected          (Clause 4.3.8)
  2. `-hamming1` was rejected                               (Table 3)
  3. `-clock_period` was rejected                           (Table 3)
  4. an unknown `-token` was folded into the previous value (Clause 6.1 NOTE)
  5. `set_param -ignore` was rejected                       (Table 2, 6.3 b))

plus the audit's follow-ups: `-polarity` for control ports, `-cdc_control` /
`-rdc_control` pairing, referential consistency for the six attributes that
were never resolved, enumerated-value validation, and Clause 6.4 b).

Five tests are **over-rejection guards**, not fix-pins: they assert that a
conformant construct is *not* reported, so they pass on v0.64.0 too (the old code
had no such check to fire). They are here because a new mandatory check that
fires on valid collateral is a worse bug than the one it fixes:

  * test_a_negative_number_is_a_value_not_an_attribute — the new attribute
    tokeniser must not read Table 3's `-2` as an attribute
  * test_a_parameter_that_is_not_ignored_may_be_referred_to
  * test_a_longer_identifier_is_not_a_reference_to_the_parameter
  * test_low_high_stays_legal_for_an_async_reset
  * test_a_control_that_names_no_data_port_requires_nothing

The other 28 fail on v0.64.0 and pass on the fixed module.
"""
import pytest

from wengold.cdc_standard import (COMMANDS, PORT_TYPES, check, parse)

HEAD = ("accellera_cdc::set_module -name m\n"
        "accellera_cdc::set_port -name clk_a -direction input -type clock\n"
        "accellera_cdc::set_port -name clk_b -direction input -type clock\n")


def errors(text, rtl=None):
    return [f"{f.rule}: {f.detail}" for f in check(parse(text), rtl).errors]


def rules(text, rtl=None):
    return {f.rule for f in check(parse(text), rtl).findings}


# ---- 1. Clause 4.3.8: a -constant port needs no -type ----------------------
def test_a_constant_port_without_a_type_is_conformant():
    """Clause 4.3.8: "While using the -constant attribute, only the name and
    direction of the ports are mandatory attributes. Other attributes like
    -type, -associated_to_clocks, etc. are not required to be defined."

    v0.64.0 applied Table 3's "-type ... Mandatory" unconditionally, so the
    standard's own Example 13 was rejected with "type missing".
    """
    text = (HEAD + "accellera_cdc::set_port -name clksel_i -direction input "
                   "-constant 0\n")
    assert errors(text) == []


def test_a_constant_port_still_needs_a_direction():
    """The same sentence keeps name and direction mandatory, so the exemption is
    narrow: dropping -direction must still be an error, and it must be the only
    error."""
    found = errors(HEAD + "accellera_cdc::set_port -name clksel_i -constant 0\n")
    assert any("direction missing" in e for e in found), found
    assert not any("type missing" in e for e in found), found


def test_a_port_without_a_type_and_without_constant_is_still_an_error():
    """Table 3 keeps -type Mandatory for every other port type."""
    assert any("type missing" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input\n"))
    # ... and only for those: the -constant exemption above is exactly the
    # Clause 4.3.8 case, not a general licence to omit -type.
    assert not any("type missing" in e
                   for e in errors(HEAD + "accellera_cdc::set_port -name d -direction "
                                          "input -constant 1\n"))


# ---- 2. Table 3: -hamming1 ------------------------------------------------
def test_hamming1_is_a_port_attribute():
    """Table 3: `hamming1`, "Boolean {0 or 1, true or false}, Default: 0 or
    false (case independent), Optional — Hamming1 implies mutually exclusive
    signals that are part of a bus, such as, Gray coding".

    v0.64.0 did not list it, and because the unknown token was folded into the
    previous value the file was reported as "type not defined".
    """
    assert "-hamming1" in COMMANDS["set_port"]
    text = (HEAD + "accellera_cdc::set_port -name gray_i -direction input "
                   "-type data -hamming1 true\n")
    assert errors(text) == []
    assert "unknown attribute" not in rules(text)
    assert parse(text).ports["gray_i"].hamming1 == "true"


def test_hamming1_takes_a_value_and_does_not_eat_the_type():
    """The value must land on -hamming1, not be appended to -type."""
    p = parse(HEAD + "accellera_cdc::set_port -name g -direction input "
                     "-type data -hamming1 1\n").ports["g"]
    assert p.type == "data" and p.hamming1 == "1"


# ---- 3. Table 3: -clock_period -------------------------------------------
def test_clock_period_is_a_port_attribute():
    """Table 3: `clock_period`, "string {clock period}, Conditional — This
    attribute is required for generating assertions, including fast to slow
    assertions. See also 8.4."
    """
    assert "-clock_period" in COMMANDS["set_port"]
    text = (HEAD + "accellera_cdc::set_port -name clk_a -direction input "
                   "-type clock -clock_period 10ns\n")
    assert errors(text) == []
    assert parse(text).ports["clk_a"].clock_period == "10ns"


# ---- 4. an unknown attribute is named, not blamed on -type ---------------
def test_an_unknown_attribute_is_reported_by_name():
    """Clause 6.1 NOTE: "The accellera_cdc namespace cannot include non-standard
    extensions. If custom extensions are needed, a different namespace name
    should be used." That is a NOTE, so it is a warning — but it must name the
    attribute.

    v0.64.0 folded `-bogus_attr x` into the value of `-type`, so the file was
    rejected with "type not defined" and the real problem was never named.
    """
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_port -name d -direction input -type data "
              "-bogus_attr x")
    assert c.ports["d"].type == "data", "the unknown token ate the -type value"
    r = check(c)
    assert not [f for f in r.errors if f.rule == "type not defined"]
    assert any(f.rule == "unknown attribute" and "bogus_attr" in f.detail
               for f in r.findings)


def test_an_unknown_attribute_does_not_swallow_the_next_attribute():
    """After the unknown token, the following attributes must still parse."""
    p = parse("accellera_cdc::set_port -name d -direction input -type data "
              "-bogus_attr x -polarity low\n").ports["d"]
    assert p.type == "data"
    assert p.raw.get("polarity") == "low"


def test_a_negative_number_is_a_value_not_an_attribute():
    """Table 3's own comment for -cdc_control_setup: "If the value is -2,
    associated_inputs data port can toggle at max up to 2 destination clock
    cycles after cdc_control enables data crossing." A parser that treats every
    `-token` as an attribute would reject that conformant value."""
    text = (HEAD + "accellera_cdc::set_port -name vld -direction input "
                   "-type cdc_control -polarity high -cdc_control_setup -2\n")
    assert errors(text) == []
    assert parse(text).ports["vld"].control_setup == "-2"


# ---- 5. Table 2 / Clause 6.3 b): set_param -ignore ----------------------
def test_set_param_accepts_ignore():
    """Table 2 gives the parameter domain an `ignore` attribute: "Boolean
    {0 or 1, true or false} (case independent), Optional — Tells that the
    parameter can be ignored."
    """
    assert "-ignore" in COMMANDS["set_param"]
    c = parse("accellera_cdc::set_module -name m\n"
              "accellera_cdc::set_param -name MSB -type int -value 7 -ignore true\n")
    assert c.params["MSB"].ignore is True
    assert c.params["MSB"].value == "7", "the ignored token ate the value"


def test_an_ignored_parameter_that_is_still_referred_to_is_an_error():
    """Clause 6.3: "There shall be an error if: ... b) If parameter is ignored
    and still referred to in subsequent commands." Table 2 repeats it: "Any
    parameter that is ignored but still referred to in the model in following
    commands is a failure."
    """
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_param -name MSB -type int -value 7 -ignore true\n"
            "accellera_cdc::set_port -name {DATA[MSB:0]} -direction input -type data\n")
    found = errors(text)
    assert any("ignored parameter referenced" in e and "MSB" in e for e in found), found


def test_an_ignored_parameter_that_is_not_referred_to_is_conformant():
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_param -name MSB -type int -value 7 -ignore true\n"
            "accellera_cdc::set_port -name {DATA[7:0]} -direction input -type data\n")
    col = parse(text)
    assert col.params["MSB"].ignore is True
    assert col.params["MSB"].value == "7", "-ignore ate the -value"
    assert errors(text) == []


def test_a_parameter_that_is_not_ignored_may_be_referred_to():
    """The clause only bites when the parameter is declared -ignore."""
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_param -name MSB -type int -value 7\n"
            "accellera_cdc::set_port -name {DATA[MSB:0]} -direction input -type data\n")
    assert errors(text) == []


def test_a_longer_identifier_is_not_a_reference_to_the_parameter():
    """A reference is the identifier itself; `MSB_i` does not refer to `MSB`."""
    text = ("accellera_cdc::set_module -name m\n"
            "accellera_cdc::set_param -name MSB -type int -value 7 -ignore true\n"
            "accellera_cdc::set_port -name MSB_i -direction input -type data\n")
    assert errors(text) == []


def test_parameter_type_must_come_from_table_2():
    """Table 2: `type`, "defined set {int, string, Boolean*, number (hex,
    decimal, oct, binary)}"."""
    assert errors("accellera_cdc::set_module -name m\n"
                  "accellera_cdc::set_param -name X -type int -value 3\n") == []
    assert any("parameter type not defined" in e
               for e in errors("accellera_cdc::set_module -name m\n"
                               "accellera_cdc::set_param -name X -type integer -value 3\n"))


# ---- Table 3: -polarity for cdc_control / rdc_control -------------------
@pytest.mark.parametrize("ptype", ["cdc_control", "rdc_control"])
def test_polarity_is_mandatory_for_a_control_port(ptype):
    """Table 3, `polarity`: "This attribute is mandatory for async reset,
    cdc_control, and rdc_control; otherwise, it is optional. For cdc_control
    and rdc_control, 'low_high' is not allowed." Neither half was checked.
    """
    assert any("polarity missing" in e
               for e in errors(HEAD + f"accellera_cdc::set_port -name c -direction input "
                                      f"-type {ptype}\n"))
    assert any("polarity not allowed" in e
               for e in errors(HEAD + f"accellera_cdc::set_port -name c -direction input "
                                      f"-type {ptype} -polarity low_high\n"))
    assert errors(HEAD + f"accellera_cdc::set_port -name c -direction input "
                         f"-type {ptype} -polarity low\n") == []


def test_low_high_stays_legal_for_an_async_reset():
    """Table 3 allows `low_high` everywhere except on the two control types."""
    assert errors(HEAD + "accellera_cdc::set_port -name rst_n -direction input "
                         "-type async_reset -polarity low_high\n") == []


# ---- Table 3: the cdc_control / rdc_control pairing ---------------------
@pytest.mark.parametrize("ptype,attr", [("cdc_control", "cdc_control"),
                                        ("rdc_control", "rdc_control")])
def test_a_data_port_must_name_the_control_that_names_it(ptype, attr):
    """Table 3, `cdc_control`: "This attribute is mandatory for a data port if
    it is paired with a port of type cdc_control"; `rdc_control`: "This attribute
    is required for a data port that is paired with a control port of type
    rdc_control". Annex A.3: "For a data port (-type data), the option
    -cdc_control specifies a unique CDC control port. If such a relation exists,
    it is mandatory to describe it in this way."

    The control names the data port through -associated_inputs, so the relation
    exists and the data port must describe it. v0.64.0 never checked it.
    """
    base = (HEAD + f"accellera_cdc::set_port -name cq -direction input -type {ptype} "
                   f"-polarity high -associated_inputs d_i\n")
    assert any("control pairing missing" in e
               for e in errors(base + "accellera_cdc::set_port -name d_i "
                                      "-direction input -type data\n"))
    assert errors(base + f"accellera_cdc::set_port -name d_i -direction input "
                         f"-type data -{attr} cq\n") == []


def test_a_control_that_names_no_data_port_requires_nothing():
    """Table 3 calls -associated_inputs "an optional part of the abstracted
    model", so the reverse direction is not required."""
    assert errors(HEAD + "accellera_cdc::set_port -name cq -direction input "
                         "-type cdc_control -polarity high\n"
                         "accellera_cdc::set_port -name d_i -direction input "
                         "-type data\n") == []


# ---- Clause 4: referential consistency for the six unresolved attributes
def test_cdc_static_must_name_a_declared_clock():
    """Table 3: `cdc_static` is a "space-separated list {clock-names}"; Clause 4
    requires declarations to be "explicitly defined and referentially
    consistent"."""
    assert any("undeclared clock" in e and "cdc_static" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -cdc_static nosuch_clk\n"))
    assert errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                         "-type data -cdc_static clk_a\n") == []


def test_associated_inputs_and_outputs_must_name_declared_ports():
    """Table 3: both are "space-separated list {ports}"."""
    assert any("undeclared port" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name o -direction output "
                                      "-type data -associated_inputs nosuch_i\n"))
    assert any("undeclared port" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name i -direction input "
                                      "-type data -associated_outputs nosuch_o\n"))


def test_a_cdc_control_reference_must_be_a_cdc_control_port():
    """Table 3: `cdc_control` is a "space-separated list {associated-ports}" and
    Annex A.3 calls it "a unique CDC control port"."""
    text = (HEAD + "accellera_cdc::set_port -name notctrl -direction input -type data\n"
                   "accellera_cdc::set_port -name d -direction input -type data "
                   "-cdc_control notctrl\n")
    assert any("not a control port" in e for e in errors(text))
    assert any("undeclared port" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -cdc_control nosuch\n"))


def test_the_rdc_data_family_must_resolve():
    """Table 3: `rdc_data_from_reset`/`rdc_data_to_reset` are {reset-names} and
    `rdc_data_to_clock` is {clock-names}; none of them was ever resolved."""
    assert any("undeclared reset" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -rdc_data_from_reset nosuch_rst\n"))
    assert any("undeclared clock" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -rdc_data_to_clock nosuch_clk\n"))


# ---- Table 3 / Table 2: enumerated values -------------------------------
def test_ignore_must_be_blocked_or_hanging():
    """Table 3, `ignore`: "defined set {blocked, hanging}"; 4.3.6 uses exactly
    `-ignore hanging` and `-ignore blocked`."""
    assert any("ignore value not defined" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -ignore dangling\n"))
    for value in ("hanging", "blocked"):
        assert errors(HEAD + f"accellera_cdc::set_port -name d -direction input "
                             f"-type data -ignore {value}\n") == []


def test_logic_must_come_from_table_3():
    """Table 3, `logic`: "defined set {combo, inverter, glitch_free_combo,
    internal_sync}"; 4.3.10 lists the same four."""
    assert any("logic value not defined" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -logic combinational\n"))
    assert errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                         "-type data -logic glitch_free_combo\n") == []


def test_sampling_edge_must_be_pos_or_neg():
    """Table 3, `sampling_edge`: "defined set {pos, neg}"."""
    assert any("sampling_edge not defined" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -sampling_edge rising\n"))
    assert errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                         "-type data -sampling_edge neg\n") == []


# ---- Clause 6.4 b): an attribute that does not apply to the port type ---
def test_cdc_data_from_clock_is_prohibited_outside_cdc_control():
    """Clause 6.4: "There shall be an error if: ... b) an attribute is specified
    for a particular type of port that is not applicable to that type of port."
    Table 3, `cdc_data_from_clock`: "Mandatory for output ports of type
    cdc_control. Optional for input ports of type cdc_control. Prohibited for
    other port types."
    """
    assert any("attribute not applicable" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -cdc_data_from_clock clk_a\n"))
    assert errors(HEAD + "accellera_cdc::set_port -name cq -direction output "
                         "-type cdc_control -polarity high "
                         "-cdc_data_from_clock clk_a\n") == []


def test_associated_inputs_belongs_on_an_output_or_a_control_port():
    """Table 3, `associated_inputs`: "applicable to outputs ... applicable to
    inputs if considering a CDC control signal input"."""
    assert any("attribute not applicable" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name d -direction input "
                                      "-type data -associated_inputs x\n"))
    # the feedthrough case: an output port naming its inputs
    assert errors(HEAD + "accellera_cdc::set_port -name i0 -direction input -type data\n"
                         "accellera_cdc::set_port -name o -direction output -type data "
                         "-associated_inputs i0\n") == []


def test_associated_outputs_belongs_on_an_input_or_a_control_port():
    """Table 3, `associated_outputs`: "applicable to inputs"."""
    assert any("attribute not applicable" in e
               for e in errors(HEAD + "accellera_cdc::set_port -name o -direction output "
                                      "-type data -associated_outputs x\n"))
    # 4.3.9's own example
    assert errors(HEAD + "accellera_cdc::set_port -name data0_i -direction input "
                         "-type data -associated_outputs data0_o\n"
                         "accellera_cdc::set_port -name data0_o -direction output "
                         "-type data\n") == []


# ---- Clause 6.5 with an unnamed clock group (Table 6: name is Optional) --
def test_an_unnamed_clock_group_is_still_checked():
    """Table 6 makes `name` Optional and `clocks` Mandatory; Clause 6.5: "There
    shall be an error if one or more specified clock names do not exist in the
    design." v0.64.0 dropped an unnamed group, so the check never ran."""
    assert any("undeclared clock" in e
               for e in errors(HEAD + "accellera_cdc::set_clock_group "
                                      "-clocks {clk_a nosuch}\n"))
    assert errors(HEAD + "accellera_cdc::set_clock_group -clocks {clk_a clk_b}\n") == []


# ---- no over-rejection: the standard's own worked examples stay clean ----
def test_a_rich_conformant_file_has_no_errors():
    """Everything the fixes touch, used correctly, in one file.

    A new mandatory check that fires on conformant input would be worse than
    the defect it fixes.
    """
    text = """
accellera_cdc::set_module -name mod0
accellera_cdc::set_param -name MSB -type int -value 7
accellera_cdc::set_param -name LSB -type int -value 0
accellera_cdc::set_port -name clk0_i -direction input -type clock -clock_period 10ns
accellera_cdc::set_port -name clk1_i -direction input -type clock -frequency 100
accellera_cdc::set_port -name rst0_n_i -direction input -type async_reset -polarity low
accellera_cdc::set_port -name mode_i -direction input -constant 0
accellera_cdc::set_port -name gray_i -direction input -type data \\
  -associated_to_clocks clk0_i -hamming1 true -logic internal_sync \\
  -sampling_edge neg -cdc_control cdcq0_i
accellera_cdc::set_port -name {DATA[MSB:LSB]} -direction input -type data \\
  -associated_to_clocks clk0_i -associated_to_reset rst0_n_i
accellera_cdc::set_port -name cdcq0_i -direction input -type cdc_control \\
  -polarity high -cdc_data_from_clock clk1_i -associated_from_clocks clk0_i \\
  -associated_inputs {gray_i} -associated_to_clocks clk0_i \\
  -cdc_control_setup 2 -cdc_control_hold -1
accellera_cdc::set_port -name rdcq0_i -direction input -type rdc_control \\
  -polarity low -blocking_polarity 0 -rdc_data_from_reset rst0_n_i \\
  -rdc_data_to_reset rst0_n_i -rdc_data_to_clock clk0_i \\
  -rdc_clock_gate_location internal
accellera_cdc::set_port -name d_o -direction output -type data \\
  -associated_from_clocks clk0_i -associated_from_reset rst0_n_i \\
  -rdc_control rdcq0_i -associated_inputs {DATA[MSB:LSB]}
accellera_cdc::set_port -name static_i -direction input -type data \\
  -cdc_static clk0_i
accellera_cdc::set_port -name gone_i -direction input -type data -ignore hanging
accellera_cdc::set_clock_group -name g -clocks {clk0_i clk1_i}
accellera_cdc::set_clock_group -clocks {clk0_i clk1_i}
accellera_cdc::set_reset_assertion_sequence -name seq -assert_sequence {rst0_n_i}
"""
    found = errors(text)
    assert found == [], found

"""The eight Clause 8 SVA defects that made the generated assertions illegal or
unbindable, one test each.

Every test here fails on the code before v0.60.0 and passes after. The shared
premise is the one in `cdc_sva`'s docstring: a property that cannot elaborate,
or a module that cannot be bound, protects nothing — so "it emits something" is
not the bar. Where a construct's legality is checked, it is checked with a real
SystemVerilog front-end (pyslang's elaborator, which resolves names inside
properties), not by eye.

Clauses are quoted from `CDC_Standard_text.txt`, the extracted text of the
Accellera CDC/RDC Interface Standard v1.0.
"""
import re

import pytest

from wengold.cdc_standard import parse
from wengold.cdc_sva import emit

HEAD = ("accellera_cdc::set_module -name m\n"
        "accellera_cdc::set_port -name clk_a -direction input -type clock\n"
        "accellera_cdc::set_port -name clk_b -direction input -type clock\n")


def sv(extra: str, head: str = HEAD) -> str:
    return emit(parse(head + extra))


def elab(text: str) -> list:
    """Elaboration errors for a generated file, from a real SV front-end.

    `SyntaxTree.fromText` only proves it parses. A `Compilation` resolves every
    identifier a property names, so an undeclared clock, a duplicate assertion
    name or an illegal identifier is reported here.
    """
    pyslang = pytest.importorskip("pyslang")
    tree = pyslang.syntax.SyntaxTree.fromText(text)
    comp = pyslang.ast.Compilation()
    comp.addSyntaxTree(tree)
    diags = comp.getAllDiagnostics()
    return [f"{diags[i].code} at {diags[i].location}"
            for i in range(len(diags)) if diags[i].isError()]


def prop_names(text: str) -> list:
    return re.findall(r"\bproperty\s+([^\s;]+)\s*;", text)


# ---------------------------------------------------------------------------
# 1. Port names emitted verbatim as identifiers; a shared base_name collided
# ---------------------------------------------------------------------------
def test_shared_base_names_get_distinct_legal_property_names():
    """Two ports sharing a `base_name` produced the *same* property and
    assertion name, and `DATA[7:4]` was used verbatim as an identifier.

    Table 3 allows a port to be named by a slice (`{DATA[7:4]}`), so the two
    slices are two crossings; an identifier cannot contain `[` or `:`, and a
    redefinition does not elaborate.
    """
    out = sv("accellera_cdc::set_port -name {DATA[7:4]} -direction input "
             "-type data -associated_to_clocks clk_b\n"
             "accellera_cdc::set_port -name {DATA[3:0]} -direction input "
             "-type data -associated_to_clocks clk_b\n")
    assert "p_cdc_stable_DATA_7_4" in out
    assert "p_cdc_stable_DATA_3_0" in out
    names = prop_names(out)
    assert len(names) == len(set(names)), f"duplicate property name: {names}"
    for n in names:
        assert re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", n), f"{n} is not an identifier"
    assert not elab(out), elab(out)


def test_a_port_name_starting_with_a_digit_is_still_an_identifier():
    out = sv("accellera_cdc::set_port -name {8bit} -direction input "
             "-type data -associated_to_clocks clk_b\n")
    for n in prop_names(out):
        assert not n[0].isdigit()
    assert not elab(out), elab(out)


# ---------------------------------------------------------------------------
# 2. Every port declared `input logic` — a multi-bit crossing on a scalar
# ---------------------------------------------------------------------------
def test_a_multi_bit_crossing_is_declared_with_its_width_and_direction():
    """Every port was declared `input logic`, so an 8-bit crossing was asserted
    on a scalar and an output crossing was declared an input.

    Table 3 makes `-direction` mandatory with the values
    "{input, output, inout}", and 4.3.1: "If the name does not include a range,
    it applies to all bits of the port" — so a declared range is the width.
    """
    out = sv("accellera_cdc::set_port -name {d[7:0]} -direction output "
             "-type data -associated_to_clocks clk_b\n")
    assert "output logic [7:0] d" in out
    assert "input logic d" not in out
    assert "$changed(d[7:0])" in out, "the check must name the declared slice"
    assert not elab(out), elab(out)


def test_an_unranged_data_port_gets_a_width_parameter_not_a_scalar():
    """4.3.1: "If the name does not include a range, it applies to all bits of
    the port" — the collateral does not state the width, so it is a parameter
    the integrator sets, not a silent scalar."""
    out = sv("accellera_cdc::set_port -name d -direction input "
             "-type data -associated_to_clocks clk_b\n")
    assert "parameter D_W = 1" in out
    assert "[D_W-1:0] d" in out
    assert not elab(out), elab(out)


def test_the_checker_binds_to_the_dut_it_was_generated_for():
    """A declared range must become a packed width. Verbatim, `DATA[7:0]` is
    `input logic DATA[7:0]` — an unpacked array — and binding that to an 8-bit
    DUT port does not elaborate (pyslang: NoImplicitConversion)."""
    dut = "module m (input logic clk_b, input logic [7:0] DATA);\nendmodule\n"
    src = (sv("accellera_cdc::set_port -name {DATA[7:0]} -direction input "
              "-type data -associated_to_clocks clk_b\n")
           + dut + "bind m m_cdc_checks u_cdc (.*);\n")
    assert not elab(src), elab(src)


# ---------------------------------------------------------------------------
# 3. A virtual clock declared as a real module input
# ---------------------------------------------------------------------------
def test_a_virtual_clock_is_not_declared_as_a_module_port():
    """Table 3: type virtual_clock "defines a virtual clock port that does not
    match an actual port in the module". Declaring it as an input of the bound
    checker gives a port no bind can drive, so the check never fires."""
    out = sv("accellera_cdc::set_port -name vclk -direction input "
             "-type virtual_clock\n"
             "accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks vclk\n")
    assert "input logic vclk" not in out, "a virtual port must not be a module port"
    assert "does not match an actual port" in out, "the omission must be explained"
    assert "clk_virtual" in out, "the crossing needs an explicit verification clock"
    assert "@(posedge clk_virtual)" in out
    assert not elab(out), elab(out)


# ---------------------------------------------------------------------------
# 4. `-cdc_control` is a list; only one control was honoured
# ---------------------------------------------------------------------------
def test_each_named_control_gets_its_own_83_block():
    """Table 3 types `cdc_control` as a "space-separated list
    {associated-ports}". The emitter compared the whole list against one port
    name, failed to resolve it, and dropped the entire 8.3 block."""
    out = sv("accellera_cdc::set_port -name c1 -direction input "
             "-type cdc_control -polarity high\n"
             "accellera_cdc::set_port -name c2 -direction input "
             "-type cdc_control -polarity low\n"
             "accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks clk_b -cdc_control {c1 c2} "
             "-cdc_control_setup 2 -cdc_control_hold 1\n")
    for c in ("c1", "c2"):
        assert f"a_cdc_setup_d_{c}" in out, f"no 8.3 setup check for {c}"
        assert f"a_cdc_hold_d_{c}" in out, f"no 8.3 hold check for {c}"
    assert "$rose(c1)" in out, "active-high control enables on the rising edge"
    assert "$fell(c2)" in out, "active-low control enables on the falling edge"
    names = prop_names(out)
    assert len(names) == len(set(names))
    assert not elab(out), elab(out)


# ---------------------------------------------------------------------------
# 5. A control that does not resolve picked an arbitrary data port
# ---------------------------------------------------------------------------
def test_an_unresolved_control_is_refused_not_replaced_by_a_data_port():
    """Clause 8.3 needs the port that enables the crossing. When the named
    control did not resolve, a fallback picked any *data* port that mentioned
    `-cdc_control` — asserting the crossing on a signal the collateral never
    named as its enable."""
    out = sv("accellera_cdc::set_port -name other -direction input -type data "
             "-cdc_control somethingelse\n"
             "accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks clk_b -cdc_control nosuch "
             "-cdc_control_setup 2 -cdc_control_hold 1\n")
    assert "nosuch" in out, "the unresolved name must be reported"
    assert "CDC-WARNING" in out
    assert "$rose(other)" not in out and "$fell(other)" not in out
    assert "p_cdc_setup" not in out, "no enable event means no 8.3 check"
    assert "p_cdc_hold" not in out


def test_a_control_named_but_declared_as_data_is_refused():
    """Table 3: `-cdc_control` names "associated-ports" of type cdc_control. A
    name that resolves to a data port is not an enable."""
    out = sv("accellera_cdc::set_port -name notactl -direction input "
             "-type data\n"
             "accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks clk_b -cdc_control notactl "
             "-cdc_control_setup 2\n")
    assert "not cdc_control" in out
    assert "p_cdc_setup" not in out
    assert "$rose(notactl)" not in out


# ---------------------------------------------------------------------------
# 6. Only the first entry of `-associated_to_clocks` was used
# ---------------------------------------------------------------------------
def test_every_destination_clock_gets_its_own_check():
    """Table 3 types `associated_to_clocks` as a "space-separated list
    {clock-names}", and Annex A fans one port out to several receivers. Only
    the first entry was checked, so the other crossings were never verified."""
    out = sv("accellera_cdc::set_port -name clk_c -direction input -type clock\n"
             "accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks {clk_b clk_c}\n")
    assert "p_cdc_stable_d_clk_b" in out
    assert "p_cdc_stable_d_clk_c" in out
    assert "@(posedge clk_b)" in out and "@(posedge clk_c)" in out
    assert out.count("assert property") == 2
    assert not elab(out), elab(out)


def test_the_annex_a_fanout_form_does_not_invent_a_clock():
    """Annex A writes a fanout entry as `{clk0_i internal_sync}` — clock plus
    the `-logic` value. `internal_sync` is Table 3's `logic` vocabulary, not a
    clock, so it must not become a check."""
    out = sv("accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks {clk_a {clk_b internal_sync} clk_b}\n")
    assert "@(posedge internal_sync)" not in out
    assert "p_cdc_stable_d_internal_sync" not in out
    assert out.count("assert property") == 2, "clk_a and one clk_b, not three"
    assert not elab(out), elab(out)


# ---------------------------------------------------------------------------
# 7. `-sampling_edge` absent silently assumed `pos`
# ---------------------------------------------------------------------------
def test_an_absent_sampling_edge_is_flagged_as_an_assumption():
    """The standard defines no default: 8.2 says only that "The port domain
    attribute -sampling_edge is used to define the active sampling edge of the
    first flop of a synchronizer", and Table 3 makes it conditional. Assuming
    `pos` in a passing comment is not saying so."""
    out = sv("accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks clk_b\n")
    assert "CDC-WARNING" in out
    assert "-sampling_edge" in out
    assert "no default" in out
    assert "@(posedge clk_b)" in out, "the check is still emitted, but flagged"


def test_a_declared_sampling_edge_is_not_flagged():
    out = sv("accellera_cdc::set_port -name d -direction input -type data "
             "-associated_to_clocks clk_b -sampling_edge neg\n")
    assert "@(negedge clk_b)" in out
    assert "no default" not in out


# ---------------------------------------------------------------------------
# 8. The 8.4 note named only the first crossing's destination clock
# ---------------------------------------------------------------------------
def test_the_84_note_names_every_destination_clock_and_compares_speeds():
    """8.4: "it is better to use either the fastest clock available between the
    two clocks or create a verification-only virtual clock". The note named one
    clock — the first crossing's — and never compared the two speeds, so the
    advice was the same for a fast-to-slow and a slow-to-fast crossing."""
    out = sv("accellera_cdc::set_port -name clk_a -direction input -type clock "
             "-frequency 200MHz\n"
             "accellera_cdc::set_port -name clk_b -direction input -type clock "
             "-frequency 50MHz\n"
             "accellera_cdc::set_port -name clk_c -direction input -type clock "
             "-frequency 400MHz\n"
             "accellera_cdc::set_port -name d1 -direction input -type data "
             "-associated_from_clocks clk_a -associated_to_clocks clk_b\n"
             "accellera_cdc::set_port -name d2 -direction input -type data "
             "-associated_from_clocks clk_a -associated_to_clocks clk_c\n",
             head="accellera_cdc::set_module -name m\n")
    note = out[out.index("Clause 8.4"):out.index("module m_cdc_checks")]
    assert "clk_b" in note and "clk_c" in note, "every destination clock is named"
    assert "fast-to-slow" in note, "200 MHz into 50 MHz is fast-to-slow (8.4)"
    assert "slow-to-fast" in note, "200 MHz into 400 MHz is slow-to-fast (8.4)"
    assert "200 MHz" in note and "50 MHz" in note and "400 MHz" in note


def test_an_undeclared_frequency_is_reported_not_guessed():
    out = sv("accellera_cdc::set_port -name d -direction input -type data "
             "-associated_from_clocks clk_a -associated_to_clocks clk_b\n")
    note = out[out.index("Clause 8.4"):out.index("module m_cdc_checks")]
    assert "not determined" in note
    assert "fast-to-slow" not in note and "slow-to-fast" not in note


# ---------------------------------------------------------------------------
# the whole file must elaborate
# ---------------------------------------------------------------------------
KITCHEN_SINK = """
accellera_cdc::set_module -name top
accellera_cdc::set_port -name clk_a -direction input -type clock -frequency 100MHz
accellera_cdc::set_port -name clk_b -direction input -type clock -frequency 250MHz
accellera_cdc::set_port -name vclk -direction input -type virtual_clock
accellera_cdc::set_port -name {DATA[7:4]} -direction input -type data \\
  -associated_from_clocks clk_a -associated_to_clocks {clk_b {clk_b internal_sync}} \\
  -sampling_edge neg -cdc_control {wr_en rd_en} \\
  -cdc_control_setup 2 -cdc_control_hold 1
accellera_cdc::set_port -name {DATA[3:0]} -direction input -type data \\
  -associated_from_clocks clk_b -associated_to_clocks vclk
accellera_cdc::set_port -name wr_en -direction input -type cdc_control -polarity high
accellera_cdc::set_port -name rd_en -direction input -type cdc_control -polarity low
accellera_cdc::set_port -name dout -direction output -type data \\
  -associated_to_clocks clk_b -cdc_control {wr_en nosuch} -cdc_control_setup 3
"""


def test_the_whole_generated_file_elaborates():
    out = emit(parse(KITCHEN_SINK))
    assert not elab(out), elab(out)
    names = prop_names(out) + re.findall(r"\b([A-Za-z_$][\w$]*)\s*:\s*assert property",
                                         out)
    assert len(names) == len(set(names)), "assertion names must be unique"


def test_every_declared_port_is_used_and_every_used_signal_is_declared():
    out = emit(parse(KITCHEN_SINK))
    for module in re.split(r"\nmodule ", out)[1:]:
        body = module.split("endmodule")[0]
        head, rest = body.split(");", 1)
        declared = set(re.findall(r"^\s*(?:input|output|inout) logic\s*(?:\[[^\]]*\]\s*)?"
                                  r"([A-Za-z_$][\w$]*)", head, re.M))
        used = set(re.findall(r"\$changed\(([A-Za-z_$][\w$]*)", rest))
        used |= set(re.findall(r"\$stable\(([A-Za-z_$][\w$]*)", rest))
        used |= set(re.findall(r"\$(?:rose|fell)\(([A-Za-z_$][\w$]*)", rest))
        used |= set(re.findall(r"@\((?:pos|neg)edge\s+([A-Za-z_$][\w$]*)", rest))
        missing = {u for u in used if u not in declared}
        assert not missing, f"used but not declared: {sorted(missing)}"

"""The VHDL front-end.

Structural, not a parser: entities are blocks, architectures say an entity is
implemented, instantiations are edges. These tests pin the parts that were wrong
while it was being written, because each one failed silently — the graph still
built, it was just missing or inventing edges.
"""
import pytest

from wengold.graph.builder import GraphBuilder
from wengold.graph.vhdl_backend import extract

ENTITY = """library ieee;
use ieee.std_logic_1164.all;
use work.neorv32_package.all;

entity leaf is
  generic (
    WIDTH : natural range 0 to 31 := 8;
    EN    : boolean               := false
  );
  port (
    clk_i  : in  std_ulogic;
    data_o : out std_ulogic_vector(WIDTH-1 downto 0)
  );
end entity leaf;

architecture leaf_rtl of leaf is
begin
  data_o <= (others => '0');
end architecture leaf_rtl;
"""

TOP = """entity top is
  port ( clk_i : in std_ulogic );
end entity top;

architecture top_rtl of top is
begin
  u_leaf : entity work.leaf
    generic map ( WIDTH => 16 )
    port map ( clk_i => clk_i );
end architecture top_rtl;
"""


def test_an_entity_is_a_block_and_an_architecture_is_not():
    u = extract(ENTITY, "leaf.vhd")
    assert u.modules == ["leaf"]
    assert "leaf_rtl" not in u.modules          # an architecture is not a block


def test_instantiations_become_edges():
    u = extract(TOP, "top.vhd")
    assert u.modules == ["top"]
    assert u.instantiations == [("top", "leaf", "u_leaf")]


def test_a_component_style_instantiation_is_found():
    src = TOP.replace("entity work.leaf", "leaf")
    assert extract(src, "top.vhd").instantiations == [("top", "leaf", "u_leaf")]


def test_generic_declarations_are_not_instantiations():
    """`WIDTH : natural` inside `generic (...)` looks exactly like
    `label : entity`. Without excluding those spans the entity's own generics
    were read as instantiations — `leaf instantiates std_ulogic_vector`."""
    u = extract(ENTITY, "leaf.vhd")
    assert u.instantiations == []


def test_parameters_are_read_but_not_the_initialiser_type():
    """`EN : boolean := false` must give EN, not also `boolean`, and
    `natural range 0 to 31 := 8` must not give `8`."""
    names = [n for n, _ in extract(ENTITY, "leaf.vhd").parameters]
    assert "WIDTH" in names and "EN" in names
    assert "boolean" not in names and "natural" not in names
    assert "8" not in names and "false" not in names


def test_a_package_and_its_body_are_one_package():
    src = "package p is\nend package;\npackage body p is\nend package body;\n"
    assert extract(src, "p.vhd").packages == ["p"]


def test_use_clauses_are_imports():
    u = extract(ENTITY, "leaf.vhd")
    assert "neorv32_package" in u.imports
    assert "std_logic_1164" in u.imports


def test_comments_do_not_create_blocks_or_edges():
    src = ("-- entity not_a_block is\n"
           "entity real is\nend entity;\n"
           "-- u_x : entity work.ghost\n")
    u = extract(src, "x.vhd")
    assert u.modules == ["real"]
    assert u.instantiations == []


def test_a_whole_vhdl_project_builds_a_graph(tmp_path):
    (tmp_path / "leaf.vhd").write_text(ENTITY)
    (tmp_path / "top.vhd").write_text(TOP)
    files = {p.name: p.read_text() for p in tmp_path.glob("*.vhd")}
    g = GraphBuilder().build_from_files(files, backend="auto")
    kinds = {n: d.kind.value for n, d in g.nodes.items()}
    assert kinds.get("leaf") == "rtl" and kinds.get("top") == "rtl"
    assert kinds.get("neorv32_package") == "package"
    # top instantiates leaf: the edge runs leaf -> top
    assert ("leaf", "top") in {(e.src, e.dst) for e in g.edges}
    assert not g.unresolved_nodes()


def test_a_mixed_vhdl_and_verilog_project_indexes_both(tmp_path):
    (tmp_path / "leaf.vhd").write_text(ENTITY)
    (tmp_path / "top.vhd").write_text(TOP)
    (tmp_path / "extra.v").write_text("module extra; endmodule\n")
    files = {p.name: p.read_text() for p in tmp_path.iterdir()}
    g = GraphBuilder().build_from_files(files, backend="auto")
    kinds = {n: d.kind.value for n, d in g.nodes.items()}
    assert kinds.get("extra") == "rtl", "the Verilog side must still be parsed"
    assert kinds.get("leaf") == "rtl" and kinds.get("top") == "rtl"


def test_an_instantiation_of_an_unknown_entity_is_unresolved():
    src = TOP.replace("work.leaf", "work.not_in_the_file_set")
    files = {"top.vhd": src}
    g = GraphBuilder().build_from_files(files, backend="auto")
    assert "top" in g.unresolved_nodes()
    assert g.completeness().get("complete") is False

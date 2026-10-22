"""Register-map and CDC front-ends."""
from wengold.graph.cdc import analyse, add_cdc_to_graph
from wengold.graph.model import DesignGraph, EdgeKind, Node, NodeKind
from wengold.graph.regmap import (add_regmap_to_graph, parse_ipxact, parse_rdl,
                                  registers_from_rdl)

RDL = """
addrmap sec_ctrl {
    reg {
        field { sw=rw; hw=r; } EN[0:0] = 0;
        field { sw=r;  hw=w; } STATUS[3:1];
    } ctrl @ 0x0000;
    reg { field { sw=rw; hw=r; } KEY[31:0] = 0; } key @ 0x0100;
};
"""

IPX = """<ipxact:component xmlns:ipxact="http://www.accellera.org/XMLSchema/IPXACT/1685-2014">
 <ipxact:memoryMaps><ipxact:memoryMap><ipxact:name>m</ipxact:name>
  <ipxact:addressBlock><ipxact:name>b</ipxact:name><ipxact:baseAddress>0x20000</ipxact:baseAddress>
   <ipxact:register><ipxact:name>sec_ctrl</ipxact:name>
    <ipxact:addressOffset>0x0</ipxact:addressOffset><ipxact:size>32</ipxact:size>
    <ipxact:field><ipxact:name>SEC_EN</ipxact:name><ipxact:bitOffset>0</ipxact:bitOffset>
     <ipxact:bitWidth>1</ipxact:bitWidth><ipxact:access>read-write</ipxact:access></ipxact:field>
    <ipxact:field><ipxact:name>RO</ipxact:name><ipxact:bitOffset>1</ipxact:bitOffset>
     <ipxact:bitWidth>3</ipxact:bitWidth><ipxact:access>read-only</ipxact:access></ipxact:field>
   </ipxact:register></ipxact:addressBlock></ipxact:memoryMap></ipxact:memoryMaps></ipxact:component>"""

MIXED = """
module mixed (input logic clk_a, input logic clk_b, input logic d_in);
    logic [7:0] a_reg, b_reg, c_reg, comb;
    always_ff @(posedge clk_a) begin a_reg <= d_in; end
    always_ff @(posedge clk_b) begin b_reg <= a_reg; end
    assign comb = a_reg + 1;
    always_ff @(posedge clk_b) begin c_reg <= comb; end
endmodule
"""

SINGLE = """
module single (input logic clk, input logic din);
    logic [7:0] q;
    always_ff @(posedge clk) q <= din;
endmodule
"""


# ---- SystemRDL ----------------------------------------------------------
def test_parse_rdl_registers_and_fields():
    amap = parse_rdl(RDL)
    assert amap.name == "sec_ctrl"
    names = {r.name: r for r in amap.registers}
    assert set(names) == {"ctrl", "key"}
    assert names["ctrl"].address == 0x0
    assert names["key"].address == 0x100
    fields = {f.name: f for f in names["ctrl"].fields}
    assert fields["EN"].sw == "rw" and fields["EN"].msb == 0
    assert fields["STATUS"].sw == "r" and fields["STATUS"].lsb == 1
    assert fields["STATUS"].width == 3
    assert amap.check() == []


def test_rdl_detects_address_overlap():
    bad = """
    addrmap m {
        reg { field { sw=rw; hw=r; } A[31:0]; } r0 @ 0x0;
        reg { field { sw=rw; hw=r; } B[31:0]; } r1 @ 0x2;
    };
    """
    assert any("overlap" in i for i in parse_rdl(bad).check())


def test_registers_from_rdl_compat():
    assert set(registers_from_rdl(RDL)) == {"ctrl", "key"}


# ---- IP-XACT ------------------------------------------------------------
def test_parse_ipxact():
    amap = parse_ipxact(IPX)
    reg = amap.registers[0]
    assert reg.name == "sec_ctrl" and reg.address == 0x20000 and reg.width == 32
    fields = {f.name: f for f in reg.fields}
    assert fields["SEC_EN"].sw == "rw"
    assert fields["RO"].sw == "r" and fields["RO"].width == 3


# ---- graph integration --------------------------------------------------
def test_regmap_nodes_and_edges():
    g = DesignGraph()
    g.add_node(Node("axi", NodeKind.RTL))
    add_regmap_to_graph(g, parse_rdl(RDL), driver="axi")
    assert "reg.ctrl" in g.nodes and "reg.ctrl.EN" in g.nodes
    assert any(e.src == "axi" and e.dst == "reg.ctrl" and e.kind is EdgeKind.DRIVES
               for e in g.edges)
    assert g.nodes["reg.ctrl.EN"].meta["sw"] == "rw"
    assert g.nodes["reg.key"].meta["address"] == "0x100"


# ---- CDC ----------------------------------------------------------------
def test_cdc_detects_crossings_and_domains():
    rep = analyse(MIXED, "mixed")
    assert rep.domains == {"clk_a": ["a_reg"], "clk_b": ["b_reg", "c_reg"]}
    sigs = {(c.signal, c.from_domain, c.to_domain) for c in rep.crossings}
    assert ("a_reg", "clk_a", "clk_b") in sigs
    assert ("comb", "clk_a", "clk_b") in sigs
    assert any(c.kind == "through_combinational" for c in rep.crossings)
    assert rep.unresolved == ["d_in"]          # cannot tell where d_in comes from


def test_cdc_clean_design_has_no_crossings():
    rep = analyse(SINGLE, "single")
    assert rep.crossings == []
    assert rep.domains == {"clk": ["q"]}


def test_cdc_marks_module_unresolved():
    g = DesignGraph()
    g.add_node(Node("mixed", NodeKind.RTL))
    add_cdc_to_graph(g, analyse(MIXED, "mixed"))
    assert "cdc.mixed.a_reg" in g.nodes
    assert g.nodes["cdc.mixed.a_reg"].meta["to"] == "clk_b"
    assert "mixed" in g.unresolved_nodes()     # d_in has no determinable domain


# ---- regression: real-RTL noise found on OpenTitan ---------------------
REALISH = """
module fifo (input logic clk_wr_i, input logic clk_rd_i, input logic wdata_i);
    parameter int unsigned Width = 8;
    localparam int Depth = 4;
    logic [Width-1:0] a_reg, b_reg;
    logic [Width-1:0] storage [Depth];
    genvar i;
    always_ff @(posedge clk_wr_i) begin a_reg <= wdata_i; end
    always_ff @(posedge clk_rd_i) begin b_reg <= a_reg; end
endmodule
"""


def test_cdc_does_not_flag_parameters_genvars_or_memories():
    rep = analyse(REALISH, "fifo")
    assert rep.domains == {"clk_rd_i": ["b_reg"], "clk_wr_i": ["a_reg"]}
    for noise in ("Width", "Depth", "i", "storage"):
        assert noise not in rep.unresolved, f"{noise} should not be reported unresolved"
    assert ("a_reg", "clk_wr_i", "clk_rd_i") in {
        (c.signal, c.from_domain, c.to_domain) for c in rep.crossings}

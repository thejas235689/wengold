"""A node that came from a file keeps its file.

The regex backend registers an instantiation of `timer` (from `timer dut(...)` in a
testbench) with no path. That second registration replaced the module node, so
`files_for` found no design file and every simulation through the regex backend
settled as "inconclusive: the result names no existing design file".

This only showed up without pyslang — i.e. exactly for a user who installed the
package and did not install the optional front-end.
"""
from wengold.graph.builder import GraphBuilder

DUT = "module timer(input logic clk, output logic q);\n  assign q = clk;\nendmodule\n"
TB = ("module timer_tb;\n  logic clk = 0; logic q;\n"
      "  timer dut(.clk(clk), .q(q));\nendmodule\n")


def test_an_instantiation_does_not_drop_the_module_path():
    g = GraphBuilder().build_from_files({"t.sv": DUT, "tb.sv": TB},
                                        backend="regex")
    node = g.nodes.get("timer")
    assert node is not None, sorted(g.nodes)
    assert node.path == "t.sv", f"the module lost its file: {node.path}"


def test_files_for_finds_the_design_file_through_the_regex_backend(tmp_path):
    from wengold.agent.runners import ToolRunner, Toolchain
    from wengold.kernel.validity import Result
    (tmp_path / "timer.sv").write_text(DUT)
    (tmp_path / "timer_tb.sv").write_text(TB)
    files = {str(p): p.read_text() for p in tmp_path.glob("*.sv")}
    g = GraphBuilder().build_from_files(files, backend="regex")
    res = {"s": Result("s", "sim", depends_on={"timer"})}
    r = ToolRunner(g, res, str(tmp_path), toolchain=Toolchain.empty())
    assert r.files_for("s"), "the design file must be found"

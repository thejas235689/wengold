# CDC/RDC collateral for examples/cdc/mixed_clocks.sv, written in the
# Accellera CDC/RDC Interface Standard v1.0 (March 2026) Tcl format.
#
# The standard exists so an IP can describe its clock and reset intent in a way
# any tool can read. Check it against the RTL with:
#
#   wengold cdc examples/cdc/mixed_clocks.sv \
#     --standard examples/cdc/mixed_clocks_cdc.tcl
#
# Only real module ports are declared here. `a_reg`, `b_reg`, `c_reg` and `comb`
# are internal signals in the RTL, and `set_port` describes ports — declaring an
# internal register would make the collateral disagree with the RTL.

accellera_cdc::set_module -name mixed_clocks

accellera_cdc::set_port -name clk_a -direction input -type clock
accellera_cdc::set_port -name clk_b -direction input -type clock

# d_in is sampled in the clk_a domain
accellera_cdc::set_port -name d_in \
  -direction input \
  -type data \
  -associated_to_clocks clk_a

# the two clocks are asynchronous, so any path between them needs a synchroniser
accellera_cdc::set_clock_group -name async_pair -clocks {clk_a clk_b}

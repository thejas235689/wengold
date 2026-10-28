# Annex C, Figure 5 — specifying a virtual_clock.
# Purpose: the tool correctly applies a virtual clock.
accellera_cdc::set_module -name fig05_virtual_clock
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name vclk0_o -direction output -type virtual_clock
accellera_cdc::set_port -name data0_i -direction input -type data \
  -associated_to_clocks vclk0_o

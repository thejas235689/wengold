# Annex C, Figure 4 — port domain attribute -associated_from_clocks.
# Purpose: the tool applies -associated_from_clocks to the intended point.
accellera_cdc::set_module -name fig04_associated_from_clocks
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name data0_o -direction output -type data \
  -associated_from_clocks clk0_i

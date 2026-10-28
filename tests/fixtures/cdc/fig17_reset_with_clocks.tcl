# Annex C, Figure 17 — active-high reset with -associated_to_clocks.
# Purpose: attributes for an active-high reset with both clock associations.
accellera_cdc::set_module -name fig17_reset_with_clocks
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name rst_i -direction input -type async_reset \
  -polarity high -associated_from_clocks clk0_i -associated_to_clocks clk1_i

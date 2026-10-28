# Annex C, Figure 6 — -associated_from_reset and -associated_to_reset.
# Purpose: the tool applies both reset attributes to the intended point.
accellera_cdc::set_module -name fig06_associated_resets
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name rst0_i -direction input -type async_reset -polarity low
accellera_cdc::set_port -name data0_i -direction input -type data \
  -associated_to_clocks clk0_i -associated_from_reset rst0_i
accellera_cdc::set_port -name data0_o -direction output -type data \
  -associated_from_clocks clk0_i -associated_to_reset rst0_i

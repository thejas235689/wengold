# Annex C, Figure 7 — -ignore hanging for input port data1_i.
# Purpose: the tool applies the ignore attribute for a hanging port.
accellera_cdc::set_module -name fig07_ignore_hanging
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name data0_i -direction input -type data \
  -associated_to_clocks clk0_i
accellera_cdc::set_port -name data1_i -direction input -type data -ignore

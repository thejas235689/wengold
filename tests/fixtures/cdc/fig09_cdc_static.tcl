# Annex C, Figure 9 — pseudo-static behaviour on a data crossing.
# Purpose: the tool uses -cdc_static to avoid unnecessary synchroniser circuitry.
accellera_cdc::set_module -name fig09_cdc_static
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name cfg_i -direction input -type data \
  -associated_to_clocks clk1_i -cdc_static

# Annex C, Figure 12 — internal synchroniser and combinational logic on paths.
# Purpose: the tool uses -logic and its values on the associated port.
accellera_cdc::set_module -name fig12_logic
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name d_i -direction input -type data \
  -associated_to_clocks clk0_i -logic internal_sync

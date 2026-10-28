# Annex C, Figure 10 — -constant attribute.
# Purpose: the tool correctly applies the constant attribute.
accellera_cdc::set_module -name fig10_constant
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name mode_i -direction input -type constant -constant

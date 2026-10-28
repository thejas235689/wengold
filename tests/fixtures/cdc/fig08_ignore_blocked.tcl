# Annex C, Figure 8 — -ignore blocked for input port data0_i.
# Purpose: the tool applies the ignore attribute for a blocked port.
accellera_cdc::set_module -name fig08_ignore_blocked
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name data0_i -direction input -type data -ignore

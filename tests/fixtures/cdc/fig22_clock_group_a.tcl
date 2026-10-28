# Annex C, Figure 22 — clock definition A.
# Purpose: two asynchronous clocks.
accellera_cdc::set_module -name fig22_clock_group_a
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_clock_group -name async_ab -clocks {clk0_i clk1_i}

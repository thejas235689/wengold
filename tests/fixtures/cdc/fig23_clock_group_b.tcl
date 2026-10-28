# Annex C, Figure 23 — clock definition B.
# Purpose: three asynchronous clocks.
accellera_cdc::set_module -name fig23_clock_group_b
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name clk2_i -direction input -type clock
accellera_cdc::set_clock_group -name async_abc -clocks {clk0_i clk1_i clk2_i}

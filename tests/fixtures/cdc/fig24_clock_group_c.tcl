# Annex C, Figure 24 — clock definition C.
# Purpose: a mixture of synchronous and asynchronous clocks.
accellera_cdc::set_module -name fig24_clock_group_c
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name clk1_i -direction input -type clock
accellera_cdc::set_port -name clk2_i -direction input -type clock
accellera_cdc::set_clock_group -name sync_01 -clocks {clk0_i clk1_i} -polarity same
accellera_cdc::set_clock_group -name async_02 -clocks {clk0_i clk2_i}

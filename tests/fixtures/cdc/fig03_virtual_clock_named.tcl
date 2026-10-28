# Annex C, Figure 3 — specifying a virtual clock.
# Purpose: the tool applies name, direction and type to the intended point.
accellera_cdc::set_module -name fig03_virtual_clock_named
accellera_cdc::set_port -name clk_i -direction input -type clock
accellera_cdc::set_port -name vclk_rx -direction input -type virtual_clock
accellera_cdc::set_port -name d_i -direction input -type data \
  -associated_to_clocks vclk_rx

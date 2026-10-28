# Annex C, Figure 14 — active-high reset on an input with a virtual clock.
# Purpose: attributes for an active-high asynchronous reset from a virtual clock.
accellera_cdc::set_module -name fig14_active_high_reset
accellera_cdc::set_port -name vclk_rx -direction input -type virtual_clock
accellera_cdc::set_port -name rst_i -direction input -type async_reset \
  -polarity high -associated_from_clocks vclk_rx

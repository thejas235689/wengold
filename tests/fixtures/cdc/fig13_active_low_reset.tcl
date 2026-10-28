# Annex C, Figure 13 — active-low reset on an input with a virtual clock.
# Purpose: attributes for an active-low asynchronous reset from a virtual clock.
accellera_cdc::set_module -name fig13_active_low_reset
accellera_cdc::set_port -name vclk_rx -direction input -type virtual_clock
accellera_cdc::set_port -name rst_ni -direction input -type async_reset \
  -polarity low -associated_from_clocks vclk_rx

# Annex C, Figure 26 — reset assertion sequence.
# Purpose: reset synchronisation that depends on the sequence of several
# asynchronous resets.
accellera_cdc::set_module -name fig26_reset_assertion_sequence
accellera_cdc::set_port -name clk0_i -direction input -type clock
accellera_cdc::set_port -name rst0_ni -direction input -type async_reset \
  -polarity low
accellera_cdc::set_port -name rst1_ni -direction input -type async_reset \
  -polarity low
accellera_cdc::set_reset_assertion_sequence -name rst_seq \
  -sequence {rst0_ni rst1_ni}

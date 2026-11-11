# Counter requirements (example)

REQ-001: When rst_n is asserted low, count becomes 0 asynchronously.
REQ-002: On rising clk when rst_n=1 and en=1, count increments by one.
REQ-003: On rising clk with en=0, count retains its previous value.
REQ-004: The four-bit count wraps from 15 back to 0.

Coverage objective: observe reset, increment, hold, and wrap-around. A completed testbench simulation does not prove coverage closure; import observed bins and review gaps.

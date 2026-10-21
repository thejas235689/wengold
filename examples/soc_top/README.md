# soc_top — the bundled walkthrough

A tiny inference SoC with four blocks (`soc_top`, `dma`, `sec_firewall`,
`npu`). Revision r2 introduces a one-line security bug in `sec_firewall.sv`
(the protection bit is read backwards). `python -m wengold.demo` shows the
kernel identify exactly which results fail, keep the ones that still hold, and
name the minimum set of checks to re-establish the design.

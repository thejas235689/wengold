# Advanced waveform debugging in Linux Silicon Studio

Open a project with `wengold desktop --native /path/to/project`, choose
**Waveforms**, and load a VCD from a project evidence folder such as `waves/`
or `formal-results/`. Imported VCD is observed trace data, not a specification
diagram or a new verification verdict.

1. Filter by a hierarchical name or glob such as `subsystem_tb.dut.*`. Use
   **Pin** to mark signals and **Pinned only** to declutter the timeline.
2. Click a timeline sample to place A. Shift-click or right-click to place B.
   The table shows each value at both cursors. **Go** snaps a VCD tick to the
   nearest sample. **Next change** and **Previous change** use the selected
   signal and cursor, including transitions between X and Z.
3. Use the readout to measure elapsed time. It uses real VCD ticks and the declared
   timescale, or raw ticks when no timescale is known. The interactive timeline
   spaces samples evenly for navigation, so use the timestamp ruler and Δ for
   measurement, not pixel distance.
4. Inspect a signal's source matches and explicitly choose a file and line to
   open in the RTL editor. These are lexical matches, not a resolved hierarchy.
   In **Wave Debug**, selecting a finding jumps to its observed sample.
   Use **Bookmark cursor** to keep named timestamps while the trace is open.
5. Pin the signals to share and set A and B to different times. **Export WaveDrom**
   writes WaveJSON with the trace path, SHA-256, original bounds, and exact uniform
   tick grid. If the grid exceeds 240 slots, narrow the window rather than losing
   time resolution. The last slot displays the endpoint value only. Use WaveDrom
   to render the file for GitHub Markdown:

   ```sh
   npx wavedrom --input observed-waveform.json > observed-waveform.svg
   ```

The desktop reads VCD files up to 8 MiB and displays at most 256 digital signals
and 1,200 timestamps. It reports omitted signals and truncated samples. Real
and string signals are not decoded. Formal witness VCDs can be inspected as raw
traces, but the viewer does not infer proof status, assumptions or solver step
mappings from a VCD alone.

## Reproduce the dropped DMA write with Xezim

From the repository root, with Xezim 0.11.6 on PATH, work in a new directory
so the intentional failure does not modify the reference project:

```sh
demo_dir=$(mktemp -d)
cp -R examples/soc_verification/rtl "$demo_dir/"
cp examples/soc_verification/subsystem_tb.sv "$demo_dir/"
mkdir "$demo_dir/waves"
(
    cd "$demo_dir"
    xezim --wave -D WENGOLD_DEBUG_VCD -D DROP_WRITE -s subsystem_tb \
        rtl/*.sv subsystem_tb.sv > dropped-write.log 2>&1
)
# Nonzero simulator exit is expected. Confirm the intended check failed.
rg 'WENGOLD_VCD_TICK|FAIL:REQ-DATA' "$demo_dir/dropped-write.log"
wengold desktop --native "$demo_dir"
```

Load `waves/dma-debug.vcd`. Filter `subsystem_tb.*`, and pin the top-level
`clk`, `addr`, `data`, `gd`, `ready`, `rd`, and `value`.
In this run the simulator reports `FAIL:REQ-DATA:10` at VCD tick `112`.
Jump to the logged VCD tick, not to cycle 10. Bookmark the failure and compare
the readback around ticks 110–112. The address changes from 4 to 5 and its value
changes from `0x39` to `0x00`. The checker expected `0xA7` at address 5.

To compare with a clean run, repeat the simulation in a second directory
without `-D DROP_WRITE`. The clean test reports `SOC_PREVIEW_PASS`.

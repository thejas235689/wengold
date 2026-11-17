# Advanced waveform debugging in Linux Silicon Studio

Open a project with `wengold desktop --native /path/to/project`, choose
**Waveforms**, and load a VCD or FST from a project evidence folder such as `waves/`
or `formal-results/`. Imported VCD and FST are observed trace data, not a specification
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

The desktop reads VCD or FST files up to 8 MiB and displays at most 256 digital signals
and 1,200 timestamps. It reports omitted signals and truncated samples. Real
and string signals are not decoded. Formal witness VCDs can be inspected as raw
traces, but the viewer does not infer proof status, assumptions or solver step
mappings from a VCD alone.

## Compare a baseline against a candidate

Open **Trace Tools → Trace comparison**, select a baseline and a candidate
VCD or FST, then **Load and compare**. By default each trace starts at its
first captured timestamp. To align at a reset release, handshake, or a
bookmark, enter that event's observed tick from each file and apply alignment.
Traces with declared timescales are compared in physical time, even if their
time units differ. Two traces without timescales can be compared in raw ticks.
A trace with units and a trace without units cannot be aligned.

The table reports the first different four-state value per matched signal,
plus paths found on only one side and same-name signals whose widths differ.
Click a row for synchronized baseline and candidate plots around the first
difference. The plots show up to 14 aligned sample slots at a time, with equal
width per slot. Use the reported timestamps, not pixel distance, to measure
time. Comparison matches exact hierarchical paths and covers only the
overlapping captured window. It does not infer renamed or missing signals.

## Decode APB or AXI transactions

Load a trace in **Waveforms**, then open **Trace Tools → Protocol lanes**.
Choose APB, AXI4, or AXI4-Lite and enter the prefix that precedes each protocol
signal, such as `tb.dut.` or `tb.dut.s_axi_`. The decoder looks for standard
signal names with that prefix. Enter the full clock or active-low reset signal
path when it differs from the default protocol name. Use the lane map or
double-click a row to jump to the observed sample in **Waveforms**.

- APB shows completed accesses, read or write, address and available payload,
  wait edges, and setup-to-completion latency when setup was captured.
- AXI shows independent AW, W, B, AR and R handshakes, available fields, and
  wait edges. It correlates AW to B and AR to the last R beat by ID, in order
  within each ID. AXI4-Lite uses in-order address/response pairing without IDs.
  W beats are visible on their own lane. This viewer does not attribute W beats
  to an AW burst or check all protocol requirements. Ambiguous address or
  completion edges can suspend correlation for that direction until reset.
- Decoding uses stable pre-edge values. Controls that change at the sampling
  timestamp can be ambiguous, so those events are skipped and counted. Fields
  with a same-timestamp change or X/Z are marked ambiguous. Missing lanes,
  unpaired responses, unknown reset edges, and truncated input are reported.

## Load FST files

Install the GTKWave package for your Linux distribution and verify
`command -v fst2vcd`. Place the `.fst` under a project evidence directory
such as `waves/`, refresh files, and use **Load FST**. The app runs the
converter locally outside the UI thread without modifying your trace.
WaveDrom export retains the FST filename and the original file's SHA-256.

FST is decoded through `fst2vcd`, not a native random-access FST index.
Input and expanded VCD are each limited to 8 MiB and conversion is time-bounded.
If the converter is missing or the trace exceeds those limits, the viewer
shows an error. The same digital signal and timestamp caps apply after conversion.

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

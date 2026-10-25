# Do WENGOLD's algorithms work on real projects?

Every number here came from running the tool on the project named. The question
"does the algorithm work" is answered two ways: against the kernel's own risk set,
and against evidence from outside WENGOLD entirely.

## The test

An algorithm that flags blocks worth looking at should flag **real problems** more
often than chance. Two ground truths, neither produced by the algorithm:

* **unresolved** — blocks whose dependencies do not resolve. The kernel computes
  this from the graph, and anything downstream of such a block is `unknown`. It is
  the real risk set.
* **simulation outcome** — does the block compile and run on its own? Evidence from
  Icarus Verilog, outside WENGOLD.

The statistic is a **permutation test**: shuffle the flags, keeping their number
the same, and count how often chance does as well. `p` is the fraction of 2,000
shuffles that matched or beat the observed hit count. A lift number alone cannot
tell you whether a signal is real — this can.

## Result: the flag is real, on projects with enough problems to find

| project | blocks | unresolved | flagged | hits | by chance | lift | p |
| --- | --- | --- | --- | --- | --- | --- | --- |
| cva6 | 458 | 32 | 33 | **16** | 2.31 | **6.94×** | **0.000** |
| ibex | 345 | 17 | 28 | **8** | 1.38 | **5.80×** | **0.000** |
| OpenTitan | 879 | 78 | 55 | **14** | 4.88 | **2.87×** | **0.000** |
| cv32e40p | 154 | 8 | 7 | 1 | 0.36 | 2.75× | 0.300 |
| picorv32 | 31 | 16 | 3 | 2 | 1.55 | 1.29× | 0.520 |
| neorv32 | 86 | **0** | 8 | 0 | 0.00 | — | 1.000 |

**On the three projects with 17 or more unresolved blocks the enrichment is large
and cannot be chance: 0 of 2,000 permutations matched, on all three.** On the three
small projects it is indistinguishable from a random draw — and neorv32 has *zero*
unresolved blocks, so there is nothing there to detect and its 8 flags are
unfalsifiable.

This corrects an earlier reading. The small projects were never evidence that the
algorithm fails; they are evidence that **the test needs roughly 30+ real problems
before it has the power to show anything.** I had reported the small-project
numbers without that qualification.

## The hits are real blocks, not a modelling artefact

The 16 flagged-and-unresolved blocks in cva6:

```
ariane   ariane_gate_tb   ariane_peripherals   ariane_tb
ariane_testharness   ariane_verilog_wrap   …
```

These are the **top-level integration modules** — exactly the ones that instantiate
vendor macros (`IOBUF`, `FIFO_DUALCLOCK_MACRO`) and therefore never resolve. The
algorithm is finding the modules whose dependencies are missing, which is the thing
worth looking at.

## Waveforms

The flagged blocks were simulated and rendered. Two produced real waveforms:

* **picorv32 → `delay4`** — a delay line; you can see `q1`/`q2`/`q3` shifting.
* **cv32e40p → `gated_clk_cell`** — a **real clock-gating cell**. `clk_out` follows
  `clk_in` only while the enable chain is high, which is the cell doing its job.

**neorv32 produced no waveform from any of its 8 flagged blocks** — 8 tried, 0
compiled. On a project with nothing unresolved, the flags point at blocks that
cannot even be simulated in isolation. That is consistent, and it is also why the
flag is only actionable where there are real problems.

## Where the algorithms do *not* reach a real project

**`learn supervised` does not read the project at all.** It accepts a path and
ignores it: it generates its own register designs and labels them with the real
formal engine. Its features describe fields of a generated spec, so they do not
apply to a real core. The command now says so:

```
!! this trains on 24 generated register designs — it does NOT read
   /scratch/repos/cv32e40p. Its features describe generated spec fields
   and do not apply to a real core.
```

**The simulation ground truth showed zero lift.** Flagged and control blocks failed
to simulate at the same rate (neorv32 3/3 vs 3/3; cv32e40p 3/3 vs 3/3; picorv32 1/3
vs 1/3). This is not the algorithm failing — it is the measure being weak: most
small modules need their dependencies to compile, so "does it simulate alone" is
mostly a question about the file set, not about design risk.

**The transformer and the LSTM were not run on these projects.** Their corpus is a
synthetic grammar; they read sentences, not designs.

## Verdict

* **Clustering / DBSCAN: works, and is now demonstrated rather than asserted** —
  2.9×–6.9× enrichment for the kernel's real risk set, p < 0.001 on three projects.
* **Supervised: works, but on generated designs only** — it makes no claim about
  your project, and the CLI no longer implies that it does.
* **RL: still loses** to a two-line greedy heuristic on every project tested.
* **Regression: still a surrogate for a label the kernel already computes exactly.**

The honest summary is narrower than "the ML works" and stronger than "the ML is
decoration": **one algorithm is measurably finding real problems on real designs,
one does not touch your design at all, and two are demonstrations.**

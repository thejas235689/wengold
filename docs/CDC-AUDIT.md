# CDC audit — four parallel reviews, and what is fixed

Four sub-agents audited the CDC implementation against the Accellera CDC/RDC
Interface Standard v1.0, each on one area, concurrently. They returned **64
findings**. Five are fixed in v0.59.1. **Fifty-nine are open**, listed below with
their severity, because a finding that is dropped is worse than one that is
scheduled.

Severity is the sub-agents' judgement, spot-checked by me: I verified the
`virtual_reset`, SVA negative-repetition, polarity, declared-setup and 8.2-window
findings by running the code before fixing them. The rest are self-reports.

## Fixed in v0.59.1

| # | area | defect |
| --- | --- | --- |
| 1 | `cdc_sva` | **The setup property was not legal SVA.** `$stable(x)[-SETUP_CYCLES]` uses a negative repetition, which does not elaborate — so Clause 8.3's setup requirement had no working assertion at all. Now a conjunction of `$past` comparisons over the declared window. |
| 2 | `cdc_sva` | **`-polarity` was ignored.** An active-low control enables on the falling edge; the check fired on `$rose` regardless, so it gated on the wrong event. |
| 3 | `cdc_sva` | **The declared setup and hold were discarded** for a default of 1. Table 3 makes them integer counts of destination clock cycles; a declared 3 was checked as 1. Now used directly, and a non-integer value (`2ns`) is reported rather than silently dropped. |
| 4 | `cdc_sva` | **The 8.2 window was six edges, not four.** `$stable[*3]` is three periods while the comment and `$error` both claimed a four-edge window — the assertion was stricter than the clause it cited. Now `[*2]`. |
| 5 | `cdc_standard` | **`virtual_reset` was not a port type.** Table 3 and Clause 5 d) 2) define it; a conformant declaration was rejected. Also exempted from the RTL port-set comparison, like `virtual_clock`. |

## Open — would let a real CDC bug through

These are the ones I would fix first. All are in `cdc_analysis.py` / `cdc.py`,
WENGOLD's own analyses rather than the standard's, and all are **false negatives**.

| area | defect |
| --- | --- |
| `cdc_analysis` | A **multi-bit bus** through a 2-FF synchroniser is given verdict `synchronised` and `Analysis.clean` returns `True`. The width hazard lives only in free text, and `Crossing.as_dict` omits width entirely — so a machine-readable consumer sees a pass. Per-bit settling means the value read can mix old and new. |
| `cdc_analysis` | `_classify` returns `synchronised` if **any** 2-FF chain exists on the destination clock. A metastable first stage feeding other destination logic, or a single-flop read beside the chain, is reported clean. |
| `cdc_analysis` | `analyse_text` creates crossings only from clocked writes, so a signal that also reaches the destination through **combinational** logic produces no entry — and `clean` is `True`. `cdc.py` does see those paths, so the two tools disagree. |
| `cdc.py` | `_WRITE` matches `sig <= expr` inside an `if` condition, so a **comparison** is recorded as an assignment. The crossing vanishes and the signal is listed in the wrong domain. |
| `cdc.py` | `_block_body` truncates at the first `;`, so an `if (en) begin ... end` body loses every assignment after it. |
| `cdc.py` | `if clock in src: continue` suppresses **every** crossing into a mixed-domain combinational node — the genuine contribution from the other domain is lost. |
| `cdc_analysis` | Only `AlwaysFFBlock` with nonblocking assignments is read, so plain `always @(posedge clk)` designs yield an **empty crossing list** (and `render()` is the only place that says empty is not clean). |

## Open — the checker rejects conformant input

| area | defect |
| --- | --- |
| `cdc_standard` | `-type` is unconditionally mandatory, but 4.3.8 exempts `-constant` ports: only name and direction are required there. |
| `cdc_standard` | `-hamming1` and `-clock_period` are Table 3 port attributes the code does not accept — and because unknown `-tokens` are folded into the previous value, the resulting error blames `-type`. |
| `cdc_standard` | `set_param` does not accept `-ignore`, so Clause 6.3 b) cannot be enforced. |
| `cdc_standard` | An unnamed clock group (`-name` is optional per Table 6) is silently discarded, along with the Clause 6.5 check on its clock names. |
| `cdc_scenarios` | **§5.4's predicate requires `-rdc_control` on the input data port, but the standard's own Example 34 does not declare one.** A collateral built to the example is reported as not supporting §5.4, and the message tells the user to add a non-standard attribute. |

## Open — overclaims and missed checks

| area | defect |
| --- | --- |
| `cdc_scenarios` | §5.4 and §5.5 are not independently assessable: one direction-blind list of control ports decides both, so an output control can be cited as evidence for an input-port scenario. |
| `cdc_scenarios` | `-cdc_control` is accepted where `-rdc_control` is meant, so a pure CDC pairing satisfies an RDC scenario. |
| `cdc_scenarios` | `-blocking_polarity` is never checked, though the standard makes it mandatory whenever an `rdc_control` is associated with a port. |
| `cdc_scenarios` | §5.6 is granted on any `-rdc_control` string: the control is not required to exist, to be of type `rdc_control`, or to carry `-rdc_data_from_reset`. |
| `cdc_scenarios` | §5.3 is granted by a `set_reset_assertion_sequence` that specifies no order at all. |
| `cdc_standard` | `-polarity` is mandatory for `cdc_control`/`rdc_control` too, and `low_high` is prohibited for them — neither is checked. |
| `cdc_standard` | `-cdc_control`/`-rdc_control` pairing on the data port is never enforced. |
| `cdc_standard` | Referential consistency is checked for four of the reference-bearing attributes; `cdc_static`, `associated_inputs`, `associated_outputs`, `cdc_control`, `rdc_control` and the `rdc_data_*` family are never resolved. |
| `cdc_standard` | Enumerated values are not validated for `-ignore` (`blocked`/`hanging`), `-logic`, `-sampling_edge` or parameter `-type`. |
| `cdc_standard` | Clause 6.4 b) — an attribute applied to a port type it does not apply to — is not implemented at all. |

## Open — IP-XACT (Clause 7)

| area | defect |
| --- | --- |
| `cdc_ipxact` | **Table 11 defines five semantic consistency rules; the code implements three** and says "three" in its docstring and output. `CDCInputPortReference` and `CDCOutputPortReference` are missing, so an `inputPortReference` pointing at an output port passes. |
| `cdc_ipxact` | Control ports are emitted as `accellera-cdc:data` and read back as type `data` — a `cdc_control` port loses its type on round-trip. |
| `cdc_ipxact` | `accellera-cdc:controlFromClock` is neither written nor read. |
| `cdc_ipxact` | `-logic` is written only for clock-like ports, so data and reset ports lose it. |
| `cdc_ipxact` | A virtual clock's direction (meaningful per 4.3.4) is overwritten with `phantom` and returns as `output`. |
| `cdc_ipxact` | The data extension carries 4 of the ~12 Table 3 attributes 7.3 says must all be captured. |
| `cdc_ipxact` | The generated component has no VLNV, though the docstring claims one. |

## Open — generated SVA will not compile or bind

| area | defect |
| --- | --- |
| `cdc_sva` | Port names are emitted verbatim as identifiers; two ports sharing a `base_name` produce duplicate property and assertion names. |
| `cdc_sva` | Every port is declared `input logic` — a multi-bit crossing is asserted on a scalar. |
| `cdc_sva` | A virtual clock used as a destination is declared as a real module input, which cannot be bound. |
| `cdc_sva` | `-cdc_control` is a space-separated list; a crossing with more than one control silently loses its whole 8.3 block. |
| `cdc_sva` | When the named control does not resolve, a fallback picks an arbitrary *data* port as the enable signal. |
| `cdc_sva` | Only the first entry of `-associated_to_clocks` is used, so a port fanned out to several receiver clocks gets one check. |
| `cdc_sva` | `-sampling_edge` absent silently assumes `pos`; the standard defines no default. |
| `cdc_sva` | The 8.4 note names only the first crossing's destination clock and never compares source and destination speeds. |

## How this was produced

Four `Explore` sub-agents ran concurrently, each given the standard's extracted
text and one or two modules, and each required to quote the standard for every
finding and to return an empty list rather than invent one. Their briefs named the
defect shapes that have actually shipped in this project before — an attribute the
standard defines that the code rejects, an invented attribute, a required check
that is missing — because those are the ones that matter.

Two findings were **rejected** on review rather than fixed:

* a claim that `-virtual_port` and `-frequency` are invented — they appear in the
  standard's own Clause 6.4 command sketches, so accepting them is defensible;
* a claim that treating an unknown command as a warning is wrong — Clause 6.1's
  "cannot include non-standard extensions" is a NOTE, not a stated error condition.

Both are recorded here because a rejected finding is part of the audit.

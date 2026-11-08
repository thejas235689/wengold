# A local model, and what actually makes the agent faster

Two separate questions that are easy to conflate. A local model adds **capability**.
It does not add speed — it costs it. The speed comes from not redoing work.

## Part 1 — speed, measured

Indexing is the only expensive step. Everything the kernel does is a graph lookup.

| step | neorv32 (77 files) | cva6 (478 files) |
| --- | --- | --- |
| index the design | 0.59 s | 8.5 s |
| `perceive()` over 50 results | 0.150 s | — |
| `completeness()` | 0.000 s | — |
| `plan()` | 0.000 s | — |

### What did not work

**Parallel parsing made it slower.** Files are parsed one at a time, so a thread pool
looked obvious. Measured on cva6:

| workers | threads | processes |
| --- | --- | --- |
| 2 | 0.9× | 0.8× |
| 4 | 0.8× | 0.8× |
| 8 | 0.8× | — |

`pyslang` holds the GIL, so threads serialise. Processes have to ship the file text
and the results between them, which costs more than the parse saves. Neither is
shipped.

### What did work

Splitting the work shows where it goes:

```
preprocess (pp.run)   0.74 s    11%
extract               6.27 s    89%
```

`extract()` is a pure function of the preprocessed text, so it can be cached on that
text — and only that text. Keying on the *source file* would be wrong: a file's
`include` resolves against the rest of the file set, so the same source preprocesses
differently in two projects. Preprocessing therefore always runs (it is the cheap
11%), and only `extract` is cached. Content-addressed, so there is no invalidation
logic and no staleness.

| project | cold | warm | speedup |
| --- | --- | --- | --- |
| neorv32 | 0.65 s | 0.42 s | **1.6×** |
| cva6 | 9.16 s | 2.50 s | **3.7×** |

Verified identical, not just faster: same 3,260 edges, same nodes, same blocks and
the same unresolved set with and without the cache. A faster wrong answer is worse
than a slow right one.

```bash
wengold doctor                # cache location, hit rate, front-end
WENGOLD_NO_CACHE=1 wengold index ./rtl   # for a clean measurement
```

The cache lives in `~/.cache/wengold/units`, content-addressed. `WENGOLD_CACHE_DIR`
overrides it.

## Part 2 — a local model

### It is off unless you turn it on

```bash
ollama pull qwen2.5-coder:7b
export WENGOLD_LLM_MODEL=qwen2.5-coder:7b
wengold doctor --llm
```

`doctor --llm` is the only end-to-end proof that matters: it probes the server, checks
the configured model is among those it has, and round-trips one request.

### What it is for

Two jobs the kernel cannot do at all:

* **`draft_rtl`** — RTL from a description the spec grammar does not cover, e.g. *"a
  FIFO with almost-full and a 2-cycle read latency"*. The output is compiled by
  iverilog, and it is a **suggestion**: nothing has been simulated or checked.
* **`explain_failure`** — prose for a result the kernel already established.

### What it is not for

**It never decides what to check.** Every decision the agent makes today is justified
by a graph fact and costs microseconds; a 7B model on CPU costs seconds. Putting a
model in that loop would make the agent slower and less reliable at once.

### What is verified, and what is not

The client is tested against a **mock server** speaking the same protocol, so the
request shape for both backends, the response parsing, the timeout and the failure
paths are real. The one thing not tested is a model's output quality — this was
written in a sandbox with 2 CPUs and 2 GB of RAM, where no useful model fits.

The rule the tests protect: **a missing model raises, it never returns `""`.** An
empty answer reads as "the model had nothing to say", which is a different and much
worse claim than "there is no model".

### Backends

| `WENGOLD_LLM_BACKEND` | default endpoint | notes |
| --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434` | native `/api/generate` |
| `openai` | `http://127.0.0.1:8080/v1` | any OpenAI-compatible server: llama.cpp, vLLM, LM Studio |

Model size against RAM, roughly: 7B needs ~8 GB, 14B ~16 GB, 32B ~32 GB. On CPU,
expect a few seconds per answer; a GPU changes that by an order of magnitude.

## Sarvam, locally

Two Sarvam models are open-weight on the Hub. They are not interchangeable, and the
difference decides what each can be used for.

| | `sarvam-m` | `sarvam-1` |
| --- | --- | --- |
| parameters | 24B | 2B |
| base | Mistral-Small-3.1-24B | trained from scratch |
| instruction-tuned | **yes** | **no** |
| licence | Apache-2.0 | Sarvam non-commercial |
| context | 32K | 8K |
| serve | `vllm serve sarvamai/sarvam-m --port 8080` | `ollama run sarvam-1` |
| RAM at Q4 | ~16 GB (BF16 ~48 GB) | ~1.5 GB |

```bash
wengold doctor --presets          # both, with licence and capability
export WENGOLD_LLM_MODEL=sarvam-m
wengold doctor --llm              # probe, confirm the model, round-trip one request
```

`from_env()` routes each preset to the backend it is published for — Sarvam-M to
vLLM's OpenAI-compatible endpoint, Sarvam-1 to Ollama. Set `WENGOLD_LLM_BACKEND` to
override.

### Why Sarvam-1 is refused for drafting and explaining

Its model card says it *"cannot be used directly as a chat or an instruction-following
model"*. A completion model continues text; it does not answer. Asked for *"a FIFO
with almost-full"* it returns plausible continuation, and this tool would present
that as a draft. So both instruction jobs raise instead, naming the model that can
do the job.

Sarvam-1 remains useful for what it is actually good at — Indic prose and
translation — through `ask`.

### The licence

Sarvam-M's weights are Apache-2.0, so a local copy does not expire even though the
hosted Sarvam-M endpoint has been deprecated. Sarvam-1 is non-commercial, which is a
different proposition if you intend to ship. `doctor --presets` prints it rather than
leaving it in a README nobody reads.

### What is verified

The preset table, the routing, the refusal and the CLI output are tested. **Neither
model has been run** — this was written where no 24B model fits. `doctor --llm` on
your machine is the check that closes that.

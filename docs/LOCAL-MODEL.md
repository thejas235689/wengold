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

## Dhīr 2B for offline specification and log assistance

Wengold includes an optional **Dhīr 2B** preset in **Local AI** and
**DV Workflow**. It does not download weights, start a server, or change the
default model. Download the
[community Q4_K_M GGUF](https://huggingface.co/dassomnath/Dhir-2B-GGUF/blob/580edf584d5b4042ca3dd75814b1d29ab7b6d7d0/dhir-2b-Q4_K_M.gguf)
of ZenteiQ's Apache-2.0 model once. The file is about 1.2 GiB. Inference
also needs memory for context and runtime. See
[ZenteiQ's local deployment notes](https://www.zenteiq.ai/research/blog/inferencing-dhir-on-edge-devices/).

From the directory containing the downloaded file, with a recent llama.cpp:

```sh
llama-server -m dhir-2b-Q4_K_M.gguf --alias dhir-2b \
  --host 127.0.0.1 --port 8080 --ctx-size 8192 --jinja
```

In Wengold, click **Use Dhīr 2B**, then **Test Inference** in **Local AI**.
The default endpoint is `http://127.0.0.1:8080/v1`. If using a different
server alias, enter the exact model ID shown by **Connect / Models**. CLI users
can set `WENGOLD_LLM_MODEL=dhir-2b` and run `wengold doctor --llm`.

Try a short requirement summary or use **DV Workflow → Root-Cause Debug**
with a project-relative Xezim or Yosys log. Check the cited lines yourself.
The output is a draft or a debug hypothesis. It does not alter simulation,
coverage, proof results, or signoff.

## Gemma 4 E4B via local Ollama

Install a current [Ollama](https://ollama.com/download) release with Gemma 4
support. Start Ollama if it is not already running, then download the model once:

```sh
ollama pull gemma4:e4b
WENGOLD_LLM_MODEL=gemma4:e4b sh wengold.sh doctor --llm
```

Use **Use Gemma 4** in **Local AI**, **DV Workflow** (including all eight
Independent Agents), or **Wave Debug**. The preset selects the Ollama backend
at `http://127.0.0.1:11434` by default. In Local AI, **Test Inference** checks
the connection with a short test prompt before you send project input. Use the
exact downloaded tag if selecting a different Gemma 4 variant manually.
Wengold does not download models automatically or change your default model.

## Qwen4-Max via Alibaba Cloud Model Studio

[`qwen4-max`](https://www.alibabacloud.com/help/en/model-studio/qwen4-max) is
hosted by Alibaba Cloud. It is not the local Qwen Coder model and is not a
fallback for local inference. Enable it only for work you can send off-device.
Selecting and running it sends the task and relevant file excerpts, retrieved
context, logs, or bounded waveform evidence to Alibaba Cloud.

Set `DASHSCOPE_API_KEY` in the launch environment using your credential
manager, then enable the backend explicitly with `WENGOLD_ALLOW_QWEN_CLOUD=1`.
The default base URL is Singapore's shared Model Studio endpoint,
`https://dashscope-intl.aliyuncs.com/compatible-mode/v1`.
Set `WENGOLD_QWEN_URL` to your official workspace's OpenAI-compatible base URL
if your API key is scoped to another region or workspace. Wengold accepts
official Model Studio HTTPS hosts, does not follow redirects or use system
proxies for model requests, and does not store the key in the project.

Start Studio from that environment, click **Use Qwen4-Max (cloud)**, and use
**Test Inference** in **Local AI** before sending any project context. You can
also choose the model in **DV Workflow** or **Wave Debug**. These are text
workflows even though the upstream models support other modalities.
The browser IDE's local model flow and `doctor --llm` are unchanged.

For the CLI, select the cloud backend explicitly and start with public
example inputs:

```sh
WENGOLD_ALLOW_QWEN_CLOUD=1 sh wengold.sh sv-agent formal examples/soc_verification \
  --backend qwencloud --rtl rtl/dma.sv --spec requirements.json \
  --task 'Draft a completion-interrupt assertion and a reachability cover.'
```

## Independent SystemVerilog agents

In **DV Workflow → Independent Agents**, select a role and explicit project
inputs. Choose Gemma 4, Dhīr 2B, another instruction-following local model, or
explicitly enable and select Qwen4-Max. Specification, RTL, UVM, Formal/SVA, Debug, Coverage,
Integration and Signoff Review each run in a fresh model session. No other role
must run first and no previous agent's output is sent automatically. The Studio
keeps the latest result separately for each role in the current project session.

For example, from the repository root with a local server running:

```sh
sh wengold.sh sv-agent formal examples/soc_verification \
  --model gemma4:e4b --rtl rtl/dma.sv --spec requirements.json \
  --task 'Draft a completion-interrupt assertion and a reachability cover.'
```

Debug, Coverage and Signoff Review require an explicitly selected
project-relative log or JSON report. Each result has a run ID and input and
output hashes. Large input files may be excerpted, which the result records.
These roles generate read-only drafts or review notes. They do not edit RTL,
run EDA, credit coverage, establish a proof, or grant signoff. Use the
existing independent simulation and formal workflows to establish those results.

## Kimi K3 through the native C inference engine

WENGOLD now has an optional **kimi-k3-cli** model backend for
[FareedKhan-dev/kimi-k3-in-c](https://github.com/FareedKhan-dev/kimi-k3-in-c).
The upstream project is a C99/OpenMP CPU inference engine. Its CLI writes a
machine-readable JSON report, which WENGOLD consumes instead of scraping
terminal output. The adapter sends one prompt per process using --prompt-file,
--incremental, --out and the checkpoint tokenizer. System instructions are
prepended as ordinary prompt text; this is batch generation, not the upstream
interactive XTML chat REPL.

### Install the upstream engine

```sh
git clone https://github.com/FareedKhan-dev/kimi-k3-in-c.git
cd kimi-k3-in-c
make -j
make test
./bin/k3 --help
```

Complete the upstream model setup separately. Its README describes a roughly
**1.56 TB checkpoint** and a roughly **109 GB packed trunk**. Run its doctor and
download/packing steps only after checking available disk, RAM, and the
checkpoint's own access and licence terms. The C inference engine's Apache-2.0
licence does not automatically grant rights to the model weights.

Configure WENGOLD with the paths on the machine running Studio:

```sh
export WENGOLD_LLM_MODEL=kimi-k3-in-c
export WENGOLD_LLM_BACKEND=kimi-k3-cli
export WENGOLD_K3_BIN="$HOME/kimi-k3-in-c/bin/k3"
export WENGOLD_K3_MODEL_DIR="$HOME/k3model"
export WENGOLD_K3_TRUNK_DIR="$HOME/k3trunk"
export WENGOLD_K3_TOK_DIR="$HOME/k3model"
export WENGOLD_K3_PRESET=auto
export WENGOLD_K3_GEN=256
export WENGOLD_K3_TIMEOUT=3600
wengold doctor --llm
```

The native **Local AI** and **DV Workflow** model controls also expose
**Use Kimi K3 C**. The model selection does not download weights or start
the engine automatically; configure the environment and restart WENGOLD.

The adapter refuses to accept output if the executable fails, times out, the
JSON report is absent or malformed, generation is interrupted, layers are
incomplete, expert loads were dropped, or decoded text is empty. It uses
argument-list subprocess execution (no shell) and temporary prompt/output
files. Proprietary RTL prompts remain on the local machine.

### Important capability boundaries

- This first adapter is **text-only, single-request batch inference**. It does
  not connect Kimi K3's interactive chat REPL, expose an HTTP server, invoke
  WENGOLD tools, or autonomously execute EDA commands.
- It is available for drafting RTL and explaining already-established
  verification evidence. Model output is advisory and never changes proof,
  simulation, coverage, or signoff status.
- The upstream README describes CPU inference and memory presets, but real
  performance depends on your CPU, RAM, storage bandwidth, and checkpoint
  setup. WENGOLD CI uses a fake CLI for adapter tests; it does not download
  the checkpoint or claim a real Kimi K3 inference run.

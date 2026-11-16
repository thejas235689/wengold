# WENGOLD Multi-RAG for SystemVerilog

Multi-RAG adds project evidence to the Local AI workbench. Use it to draft RTL,
UVM or assertions against source you select, or inspect the same retrieval
without a model. Every excerpt includes its path, a source location and a
SHA-256 content fingerprint. Retrieved data and model output are not signoff.

## Run the included example

```bash
python3 -m pip install -e '.[slang]'
wengold multi-rag examples/dv_workflow \
  --query "counter4 reset timing, port widths and wrap behavior"
```

In Linux Silicon Studio, open the project and go to **Local AI**. Enter the task,
set **Multi-RAG** to `multi-rag.json`, and choose **Preview Multi-RAG context**
to inspect the ranked passages and conflicts without calling the model. Then
choose **Generate Draft** with a locally running model. Leaving the manifest
input blank preserves the existing generation workflow. Retrieval does not write
to your project. The model request goes directly to the configured loopback
server, without a proxy or cloud fallback.

## Choose the sources

Put a JSON manifest in the project root. All source paths are relative to that
root. List only material you want the local model to see.

```json
{
  "sources": [
    {"kind": "rtl", "path": "rtl/bridge.sv"},
    {"kind": "rtl", "path": "rtl/bus_pkg.sv"},
    {"kind": "sva", "path": "dv/write_checkers.sv"},
    {"kind": "spec", "path": "spec/write_timing.pdf"},
    {"kind": "registers", "path": "spec/csr.json", "scope": "write_bridge"},
    {"kind": "diagram", "path": "spec/timing_captions.json"}
  ],
  "compile_files": ["rtl/bus_pkg.sv", "rtl/bridge.sv"]
}
```

| Source kind | Index and provenance |
|---|---|
| `rtl`, `sva` | SystemVerilog design-unit syntax spans, identifiers, import/instantiation/include links, and source lines. Without `pyslang`, the bounded text fallback is labeled as such. |
| `spec` | Markdown, plain text and reStructuredText excerpts. PDF extraction uses local Poppler `pdftotext` on the first 20 pages and records the page number. |
| `registers` | JSON, SystemRDL or IP-XACT using WENGOLD's existing register front ends. Register rows retain addresses and bit fields. Use the same scope for sources describing the same register map. Competing values are reported together, without guessing a winner. |
| `diagram` | Reviewed text captions linked to an existing local image or PDF and its content hash. WENGOLD does not infer waveform behavior from pixels. |

A JSON register map has the form
`{"name":"write_bridge","registers":[{"name":"CTRL","address":"0x10","fields":[{"name":"enable","msb":0,"lsb":0,"sw":"rw","reset":0}]}]}`.
A diagram caption manifest has the form
`{"captions":[{"asset":"spec/write_response.svg","text":"The local write response window starts after both handshakes."}]}`.
Use one register row per register. The preview exposes disagreements between
maps when their scopes, register and field names align. It does not resolve
natural-language conflicts in specification prose.

## How retrieval and compiler feedback work

1. WENGOLD searches across all selected sources, and routes additional queries
   to relevant RTL, specification, CSR, SVA and diagram facets. It combines
   BM25 and lightweight character n-gram vectors with reciprocal rank fusion,
   then fills a small part of the context with linked design units or headers.
   The vectors are local lexical features, not neural or attention-head embeddings.
2. Generation receives a bounded JSON context with citations, conflicts and
   notes. The report records the excerpts actually sent. Greater retrieval
   relevance is not proof that a source is correct.
3. If installed, slang compiles a returned SystemVerilog draft and the optional
   ordered `compile_files` set. This scoped probe deliberately does not open
   filesystem includes. A reported missing symbol or header can trigger one
   targeted retrieval and regeneration if the index supplies new context.
   The original draft is kept if the retry does not improve the compiler check.
4. The workbench keeps the result marked **DRAFT**. A clean scoped compile is
   not UVM simulation, an SVA proof, an assertion-to-spec equivalence check, or
   a replacement for the project's complete build options and tool flow.
   Use the separate RTL check or reviewed EDA flow for subsequent validation.

The first implementation covers deterministic multi-source retrieval, hybrid
fusion, structural links and caption-based retrieval. Neural encoders,
attention-head MRAG, automatic vision-model ingestion and a formal semantic
admission gate are outside this change.

## Design references

- [VeriRAG — Knowledge Graph-Augmented RAG for Verilog and Assertion Generation](https://www.aspdac.com/aspdac2026/archive/pdf/1E-3.pdf)
- [MultiRAG — Knowledge-guided Multi-source Retrieval](https://arxiv.org/abs/2508.03553)
- [Multi-Head RAG — A separate attention-head approach](https://github.com/spcl/MRAG)

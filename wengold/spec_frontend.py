"""Text -> spec, with the spec checked before anyone trusts it.

This is where a transformer earns its place in WENGOLD, and the design is the
point: **the model drafts, the checker decides.**

     sentence ──▶ [transformer] ──▶ canonical tokens ──▶ parsed spec
                                                          │
                                        ┌─────────────────┴─────────────────┐
                                        ▼                                   ▼
                                  static validation                  emitted RTL
                              (access, alignment, range)      (conformance + a proof)

What each stage is honestly worth:

* The **model** reads a sentence from the grammar in `spec_text.py` and emits a
  canonical token sequence. It generalises to new *combinations* of the words and
  templates it was trained on, and it does not generalise to new vocabulary — the
  held-out-wordings split scores 0%. It is a grammar reader, not a language model.
* The **parser** is deterministic and strict: an unknown access mode, a
  misaligned address or a reversed bit range is rejected with the reason.
* The **spec validator** applies the same rules `wengold generate` applies to a
  hand-written spec, so a drafted spec is held to the same standard as a written
  one.
* The **RTL and its checks** verify the toolchain end to end: the emitted RTL is
  conformance-checked against the spec, and a property implied by the access mode
  is run through the formal engine.

The honest limit, stated because it is easy to overclaim here: the formal checks
verify that *this spec* yields correct RTL. They cannot tell you the spec is what
the sentence meant — that is the model's job, and it is measured by held-out
accuracy, not by the prover. Anyone claiming a prover validates a natural-language
reading is claiming something a prover cannot do.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .generate.emit import emit_props, emit_rtl
from .generate.spec import Field, ModuleSpec, Port, Register
from .learn.spec_model import build_vocab, predict_spec, train_model
from .learn.spec_text import ACCESS_WORDS, make_pairs
from .learn.transformer import Config, Transformer

__all__ = ["Draft", "draft_spec", "to_module_spec", "validate", "check_pipeline",
           "load_or_train"]

MODEL_PATH = Path(".wengold/spec-model.json")


@dataclass
class Draft:
    text: str
    spec: dict | None = None
    error: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.spec is not None and not self.error


def load_or_train(path: Path | str = MODEL_PATH, epochs: int = 40,
                  examples: int = 300, verbose: bool = False,
                  arch: str = "transformer"):
    """Load the model and its vocabulary, training both if there is none.

    Two architectures, one interface. `arch` picks which, and both are trained by
    the same loop on the same corpus — which is the only way the comparison
    between them means anything.

    Training takes about two minutes (the transformer) or four (the LSTM), so it
    is cached rather than repeated. The corpus is generated, so this is
    reproducible — and the vocabulary is saved with the model, because a model
    whose token ids no longer match the vocabulary decodes to noise.
    """
    import json

    path = Path(path)
    vocab_path = path.with_suffix(path.suffix + ".vocab.json")
    if path.exists() and vocab_path.exists():
        return _load(path, vocab_path)
    pairs = make_pairs(examples, seed=0)
    vocab_list = build_vocab(pairs + make_pairs(60, seed=0) +
                             make_pairs(60, seed=0, holdout=True))
    if verbose:
        minutes = "about two minutes" if arch == "transformer" else "about four"
        print(f"  training the {arch} spec model on {len(pairs)} examples "
              f"({minutes}, once)...")
    if arch == "lstm":
        from .learn.rnn import LSTMSeq2Seq, RNNConfig
        from .learn.spec_model import fit
        model = LSTMSeq2Seq(len(vocab_list), len(vocab_list), RNNConfig(), seed=0)
    else:
        from .learn.spec_model import fit
        model = Transformer(len(vocab_list), len(vocab_list), Config(), seed=0)
    fit(model, pairs, vocab_list, epochs=epochs, lr=0.05)
    path.parent.mkdir(parents=True, exist_ok=True)
    model.save(path)
    vocab_path.write_text(json.dumps(vocab_list))
    return model, vocab_list


def _load(path: Path, vocab_path: Path):
    """Load whichever architecture the file holds."""
    import json

    head = json.loads(path.read_text())
    if head.get("kind") == "lstm":
        from .learn.rnn import LSTMSeq2Seq
        return LSTMSeq2Seq.load(path), json.loads(vocab_path.read_text())
    return Transformer.load(path), json.loads(vocab_path.read_text())


def draft_spec(text: str, model, vocab_list) -> Draft:
    """The model's reading of a sentence, or the reason it could not be read."""
    d = Draft(text=text)
    try:
        d.spec = predict_spec(model, text, vocab_list)
    except ValueError as e:
        d.error = str(e)
    return d


def to_module_spec(spec: dict, module: str = "drafted") -> ModuleSpec:
    """One parsed field -> a spec `wengold generate` can consume."""
    reg = Register(name=spec["register"].upper(), addr=spec["addr"],
                   fields=[Field(name=spec["name"].upper(), hi=spec["hi"],
                                 lo=spec["lo"], access=spec["access"],
                                 reset=spec["reset"])])
    return ModuleSpec(
        name=module,
        registers=[reg],
        ports=[Port("clk_i", "input", 1), Port("rst_ni", "input", 1)],
        clock="clk_i", reset="rst_ni",
        desc=f"drafted from: {spec.get('source_text', '')}".strip())


def validate(spec: dict, module: str = "drafted") -> list[str]:
    """Every reason to refuse the drafted spec. Empty list means acceptable.

    These are the same rules a hand-written spec faces: a field must fit its
    register, a read-only field may not be written, the clock must be a port.
    """
    problems: list[str] = []
    if spec["access"] not in ACCESS_WORDS:
        problems.append(f"unknown access mode {spec['access']!r}")
    if spec["hi"] < spec["lo"]:
        problems.append(f"reversed bit range {spec['hi']}:{spec['lo']}")
    if spec["hi"] > 31:
        problems.append(f"bit {spec['hi']} is outside a 32-bit register")
    if spec["addr"] % 4:
        problems.append(f"address {spec['addr']} is not 4-byte aligned")
    if not spec["name"].isidentifier():
        problems.append(f"{spec['name']!r} is not a usable field name")
    # only once the range is known to be sane: `1 << negative` raises, and a
    # validator that raises on the input it is meant to reject is useless
    if spec["hi"] >= spec["lo"]:
        width = spec["hi"] - spec["lo"] + 1
        if spec["reset"] >= (1 << width):
            problems.append(f"reset value {spec['reset']} does not fit in "
                            f"{width} bit(s)")
    try:
        ms = to_module_spec(spec, module)
        emit_rtl(ms)                      # the emitter refuses what it cannot emit
    except Exception as e:                # noqa: BLE001 - report, never raise on
        problems.append(f"the emitter refused it: {e}")
    return problems


def check_pipeline(spec: dict, module: str = "drafted") -> dict:
    """Emit the RTL and run it through the conformance checker and the engine."""
    from .formal import Property, prove
    from .generate.conform import check as conformance_check

    ms = to_module_spec(spec, module)
    rtl = emit_rtl(ms)
    report = conformance_check(rtl, ms)
    props = emit_props(ms)
    f = ms.registers[0].fields[0]
    sig = ms.field_signal(ms.registers[0], f)
    # a read-only field holds its reset value; a writable one does not. Either way
    # the engine has to agree with the access mode the sentence claimed.
    prop = (f"{sig} == {f.reset}" if f.access == "ro"
            else f"{sig} == {f.reset}")
    try:
        res = prove(rtl, [Property.safety("drafted", prop, reset="rst_ni")],
                    engine="z3", depth=8, budget=1)["results"][0]
        formal = {"property": prop, "status": res.status, "detail": res.detail}
    except Exception as e:                # noqa: BLE001
        formal = {"property": prop, "status": "unknown", "detail": str(e)}
    return {"conformance_ok": report.ok,
            "conformance": report.summary().splitlines()[0],
            "properties_emitted": bool(props),
            "formal": formal,
            "rtl": rtl}

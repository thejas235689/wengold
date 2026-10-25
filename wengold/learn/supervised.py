"""Supervised: predict whether a property will fail, labelled by running the
real formal engine.

The kernel cannot answer this. It knows which results a change *invalidates* — it
computes that exactly — but whether a check then *fails* is only knowable by
running it. So the target here is measured, not invented: each example is a
generated design plus a property, and the label is whatever the formal engine
said when it was actually run.

That makes the training data honest and also small, which is the honest limit:
this is a triage model. Given a set of properties and a budget that does not
cover them all, it ranks the ones most likely to fail so they are run first. It
does not decide whether anything is proven — the engine does that.

Features are read from the *spec* and the property, both available before any run,
so the model can be applied to a property that has never been checked.
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["LogisticRegression", "Example", "build_dataset", "train_eval",
           "FEATURE_KEYS"]

FEATURE_KEYS = [
    "is_equality", "is_inequality", "compares_to_reset", "compares_to_zero",
    "target_is_field", "field_is_rw", "field_is_ro", "field_is_w1c",
    "field_width", "field_reset", "n_fields", "n_registers", "design_max_width",
    "target_bit_hi", "has_reset_port",
]


@dataclass
class Example:
    features: list[float]
    label: int
    design: str
    prop: str


@dataclass
class Metrics:
    n: int = 0
    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def accuracy(self) -> float:
        n = self.tp + self.fp + self.tn + self.fn
        return (self.tp + self.tn) / n if n else 0.0

    @property
    def precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 0.0

    @property
    def recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 0.0

    def render(self) -> str:
        return (f"n={self.n} acc={self.accuracy:.3f} "
                f"precision={self.precision:.3f} recall={self.recall:.3f} "
                f"(tp={self.tp} fp={self.fp} tn={self.tn} fn={self.fn})")


class LogisticRegression:
    """Plain gradient descent on the log-loss, with L2. No numpy, no sklearn."""

    def __init__(self, n_features: int, lr: float = 0.15, l2: float = 1e-3,
                 epochs: int = 400):
        self.w = [0.0] * n_features
        self.b = 0.0
        self.lr, self.l2, self.epochs = lr, l2, epochs
        self.mean: list[float] = [0.0] * n_features
        self.std: list[float] = [1.0] * n_features

    def _fit_scaler(self, X: list[list[float]]) -> list[list[float]]:
        n = len(X)
        d = len(X[0]) if n else 0
        self.mean = [sum(row[j] for row in X) / n for j in range(d)]
        self.std = []
        for j in range(d):
            var = sum((row[j] - self.mean[j]) ** 2 for row in X) / n
            self.std.append(math.sqrt(var) or 1.0)
        return self._scale(X)

    def _scale(self, X):
        return [[(row[j] - self.mean[j]) / self.std[j] for j in range(len(self.w))]
                for row in X]

    def fit(self, X, y):
        Xs = self._fit_scaler(X)
        for _ in range(self.epochs):
            gw = [0.0] * len(self.w)
            gb = 0.0
            for row, label in zip(Xs, y):
                p = self._sigmoid(sum(w * v for w, v in zip(self.w, row)) + self.b)
                err = p - label
                for j in range(len(self.w)):
                    gw[j] += err * row[j]
                gb += err
            n = len(Xs) or 1
            for j in range(len(self.w)):
                self.w[j] -= self.lr * (gw[j] / n + self.l2 * self.w[j])
            self.b -= self.lr * gb / n
        return self

    @staticmethod
    def _sigmoid(z: float) -> float:
        if z < -60:
            return 0.0
        if z > 60:
            return 1.0
        return 1.0 / (1.0 + math.exp(-z))

    def predict_proba(self, row: list[float]) -> float:
        xs = [(row[j] - self.mean[j]) / self.std[j] for j in range(len(self.w))]
        return self._sigmoid(sum(w * v for w, v in zip(self.w, xs)) + self.b)

    def predict(self, row: list[float], threshold: float = 0.5) -> int:
        return 1 if self.predict_proba(row) >= threshold else 0

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps({
            "w": self.w, "b": self.b, "mean": self.mean, "std": self.std,
            "features": FEATURE_KEYS}, indent=2) + "\n")

    @classmethod
    def load(cls, path: str | Path) -> "LogisticRegression":
        d = json.loads(Path(path).read_text())
        m = cls(len(d["w"]))
        m.w, m.b, m.mean, m.std = d["w"], d["b"], d["mean"], d["std"]
        return m


# ---- the dataset -----------------------------------------------------------
def _spec_for(seed: int):
    """A small register block, varied by seed."""
    from ..generate.spec import Field, ModuleSpec, Parameter, Port, Register
    rng = random.Random(seed)
    n_regs = rng.randint(1, 3)
    regs = []
    for r in range(n_regs):
        fields = []
        hi = 0
        for f in range(rng.randint(1, 4)):
            width = rng.choice([1, 1, 2, 4, 8])
            lo, hi = hi, hi + width - 1
            fields.append(Field(
                name=f"F{f}", hi=hi, lo=lo,
                access=rng.choice(["rw", "rw", "ro", "w1c"]),
                reset=rng.choice([0, 0, 1, 3])))
            hi += width
        regs.append(Register(name=f"R{r}", addr=r * 4, fields=fields))
    return ModuleSpec(
        name=f"blk{seed}", registers=regs,
        parameters=[Parameter(name="N", value=n_regs)],
        ports=[Port("clk_i", "input", 1), Port("rst_ni", "input", 1),
               Port("busy_o", "output", 1)],
        assigns=[])


def _num(literal: str) -> int | None:
    """Read a numeric literal: 3, 'h3, 4'h3, 8'd12."""
    s = literal.strip().strip(")").lower()
    if not s:
        return None
    m = __import__("re").fullmatch(r"(?:\d+)?'?([hdb]?)([0-9a-f_]+)", s)
    if not m:
        return None
    base = {"h": 16, "d": 10, "b": 2, "": 10}[m.group(1)]
    try:
        return int(m.group(2).replace("_", ""), base)
    except ValueError:
        return None


def _features(spec, field, prop: str) -> list[float]:
    width = field.width
    reset = field.reset
    bits = prop.replace(" ", "")
    rhs = bits.split("==")[-1] if "==" in bits else ""
    rhs_value = _num(rhs) if rhs else None
    return [
        1.0 if "==" in bits else 0.0,
        1.0 if ("<" in bits or ">" in bits) else 0.0,
        1.0 if rhs_value is not None and rhs_value == reset else 0.0,
        1.0 if rhs_value == 0 else 0.0,
        1.0,
        1.0 if field.access == "rw" else 0.0,
        1.0 if field.access == "ro" else 0.0,
        1.0 if field.access == "w1c" else 0.0,
        float(width), float(reset),
        float(sum(len(r.fields) for r in spec.registers)),
        float(len(spec.registers)),
        float(max(f.width for r in spec.registers for f in r.fields)),
        float(field.hi),
        1.0 if any(p.name == "rst_ni" for p in spec.ports) else 0.0,
    ]


def build_dataset(n_designs: int = 24, seed: int = 0, depth: int = 8,
                  verbose: bool = False) -> list[Example]:
    """Generate designs and properties, and label them by running the engine.

    A property is derived from a field, so the label genuinely depends on the
    field's access mode and reset value — which is exactly what the model has to
    learn.
    """
    from ..formal import Property, prove
    from ..generate.emit import emit_rtl

    out: list[Example] = []
    for s in range(n_designs):
        spec = _spec_for(seed * 1000 + s)
        rtl = emit_rtl(spec)
        for r in spec.registers:
            for f in r.fields:
                sig = spec.field_signal(r, f)
                for prop in (f"{sig} == {f.reset}",
                             f"{sig} == 0",
                             f"{sig} <= {(1 << f.width) - 1}"):
                    try:
                        # the symbolic engine, not the explicit one: a register
                        # block has a 32-bit address and data input, so the
                        # explicit search cannot complete the input space and
                        # reports `bounded` for everything. Nothing would ever be
                        # proven and the dataset would carry a single label.
                        res = prove(rtl, [Property.safety("p", prop,
                                                          reset="rst_ni")],
                                    engine="z3", depth=depth, budget=1)
                    except Exception:
                        continue
                    status = res["results"][0].status
                    if status not in ("fail", "proof"):
                        continue                     # bounded/unknown: no label
                    out.append(Example(_features(spec, f, prop),
                                       1 if status == "fail" else 0,
                                       spec.name, prop))
        if verbose:
            print(f"  {spec.name}: {len(out)} examples so far")
    return out


def train_eval(examples: list[Example], test_frac: float = 0.3,
               seed: int = 0) -> tuple[LogisticRegression, Metrics, Metrics]:
    """Split by *design*, not by example — properties from one design are not
    independent, and splitting them would flatter the score."""
    designs = sorted({e.design for e in examples})
    rng = random.Random(seed)
    rng.shuffle(designs)
    cut = max(1, int(len(designs) * (1 - test_frac)))
    train_d, test_d = set(designs[:cut]), set(designs[cut:])
    tr = [e for e in examples if e.design in train_d]
    te = [e for e in examples if e.design in test_d]
    if not tr or not te:
        tr = te = examples

    model = LogisticRegression(len(FEATURE_KEYS)).fit([e.features for e in tr],
                                                      [e.label for e in tr])
    return model, _metrics(model, tr), _metrics(model, te)


def _metrics(model: LogisticRegression, ex: list[Example]) -> Metrics:
    m = Metrics(n=len(ex))
    for e in ex:
        pred = model.predict(e.features)
        if pred and e.label:
            m.tp += 1
        elif pred and not e.label:
            m.fp += 1
        elif not pred and e.label:
            m.fn += 1
        else:
            m.tn += 1
    return m


def majority_baseline(examples: list[Example]) -> float:
    """The accuracy of always predicting the commoner label.

    Reported next to every model, because a high accuracy on a lopsided dataset
    means nothing without it.
    """
    if not examples:
        return 0.0
    pos = sum(e.label for e in examples)
    return max(pos, len(examples) - pos) / len(examples)


def precision_at_k(model: LogisticRegression, examples: list[Example],
                   k: int) -> float:
    """The metric that matters for triage: of the k we would run first, how many
    actually fail."""
    if not examples:
        return 0.0
    ranked = sorted(examples, key=lambda e: -model.predict_proba(e.features))[:k]
    return sum(e.label for e in ranked) / len(ranked)

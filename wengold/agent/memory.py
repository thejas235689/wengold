"""Dual-stream memory: what happened, and what is true.

Two streams, kept apart because they decay differently.

* **Episodic** — the runs: what changed, what was planned, what each check
  produced. Large, append-only, and only useful by similarity ("this change looks
  like one I have seen").
* **Semantic** — the facts that do not change run to run: which tools are
  installed, which blocks have never passed, which blocks always pass. Small,
  overwritten, and useful directly.

Keeping them separate matters because they answer different questions. "What
happened last Tuesday" is episodic; "cocotb is not installed on this machine" is
semantic, and it should not have to be rediscovered from the log every time.

The memory persists as JSON so it survives between runs — which is the whole point
of a persistent state module, and the reason the flat heuristics can beat a clever
planner on a *cold* start and lose on a warm one.

Retrieval feeds `belief.py`: the pass rate of a result across similar past changes
becomes its prior, which is what makes value-of-information ordering different from
ranking on graph shape.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

__all__ = ["Memory"]


@dataclass
class Episode:
    changed: list[str]
    planned: list[str]
    outcomes: dict            # result -> "pass" | "fail" | other
    checks: int
    settled: int

    def similarity(self, changed) -> float:
        """Jaccard over the changed set — crude, and honest about being crude."""
        a, b = set(self.changed), set(changed)
        if not a and not b:
            return 1.0
        return len(a & b) / max(len(a | b), 1)


@dataclass
class Memory:
    """Episodic history plus semantic facts, persisted to a JSON file."""

    path: str | None = None
    episodes: list[Episode] = field(default_factory=list)
    facts: dict = field(default_factory=dict)     # semantic stream

    # ---- the two streams -------------------------------------------------
    def record(self, changed, planned, outcomes, checks: int, settled: int) -> None:
        self.episodes.append(Episode(list(changed), list(planned),
                                     dict(outcomes), checks, settled))
        for rid, outcome in outcomes.items():
            if outcome in ("pass", "fail"):
                key = f"passes:{rid}"
                p, n = self.facts.get(key, (0, 0))
                self.facts[key] = (p + (1 if outcome == "pass" else 0), n + 1)

    def remember(self, fact: str, value) -> None:
        self.facts[fact] = value

    def recall(self, fact: str, default=None):
        return self.facts.get(fact, default)

    # ---- what the belief needs -------------------------------------------
    def pass_rate(self, rid: str, similar_only=None) -> float | None:
        """Historical pass rate for a result, or None when nothing is known."""
        if similar_only is not None:
            hits = [e.outcomes[rid] for e in self.episodes
                    if rid in e.outcomes and e.similarity(similar_only) >= 0.5]
            if not hits:
                return None
            return sum(1 for h in hits if h == "pass") / len(hits)
        p, n = self.facts.get(f"passes:{rid}", (0, 0))
        return (p / n) if n else None

    def warm(self) -> bool:
        return bool(self.episodes) or bool(self.facts)

    def summary(self) -> str:
        return (f"{len(self.episodes)} episode(s), "
                f"{len(self.facts)} fact(s)"
                f"{'' if self.warm() else ' — cold, priors will be flat'}")

    # ---- persistence -----------------------------------------------------
    def save(self) -> None:
        if not self.path:
            return
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.path).write_text(json.dumps({
            "episodes": [{"changed": e.changed, "planned": e.planned,
                          "outcomes": e.outcomes, "checks": e.checks,
                          "settled": e.settled} for e in self.episodes],
            "facts": {k: list(v) if isinstance(v, tuple) else v
                      for k, v in self.facts.items()},
        }, indent=2))

    @classmethod
    def load(cls, path: str) -> "Memory":
        p = Path(path)
        if not p.exists():
            return cls(path=path)
        try:
            d = json.loads(p.read_text())
        except Exception:
            return cls(path=path)
        eps = [Episode(e["changed"], e["planned"], e["outcomes"],
                       e.get("checks", 0), e.get("settled", 0))
               for e in d.get("episodes", [])]
        facts = {}
        for k, v in (d.get("facts") or {}).items():
            facts[k] = tuple(v) if isinstance(v, list) else v
        return cls(path=path, episodes=eps, facts=facts)

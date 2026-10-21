"""An evidence record: a claim plus the witness that backs it.

A verdict cannot exist without a witness — a real artifact (log, waveform,
counterexample, report) produced by a real tool — and that witness is bound to
the exact design inputs, the exact run and the environment, so it can be
re-checked later. `repro` is the hash of all three; if it changes, the evidence
no longer describes the current design.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .repro import DesignInputs, RunSpec, digest_text, env_fingerprint, repro_hash


@dataclass
class Evidence:
    claim: str
    tool: str
    artifact: str
    digest: str
    inputs: dict = field(default_factory=dict)
    run: dict = field(default_factory=dict)
    repro: str = ""
    meta: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "claim": self.claim, "tool": self.tool, "artifact": self.artifact,
            "digest": self.digest, "inputs": self.inputs, "run": self.run,
            "repro": self.repro, "meta": self.meta,
        }

    def is_reproducible(self, inputs: DesignInputs, run: RunSpec,
                        env: dict | None = None) -> bool:
        """Does this evidence still describe the given inputs and run?"""
        return self.repro == repro_hash(inputs, run, env)


def make_evidence(claim: str, tool: str, artifact_text: str,
                  inputs: DesignInputs | None = None,
                  run: RunSpec | None = None,
                  env: dict | None = None,
                  artifact: str = "inline",
                  meta: dict | None = None) -> Evidence:
    """Build an evidence record with a fresh artifact digest and repro hash."""
    inputs = inputs or DesignInputs()
    run = run or RunSpec(tool=tool)
    env = env if env is not None else env_fingerprint()
    return Evidence(
        claim=claim,
        tool=tool,
        artifact=artifact,
        digest=digest_text(artifact_text),
        inputs=inputs.as_dict(),
        run=run.as_dict(),
        repro=repro_hash(inputs, run, env),
        meta=meta or {},
    )

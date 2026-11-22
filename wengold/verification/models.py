"""Versioned, content-addressed metadata for verification executions."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Mapping


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


@dataclass(frozen=True)
class RunManifest:
    """Reproducibility metadata; artifact truth remains in the existing ledger.

    Environment values are represented by a digest rather than copied into the
    manifest, avoiding accidental persistence of credentials or secret values.
    Input digests are sorted before hashing so caller ordering is immaterial.
    """
    tool: str
    argv: tuple[str, ...]
    source_digests: tuple[tuple[str, str], ...] = ()
    testbench_digests: tuple[tuple[str, str], ...] = ()
    config_digests: tuple[tuple[str, str], ...] = ()
    tool_version: str | None = None
    seed: int | None = None
    timeout_seconds: float | None = None
    environment_digest: str | None = None
    schema_version: int = 1
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tool.strip():
            raise ValueError("tool must be a non-empty identifier")
        if self.schema_version != 1:
            raise ValueError(f"unsupported RunManifest schema_version: {self.schema_version}")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        for field_name in ("source_digests", "testbench_digests", "config_digests"):
            pairs = getattr(self, field_name)
            if len({path for path, _digest in pairs}) != len(pairs):
                raise ValueError(f"{field_name} contains duplicate paths")
            if any(not path or not digest for path, digest in pairs):
                raise ValueError(f"{field_name} entries require non-empty path and digest")

    def as_dict(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "tool": self.tool,
            "tool_version": self.tool_version,
            "argv": list(self.argv),
            "source_digests": dict(sorted(self.source_digests)),
            "testbench_digests": dict(sorted(self.testbench_digests)),
            "config_digests": dict(sorted(self.config_digests)),
            "seed": self.seed,
            "timeout_seconds": self.timeout_seconds,
            "environment_digest": self.environment_digest,
            "metadata": dict(sorted(self.metadata.items())),
        }

    @property
    def digest(self) -> str:
        """Full SHA-256 digest of the canonical manifest."""
        return "sha256:" + hashlib.sha256(_canonical_json(self.as_dict())).hexdigest()

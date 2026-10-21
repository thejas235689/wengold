"""RTL front-end.

Wraps open parsers (Surelog / sv-parser / Verible) to extract modules, ports,
instantiations, always-blocks and signal-level references. The default backend
is a conservative regex parser so the graph builds with no external tools; plug
a real parser in via `BACKENDS`.
"""
from __future__ import annotations

import re

MODULE_RE = re.compile(r"\bmodule\s+(\w+)")
INST_RE = re.compile(r"\b(\w+)\s+(?:#\s*\([^)]*\)\s*)?(\w+)\s*\(")


def parse_modules(source: str) -> list[str]:
    return MODULE_RE.findall(source)


def parse_instantiations(source: str) -> list[tuple[str, str]]:
    """Return (module_type, instance_name) pairs. Best-effort without a real
    elaborator; use Surelog for exact results."""
    out = []
    for m in INST_RE.finditer(source):
        mod, inst = m.group(1), m.group(2)
        if mod in {"module", "always", "assign", "if", "for", "case", "wire", "reg"}:
            continue
        out.append((mod, inst))
    return out

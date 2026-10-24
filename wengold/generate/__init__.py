"""Spec-driven generation: spec -> SystemVerilog -> conformance check.

The pipeline is deliberately closed. A spec is read and validated
(`spec.py`), SystemVerilog is emitted (`emit.py`), and the emitted code is then
re-read and checked against the spec (`conform.py`). Generation alone is not
treated as correctness: what makes the output trustworthy is that the artifact is
verified against the thing it claims to implement.
"""
from .conform import Check, Report, check            # noqa: F401
from .emit import emit_map, emit_props, emit_rtl     # noqa: F401
from .spec import SpecError, ModuleSpec, load_spec   # noqa: F401

__all__ = ["load_spec", "ModuleSpec", "SpecError", "emit_rtl", "emit_props",
           "emit_map", "check", "Report", "Check"]

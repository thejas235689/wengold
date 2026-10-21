"""Typed dependencies and reassessment rules.

Not every dependency is the same, and a change of one type must not be treated
like a change of another. A comment edit is a compilation dependency; a parameter
change is a configuration dependency that only affects the results whose scope
includes that parameter; an assumption change invalidates everything that leaned
on it, even though the RTL never moved.

This module classifies each graph edge into a `DependencyType` and states the
reassessment rule for a change of that type.
"""
from __future__ import annotations

from enum import Enum

from ..graph.model import DesignGraph, EdgeKind


class DependencyType(str, Enum):
    COMPILATION = "compilation"        # source text / include structure
    ELABORATION = "elaboration"        # packages, generate, parameter binding
    BEHAVIORAL = "behavioral"          # actual logic behaviour
    ASSUMPTION = "assumption"          # a condition the result leans on
    CONFIGURATION = "configuration"    # parameters, defines, features
    REQUIREMENT = "requirement"        # what the design must do


_EDGE_TO_DEP = {
    EdgeKind.DEFINED_IN: DependencyType.COMPILATION,
    EdgeKind.INCLUDES: DependencyType.COMPILATION,
    EdgeKind.IMPORTS: DependencyType.ELABORATION,
    EdgeKind.GENERATES: DependencyType.ELABORATION,
    EdgeKind.PARAMETERIZES: DependencyType.CONFIGURATION,
    EdgeKind.INSTANTIATES: DependencyType.BEHAVIORAL,
    EdgeKind.DRIVES: DependencyType.BEHAVIORAL,
    EdgeKind.CLOCKED_BY: DependencyType.BEHAVIORAL,
    EdgeKind.RESET_BY: DependencyType.BEHAVIORAL,
    EdgeKind.CROSSES: DependencyType.BEHAVIORAL,
    EdgeKind.VERIFIES: DependencyType.BEHAVIORAL,
    EdgeKind.COVERS: DependencyType.BEHAVIORAL,
    EdgeKind.CONSTRAINED_BY: DependencyType.ASSUMPTION,
    EdgeKind.ASSUMES: DependencyType.ASSUMPTION,
    EdgeKind.GUARANTEES: DependencyType.ASSUMPTION,
    EdgeKind.TRACES_TO: DependencyType.REQUIREMENT,
    EdgeKind.UNKNOWN: DependencyType.BEHAVIORAL,
}

_RULES = {
    DependencyType.COMPILATION:
        "Recompile; a text/include change does not alter behaviour but must be re-read.",
    DependencyType.ELABORATION:
        "Re-elaborate; package, generate or parameter binding may change the netlist.",
    DependencyType.BEHAVIORAL:
        "Re-run; the logic may have changed, so every result that exercises it is in doubt.",
    DependencyType.ASSUMPTION:
        "Invalidate every result that leaned on the assumption, even if the RTL is unchanged.",
    DependencyType.CONFIGURATION:
        "Invalidate only results whose scope includes the changed parameter/define/feature.",
    DependencyType.REQUIREMENT:
        "Invalidate every conclusion traced to the requirement, even if the RTL is unchanged.",
}


def dep_type(edge) -> DependencyType:
    return _EDGE_TO_DEP.get(edge.kind, DependencyType.BEHAVIORAL)


def reassessment_rule(dtype: DependencyType) -> str:
    return _RULES[dtype]


def typed_ancestors(graph: DesignGraph, deps: set[str],
                    types: set[DependencyType]) -> set[str]:
    """Upstream closure of `deps`, following only edges of the given types."""
    seen: set[str] = set()
    stack = list(deps)
    while stack:
        cur = stack.pop()
        for e in graph.in_edges(cur):
            if dep_type(e) in types and e.src not in seen:
                seen.add(e.src)
                stack.append(e.src)
    return seen


def config_scope_affected(result, changed_config_keys: set[str]) -> bool:
    """Does a configuration change of these keys touch the result's scope?

    A result with no recorded configuration is *not* assumed to be unaffected —
    callers treat that as UNKNOWN, not as VALID.
    """
    cfg = {}
    if getattr(result, "contract", None) is not None:
        cfg = result.contract.config()
    if not cfg:
        return True                      # unknown scope: assume it could be affected
    return bool(set(cfg) & changed_config_keys)


def change_impact(graph: DesignGraph, changed: set[str],
                  changed_config_keys: set[str] | None = None) -> dict:
    """Summarise what kinds of change the delta contains, and the rule for each."""
    kinds: dict[str, list[str]] = {}
    for e in graph.edges:
        if e.src in changed or e.dst in changed:
            kinds.setdefault(dep_type(e).value, []).append(f"{e.src}->{e.dst}")
    if changed_config_keys:
        kinds.setdefault(DependencyType.CONFIGURATION.value, []).extend(sorted(changed_config_keys))
    return {k: {"nodes": sorted(set(v)), "rule": reassessment_rule(DependencyType(k))}
            for k, v in kinds.items()}

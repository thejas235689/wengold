# Contributing to WENGOLD

Thanks for helping build open silicon verification.

- **Tool adapters** are the easiest first contribution. Add a `ToolSpec` and a
  thin `ToolAdapter` under `wengold/tools/adapters/`, register it in
  `wengold/tools/registry.py`, and add a test in the matching `tests/test_*.py`
  group.
- **Kernel rules** (how a change propagates across the graph) live in
  `wengold/kernel/`. Every rule needs a property test.
- **Agents** live in `wengold/agents/`. No agent may write to the design; agents
  propose, the kernel and the tools decide.

Run the suite with `pytest -q`. Please keep the three tool groups
(simulation / formal / flow) green.

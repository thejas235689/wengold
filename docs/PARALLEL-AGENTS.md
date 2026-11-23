# Parallel agent execution

The ParallelAgentRunner executes independent agent tasks concurrently with a
bounded worker pool and an explicit dependency graph.

Each task has a stable ID, role, prompt, priority and optional dependencies.
An agent receives only the outputs named in its dependency list. Failed
dependencies block dependants, while unrelated tasks continue. Results are
returned in input order.

The scheduler is backend-neutral. It can submit work to a shared inference
client, but the backend decides whether requests are batched or serialized.
The current Kimi K3 command-line adapter starts a subprocess per request and
is not a persistent worker. Do not claim model weights are shared until a
long-lived runtime is implemented and verified on target hardware.

Parallel agent outputs remain advisory. They do not modify RTL, run EDA,
establish formal proof, credit coverage or grant signoff. The existing
WENGOLD graph, validity kernel and evidence ledger remain authoritative.

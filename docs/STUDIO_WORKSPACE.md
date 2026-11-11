# Silicon Studio engineering workspaces

Launch the local desktop:

```bash
sh wengold.sh desktop ./your-rtl-project
```

The **RTL Editor** opens HDL files from the indexed project. Saving writes only an
existing source file inside the project root, requires a session token, and rejects
changes if its SHA-256 has changed since it was opened. A save does **not** imply
that the old dependency graph, verification verdicts, or coverage conclusions
remain valid. Restart the desktop after saving to rebuild the graph, then rerun
affected checks.

The **Waveforms** tab reads simulation VCD files (up to 8 MB) from project
subfolders named `waves/`, `waveforms/`, `sim/`, `results/`,
`formal-results/`, or `reports/`. It displays up to 48 signals and 600
sample timestamps, and distinguishes unknown values instead of displaying a
fabricated zero. The viewer is a compact signal plot, not a replacement for
GTKWave or a full waveform debugger.

The **Formal Results** tab displays JSON artifacts (up to 2 MB) in those
directories. These are imported reports, not claims independently proven by
WENGOLD. Tool provenance, property assumptions, depth, and solver status must be
checked before accepting any result. Reports are never silently classified PASS.

The **Agent Orchestration** tab presents the existing graph-based analysis
steps and recommendations. Clicking **Inspect agent plan** does not run
simulation, invoke an LLM, apply patches, or sign off verification. Use the
existing CLI and verified tool adapters for actual checks.

All new endpoints are loopback-only, respect the project root, reject unsupported
file extensions, and expose no arbitrary shell command execution.

## Verification

```bash
python3 -m pytest tests/test_studio_workspace.py tests/test_desktop.py tests/test_wave.py
```

Any output from the CI workflow is authoritative for test success. A committed UI
does not itself prove rendering or tool integration has passed testing.


## Milestone: executable checks and local evidence review

The yellow/white Silicon Studio adds four bounded execution capabilities:

- Syntax Diagnostics queues a real pyslang parse of the selected saved RTL source. Missing pyslang is reported as unavailable, never clean.
- Run Formal executes WENGOLD's existing limited in-process proof engine on a selected indexed RTL file and user-supplied safety expression. Explicit-state depth is limited to 1–20 and the state budget to 5,000. Unsupported RTL yields unknown, not proof.
- Run Syntax → Formal Pipeline executes syntax first and only proceeds if syntax is clean, recording each stage in the local ledger.
- Cross-Probe RTL finds whole-token references in indexed HDL files. The search is lexical, not resolved hierarchical signal ownership.

Refresh Jobs lists actual queued, running and completed checks for this desktop session. A single local worker serializes jobs. It is not a durable distributed multi-agent job manager; queued jobs are lost at desktop shutdown.

Accept Proof or Reject Evidence creates an immutable reviewer-entered ledger record. Accept requires a completed current formal proof, matching source hash, and a clean ledger audit. Bounded, unknown, failed, stale or missing results cannot be accepted.

Records live in the project-local .wengold-studio-ledger.jsonl hash-chained ledger. Source and result SHA-256 digests bind run evidence to an artifact snapshot. Audit checks the local chain but cannot authenticate a human or protect against an attacker replacing the entire ledger and checkpoint.

Reviewer identity is free text and NOT AUTHENTICATED. An evidence review record is not independent tapeout signoff. Formal coverage completeness, tool qualification, privileged approval, external evidence retention and authenticated identity are future work.

Run: python3 -m pytest -q tests/test_studio_milestone.py tests/test_studio_workspace.py

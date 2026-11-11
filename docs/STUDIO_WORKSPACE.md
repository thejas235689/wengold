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

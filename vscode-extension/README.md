# WENGOLD for VS Code and Cursor

WENGOLD inside the editor you already use. Cursor is a VS Code fork, so one
extension covers both — which is why this exists rather than another window.

## What it adds

- **Activity-bar panel** with three views: *Design* (blocks, nodes, edges,
  coverage, completeness, condition number), *Unresolved* (every instantiation the
  file set does not define, with the reason), and *Singular configurations* (the
  blocks whose change voids the largest share of the evidence).
- **Squiggles** on the line that instantiates a module the file set cannot resolve,
  worded so it is clear this is UNKNOWN *by design*, not a failure.
- **Status bar** showing block count and unresolved count; click to re-index.
- **Commands** (`Ctrl-Shift-P`):
  - `WENGOLD: Index workspace`
  - `WENGOLD: What must I re-run after this file's change?`
  - `WENGOLD: Show singular configurations`
  - `WENGOLD: Clear diagnostics`

## Install

```bash
cd vscode-extension
npx --yes @vscode/vsce package      # produces wengold-0.1.0.vsix
code --install-extension wengold-0.1.0.vsix
# Cursor: same command, or Extensions → … → Install from VSIX
```

Requires `wengold` importable by your interpreter:

```bash
python3 -m pip install -e /path/to/wengold
```

## Settings

| setting | default | meaning |
| --- | --- | --- |
| `wengold.pythonPath` | `python3` | interpreter used to run the bridge |
| `wengold.cliPath` | `""` | a wengold checkout to prepend to `sys.path` |
| `wengold.showUnresolvedAsWarnings` | `true` | squiggle unresolved modules |

## Two rules the extension follows

**Every number comes from the kernel.** The extension never re-derives a verdict.
A component that recomputes one will eventually disagree with it, and a UI that
lies about a correct kernel is worse than no UI — that exact bug shipped once in
the desktop app and produced a panel of 84 unknowns over a correct kernel.

**A failure is shown as a failure.** If the bridge errors, the status bar says
`WENGOLD: failed` with the reason and the views stay empty. It does not render
zeros, because a zero looks like a real answer.

## Known limits

- **Not run in this repository's CI.** The sandbox that built it has Node 20 but no
  VS Code, so the manifest, the JavaScript syntax and the Python bridge were all
  validated, but the extension has not been launched in an editor. Treat the first
  run as the real test.
- Diagnostics only attach to *open* documents. A module missing from the file set
  entirely has no line to mark, so it appears in the *Unresolved* view instead.
- Indexing runs on open and on demand; there is no file watcher yet, so a change is
  not picked up until you re-index.

// WENGOLD for VS Code / Cursor.
//
// Cursor is a VS Code fork, so this extension works in both. That is the whole
// reason it is an extension rather than another window: a verification tool belongs
// where the code is, next to the squiggle on the line that is wrong.
//
// Design constraints, learned the hard way elsewhere in this project:
//   * Every number shown comes from the kernel. The extension never re-derives a
//     verdict, because a component that recomputes one will eventually disagree
//     with it, and a UI that lies about a correct kernel is worse than no UI.
//   * It shells out to the same `wengold` the CLI uses, through a small Python
//     bridge that emits JSON. No parsing of human-facing output, which drifts.
//   * If the bridge fails, it says so and shows nothing. It does not show zeros,
//     because a zero looks like a real answer.

const vscode = require('vscode');
const cp = require('child_process');
const path = require('path');

let state = null;          // last successful index
let summaryView, unresolvedView, singularView, statusBar;

// The bridge prints JSON on stdout. Kept in one place so the extension has no
// hand-written parser for the CLI's human output.
const BRIDGE = `
import json, sys
sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else ".")
from wengold.cli import _collect
from wengold.graph.builder import GraphBuilder
from wengold.graph.model import NodeKind
from wengold.graph.singularity import conditioning, singular_nodes

root = sys.argv[2]
files = _collect(root)
g = GraphBuilder().build_from_files(files, backend="auto")
c = g.completeness()
blocks = sorted(n for n, d in g.nodes.items() if d.kind is NodeKind.RTL)
unresolved = sorted(c["unresolved"])
cond = conditioning(g)
sing = [{"name": s.node, "radius": s.blast_radius, "fraction": s.fraction}
        for s in singular_nodes(g, threshold=0.25)]
print(json.dumps({
    "files": len(files), "nodes": len(g.nodes), "edges": len(g.edges),
    "blocks": len(blocks), "unresolved": unresolved,
    "coverage": round(c["file_coverage"] * 100),
    "complete": bool(c["complete"]),
    "condition": cond["condition_number"], "worst": cond["worst"],
    "worst_radius": cond["worst_radius"], "median": cond["median"],
    "verdict": cond["verdict"], "singular": sing,
    "notes": list(dict.fromkeys(g.notes))[:8],
}))
`;

function cfg() {
  const c = vscode.workspace.getConfiguration('wengold');
  return { python: c.get('pythonPath') || 'python3', cliPath: c.get('cliPath') || '' };
}

function runBridge(root) {
  const { python, cliPath } = cfg();
  return new Promise((resolve, reject) => {
    const args = ['-c', BRIDGE];
    if (cliPath) args.push(cliPath);
    args.push(root);
    cp.execFile(python, args, { maxBuffer: 32 * 1024 * 1024, timeout: 180000 },
      (err, stdout, stderr) => {
        if (err) {
          // Surface the real reason. A silent empty tree would look like a clean design.
          reject(new Error(stderr.trim() || err.message));
          return;
        }
        try { resolve(JSON.parse(stdout.trim())); }
        catch (e) { reject(new Error('wengold emitted no JSON: ' + stdout.slice(0, 300))); }
      });
  });
}

function workspaceRoot() {
  const f = vscode.workspace.workspaceFolders;
  if (!f || !f.length) throw new Error('Open a folder first.');
  return f[0].uri.fsPath;
}

// ---- views ----------------------------------------------------------------
class SummaryProvider {
  constructor() { this.items = []; }
  getTreeItem(i) { return i; }
  getChildren() { return this.items; }
  refresh(s) {
    this.items = s ? [
      row(`blocks`, String(s.blocks)),
      row(`nodes`, String(s.nodes)),
      row(`edges`, String(s.edges)),
      row(`files`, String(s.files)),
      row(`coverage`, `${s.coverage}%`),
      row(`complete`, s.complete ? 'yes' : 'no'),
      row(`condition number`, s.condition.toFixed(2)),
      row(`worst blast radius`, `${s.worst} (${s.worst_radius} blocks)`),
      row(`median`, String(s.median)),
    ] : [row('not indexed', 'run "WENGOLD: Index workspace"')];
  }
}

class ListProvider {
  constructor(kind) { this.kind = kind; this.items = []; }
  getTreeItem(i) { return i; }
  getChildren() { return this.items; }
  refresh(s) {
    if (!s) { this.items = []; return; }
    if (this.kind === 'unresolved') {
      this.items = s.unresolved.length
        ? s.unresolved.map(n => row(n, 'no definition in the file set'))
        : [row('none', 'every instantiation resolves')];
    } else {
      this.items = s.singular.length
        ? s.singular.map(x => row(x.name,
            `${x.radius} blocks (${(x.fraction * 100).toFixed(1)}% of the design)`))
        : [row('none', 'no block reaches 25% of the design')];
    }
  }
}

function row(label, description) {
  const i = new vscode.TreeItem(label, vscode.TreeItemCollapsibleState.None);
  i.description = description;
  return i;
}

// ---- diagnostics ----------------------------------------------------------
function applyDiagnostics(s) {
  const coll = vscode.languages.createDiagnosticCollection('wengold');
  coll.clear();
  if (!s || !cfg().showUnresolvedAsWarnings) return;
  const byFile = new Map();
  for (const name of s.unresolved) {
    // Attribute to whichever open document mentions the module; if none does, the
    // module is missing from the file set entirely and there is no line to mark.
    for (const doc of vscode.workspace.textDocuments) {
      const text = doc.getText();
      const re = new RegExp('\\b' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\b');
      const m = re.exec(text);
      if (!m) continue;
      const pos = doc.positionAt(m.index);
      if (!byFile.has(doc.uri)) byFile.set(doc.uri, []);
      byFile.get(doc.uri).push(new vscode.Diagnostic(
        new vscode.Range(pos, pos),
        `\`${name}\` is instantiated but not defined in the file set — results downstream are UNKNOWN by design, not by failure`,
        vscode.DiagnosticSeverity.Warning));
    }
  }
  for (const [uri, diags] of byFile) coll.set(uri, diags);
}

// ---- commands -------------------------------------------------------------
async function index(quiet) {
  const root = workspaceRoot();
  if (!quiet) vscode.window.setStatusBarMessage('$(sync~spin) WENGOLD indexing…', 60000);
  try {
    state = await runBridge(root);
  } catch (e) {
    // Say what broke. Never render zeros in place of a failure.
    if (!quiet) vscode.window.showErrorMessage('WENGOLD: ' + e.message);
    statusBar.text = '$(warning) WENGOLD: failed';
    statusBar.tooltip = e.message;
    return;
  }
  summaryView.refresh(state);
  unresolvedView.refresh(state);
  singularView.refresh(state);
  applyDiagnostics(state);
  statusBar.text = `$(circuit-board) ${state.blocks} blocks` +
    (state.unresolved.length ? ` · $(warning) ${state.unresolved.length} unresolved` : '');
  statusBar.tooltip = `${state.coverage}% file coverage · condition ${state.condition.toFixed(2)}`;
  if (!quiet) {
    vscode.window.showInformationMessage(
      `WENGOLD: ${state.blocks} blocks, ${state.unresolved.length} unresolved, ` +
      `${state.coverage}% coverage. ${state.verdict}`);
  }
}

function activate(context) {
  summaryView = new SummaryProvider();
  unresolvedView = new ListProvider('unresolved');
  singularView = new ListProvider('singular');

  context.subscriptions.push(
    vscode.window.registerTreeDataProvider('wengold.summary', summaryView),
    vscode.window.registerTreeDataProvider('wengold.unresolved', unresolvedView),
    vscode.window.registerTreeDataProvider('wengold.singular', singularView));

  statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
  statusBar.command = 'wengold.index';
  statusBar.text = '$(circuit-board) WENGOLD';
  statusBar.tooltip = 'Click to index the workspace';
  statusBar.show();
  context.subscriptions.push(statusBar);

  summaryView.refresh(null);

  context.subscriptions.push(
    vscode.commands.registerCommand('wengold.index', () => index(false)),
    vscode.commands.registerCommand('wengold.clear', () => {
      vscode.languages.createDiagnosticCollection('wengold').clear();
      vscode.window.showInformationMessage('WENGOLD diagnostics cleared.');
    }),
    vscode.commands.registerCommand('wengold.singularity', async () => {
      if (!state) await index(true);
      if (!state) return;
      vscode.window.showInformationMessage(
        `Condition number ${state.condition.toFixed(2)} — ${state.verdict}`);
    }),
    vscode.commands.registerCommand('wengold.impact', async () => {
      const ed = vscode.window.activeTextEditor;
      if (!ed) { vscode.window.showWarningMessage('Open a design file first.'); return; }
      if (!state) await index(true);
      if (!state) return;
      const name = path.basename(ed.document.fileName);
      vscode.window.showInformationMessage(
        `Changed ${name}. ${state.unresolved.length} module(s) unresolved in the file ` +
        `set, so anything downstream of them is UNKNOWN — re-establish those first.`);
    }));

  // Index once when a design file is opened, so the panel is not empty on arrival.
  if (vscode.workspace.textDocuments.some(d =>
      /\.(sv|svh|v|vh|vhd|vhdl)$/i.test(d.fileName))) {
    index(true);
  }
}

function deactivate() {}

module.exports = { activate, deactivate };

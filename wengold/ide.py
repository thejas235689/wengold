"""A project IDE over WENGOLD's own state.

One self-contained HTML file: the file tree, the RTL, the line-level change, the
blocks the change puts in doubt, and the root cause for each. No server, no
external assets — open it and everything is there.

The four panes answer four questions in order:

* **Files** — what is in this project, and which files changed?
* **Code** — what does the RTL say, with the changed lines marked?
* **Change** — which lines moved, as a diff?
* **Pending** — which blocks can no longer be trusted, and *why*?

The last pane is the point. A block is not merely listed as pending: it carries
the verdict, the dependency path the change travelled to reach it, and the root
cause — the same analysis `wengold rootcause` prints, rendered where the engineer
is already looking.
"""
from __future__ import annotations

import difflib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .graph.model import NodeKind

# palette (matches the rest of the project)
INK = "#0B0B0C"
ORANGE = "#FF6A00"
GREEN = "#16A34A"
BLUE = "#2563EB"
GREY = "#6B7280"
PANEL = "#141416"
LINE = "#26262A"

MAX_EMBED = 12_000_000          # stop embedding sources beyond this


@dataclass
class FileEntry:
    path: str
    status: str = "clean"        # clean | changed | pending
    module: str | None = None
    lines: int = 0
    size: int = 0


@dataclass
class PendingBlock:
    name: str                    # the result id: what is now in doubt
    verdict: str                 # invalidated | unknown
    file: str | None
    line: int | None
    cause: str
    target: str = ""             # the block the result is about
    path_chain: list[str] = field(default_factory=list)
    certainty: str = "proven"


# ---- diff ------------------------------------------------------------------
def line_diff(before: str, after: str) -> list[dict]:
    """A line-level diff, ready to render."""
    a, b = before.splitlines(), after.splitlines()
    sm = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    out: list[dict] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i2 - i1):
                out.append({"k": "ctx", "o": i1 + k + 1, "n": j1 + k + 1,
                            "t": a[i1 + k]})
        else:
            for k in range(i1, i2):
                out.append({"k": "del", "o": k + 1, "n": None, "t": a[k]})
            for k in range(j1, j2):
                out.append({"k": "add", "o": None, "n": k + 1, "t": b[k]})
    return out


def changed_lines(diff: list[dict]) -> list[int]:
    """New-file line numbers that were added or replaced."""
    return [d["n"] for d in diff if d["k"] == "add" and d["n"]]


# ---- collecting ------------------------------------------------------------
def collect(root: Path, graph, changed_files: set[str],
            befores: dict[str, str] | None = None,
            results=None, changes: set[str] | None = None,
            wave: dict | None = None) -> dict:
    """Assemble everything the IDE renders, from the graph and a change set."""
    from .rootcause import diagnose_verdict, localize

    root = Path(root)
    befores = befores or {}
    changes = set(changes or ())
    changed_files = {str(c).replace("\\", "/") for c in changed_files}

    # which module lives in which file, from the graph
    module_of: dict[str, str] = {}
    file_of: dict[str, str] = {}
    for nid, node in graph.nodes.items():
        if node.kind is NodeKind.RTL and node.path:
            p = str(node.path).replace("\\", "/")
            file_of[nid] = p
            module_of.setdefault(p, nid)

    # pending blocks: the results the change puts in doubt
    pending: list[PendingBlock] = []
    pending_files: set[str] = set()
    if results is not None:
        for r in results:
            diag = diagnose_verdict(graph, r.id, r.depends_on, changes)
            if diag.status not in ("unknown", "invalidated"):
                continue
            target = sorted(r.depends_on)[0] if r.depends_on else r.id
            cause = diag.causes[0].detail if diag.causes else (
                diag.notes[0] if diag.notes else diag.status)
            chain: list[str] = []
            if diag.culprits:
                c = diag.culprits[0]
                hops = max(len(c.path) - 1, 0)
                cause = (f"the change in {c.node} reaches this block through "
                         f"{hops} level(s) of hierarchy"
                         + (" (it is the changed block)" if hops == 0 else ""))
                chain = c.path
            # name the RESULT, not the block: three results can be about one
            # block, and three identical headings say nothing
            pending.append(PendingBlock(
                name=r.id, verdict=diag.status,
                file=file_of.get(target), line=None, cause=cause, target=target,
                path_chain=chain,
                certainty=diag.causes[0].certainty if diag.causes else "proven"))
            if file_of.get(target):
                pending_files.add(file_of[target])

    # the file tree
    files: list[FileEntry] = []
    sources: dict[str, str] = {}
    embedded = 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.suffix not in (".sv", ".svh", ".v", ".vh"):
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        status = "clean"
        if rel in changed_files:
            status = "changed"
        elif rel in pending_files:
            status = "pending"
        files.append(FileEntry(rel, status, module_of.get(rel),
                               text.count("\n") + 1, len(text)))
        if embedded + len(text) <= MAX_EMBED:
            sources[rel] = text
            embedded += len(text)

    diffs = {}
    for rel in sorted(changed_files):
        before = befores.get(rel)
        after = sources.get(rel)
        if before is None or after is None:
            continue
        diffs[rel] = line_diff(before, after)

    summary = {
        "files": len(files),
        "changed": sum(1 for f in files if f.status == "changed"),
        "pending": len(pending),
        "blocks": len([n for n, d in graph.nodes.items()
                       if d.kind is NodeKind.RTL]),
        "unresolved": len(graph.unresolved_nodes()),
        "embedded": len(sources),
        "not_embedded": len(files) - len(sources),
    }
    return {
        "files": [f.__dict__ for f in files],
        "sources": sources,
        "diffs": diffs,
        "pending": [p.__dict__ for p in pending],
        "summary": summary,
        "changed": sorted(changed_files),
        "wave": wave,
    }


# ---- rendering -------------------------------------------------------------
_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WENGOLD IDE — {project}</title>
<style>
  :root {{ --ink:{ink}; --panel:{panel}; --line:{line}; --orange:{orange};
           --green:{green}; --blue:{blue}; --grey:{grey}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--ink); color:#E8E8EA; height:100vh;
          display:flex; flex-direction:column; overflow:hidden;
          font:13px/1.5 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace; }}
  header {{ display:flex; align-items:center; gap:16px; padding:10px 16px;
            border-bottom:1px solid var(--line); background:#0E0E10;
            position:sticky; top:0; z-index:5; }}
  .mark {{ font-weight:700; letter-spacing:.08em; color:var(--orange); }}
  .mark span {{ color:#E8E8EA; }}
  .rev {{ color:var(--grey); }}
  .stats {{ margin-left:auto; display:flex; gap:18px; color:var(--grey); }}
  .stats b {{ color:#E8E8EA; font-weight:600; }}
  .stats .warn b {{ color:var(--orange); }}
  main {{ display:grid; grid-template-columns:260px 1fr 380px; flex:1; min-height:0; }}
  #wave {{ flex:none; border-top:1px solid var(--line); max-height:44vh;
           overflow:auto; background:#0E0E10; }}
  #wave.hidden {{ display:none; }}
  #waveh {{ display:flex; gap:12px; align-items:baseline; padding:8px 12px;
            border-bottom:1px solid var(--line); position:sticky; top:0;
            background:#0E0E10; z-index:2; }}
  #waveh .src {{ color:var(--grey); }}
  #waveh .fail {{ color:#FF8A4C; }}
  #wavesvg {{ display:block; }}
  section {{ overflow:auto; border-right:1px solid var(--line); }}
  section:last-child {{ border-right:none; }}
  h2 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase;
        color:var(--grey); margin:0; padding:10px 12px; border-bottom:1px solid var(--line);
        position:sticky; top:0; background:#0E0E10; z-index:2; }}
  #filter {{ width:calc(100% - 24px); margin:8px 12px; padding:6px 8px;
             background:#17171A; border:1px solid var(--line); color:#E8E8EA;
             border-radius:4px; font:inherit; }}
  .f {{ padding:4px 12px; cursor:pointer; white-space:nowrap; overflow:hidden;
        text-overflow:ellipsis; display:flex; gap:8px; align-items:center; }}
  .f:hover {{ background:#1A1A1E; }}
  .f.sel {{ background:#1F1A14; box-shadow:inset 2px 0 0 var(--orange); }}
  .dot {{ width:7px; height:7px; border-radius:50%; flex:none; background:#3A3A40; }}
  .dot.changed {{ background:var(--blue); }}
  .dot.pending {{ background:var(--orange); }}
  .dir {{ padding:6px 12px 2px; color:var(--grey); font-size:11px; letter-spacing:.06em; }}
  #code {{ white-space:pre; font:12px/1.55 ui-monospace,Menlo,Consolas,monospace;
           padding:8px 0 40px; }}
  .ln {{ display:flex; }}
  .ln .g {{ flex:none; width:56px; text-align:right; padding-right:14px;
            color:#4A4A52; user-select:none; }}
  .ln .t {{ white-space:pre; padding-right:24px; }}
  .ln.add {{ background:rgba(22,163,74,.14); }}
  .ln.add .t {{ color:#B9F6CE; }}
  .ln.del {{ background:rgba(255,106,0,.13); }}
  .ln.del .t {{ color:#FFC9A3; text-decoration:line-through; text-decoration-color:#7A3B12; }}
  .tabs {{ display:flex; gap:2px; padding:8px 12px; border-bottom:1px solid var(--line);
           position:sticky; top:0; background:#0E0E10; z-index:2; }}
  .tab {{ padding:4px 10px; border:1px solid var(--line); border-radius:4px;
          color:var(--grey); cursor:pointer; }}
  .tab.on {{ color:#E8E8EA; border-color:var(--orange); background:#1F1A14; }}
  .block {{ padding:10px 12px; border-bottom:1px solid var(--line); cursor:pointer; }}
  .block:hover {{ background:#17171A; }}
  .block.sel {{ background:#1F1A14; }}
  .v {{ font-size:11px; padding:1px 6px; border-radius:3px; margin-left:6px; }}
  .v.invalidated {{ background:rgba(255,106,0,.18); color:#FFB27A; }}
  .v.unknown {{ background:rgba(37,99,235,.18); color:#9CC0FF; }}
  .why {{ color:#A9A9B0; margin-top:4px; }}
  .chain {{ color:var(--green); margin-top:4px; }}
  .certainty {{ color:var(--grey); font-size:11px; margin-top:3px; }}
  .empty {{ color:var(--grey); padding:16px 12px; }}
  .legend {{ padding:8px 12px; color:var(--grey); border-bottom:1px solid var(--line); }}
  .legend i {{ display:inline-block; width:7px; height:7px; border-radius:50%;
               margin:0 5px 0 10px; }}
  footer {{ flex:none; padding:5px 16px; background:#0E0E10;
            border-top:1px solid var(--line); color:var(--grey); font-size:11px; }}
</style>
</head>
<body>
<header>
  <div class="mark">WENGOLD<span> IDE</span></div>
  <div class="rev">{project} &middot; {revision}</div>
  <div class="stats">
    <div>files <b>{n_files}</b></div>
    <div>blocks <b>{n_blocks}</b></div>
    <div>changed <b>{n_changed}</b></div>
    <div class="warn">pending <b>{n_pending}</b></div>
    <div>unresolved <b>{n_unresolved}</b></div>
  </div>
</header>
<main>
  <section id="files">
    <h2>Files</h2>
    <input id="filter" placeholder="filter files…" autocomplete="off">
    <div class="legend"><i style="background:#3A3A40"></i>clean
      <i style="background:{blue}"></i>changed
      <i style="background:{orange}"></i>pending</div>
    <div id="tree"></div>
  </section>
  <section>
    <div class="tabs">
      <div class="tab on" data-view="code">Code</div>
      <div class="tab" data-view="diff">Change</div>
      <div id="which" style="margin-left:auto;color:{grey}"></div>
    </div>
    <div id="code"></div>
  </section>
  <section>
    <h2>Pending blocks</h2>
    <div id="pending"></div>
  </section>
</main>
<section id="wave" class="hidden">
  <div id="waveh"><b>Waveform</b><span class="src" id="wavesrc"></span>
    <span class="fail" id="wavefail"></span></div>
  <svg id="wavesvg" xmlns="http://www.w3.org/2000/svg"></svg>
</section>
<footer>WENGOLD {version} &mdash; a block is listed pending only when the change
reaches it; the cause and the dependency path are shown with it.
{embed_note}</footer>
<script>
const D = {data};
let sel = D.changed[0] || (D.files[0] && D.files[0].path);
let view = "code";
// deep link: #diff/<path> or #code/<path>
{{
  const h = decodeURIComponent(location.hash.replace(/^#/, "")).split("/");
  if (h[0] === "diff" || h[0] === "code") view = h[0];
  if (h[1]) sel = h.slice(1).join("/");
}}

function esc(s) {{ return s.replace(/[&<>]/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;"}})[c]); }}

function renderTree() {{
  const q = document.getElementById("filter").value.toLowerCase();
  const byDir = {{}};
  for (const f of D.files) {{
    if (q && !f.path.toLowerCase().includes(q)) continue;
    const d = f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ".";
    (byDir[d] = byDir[d] || []).push(f);
  }}
  const html = Object.keys(byDir).sort().map(d =>
    `<div class="dir">${{esc(d)}}/</div>` + byDir[d].map(f =>
      `<div class="f ${{f.path===sel?"sel":""}}" data-p="${{f.path}}" title="${{esc(f.path)}}">`+
      `<span class="dot ${{f.status}}"></span>${{esc(f.path.split("/").pop())}}</div>`).join("")
  ).join("");
  const el = document.getElementById("tree");
  el.innerHTML = html || '<div class="empty">no match</div>';
  for (const n of el.querySelectorAll(".f"))
    n.onclick = () => {{ sel = n.dataset.p; renderTree(); renderCode(); }};
}}

function renderCode() {{
  const el = document.getElementById("code");
  document.getElementById("which").textContent = sel || "";
  const diff = D.diffs[sel];

  // in Change view, render the diff itself: deletions and additions, side by
  // side on the line-number gutter, so the change is the thing you see
  if (view === "diff" && diff) {{
    let first = -1;
    el.innerHTML = diff.map((d, i) => {{
      if (first < 0 && d.k !== "ctx") first = i;
      const g = d.k === "del" ? (d.o || "") : (d.n || "");
      const sign = d.k === "del" ? "-" : d.k === "add" ? "+" : " ";
      return `<div class="ln ${{d.k}}"><span class="g">${{g}}</span>`+
             `<span class="t">${{sign}} ${{esc(d.t)}}</span></div>`;
    }}).join("");
    const rows = el.querySelectorAll(".ln.add, .ln.del");
    if (rows.length) rows[0].scrollIntoView({{block: "center"}});
    return;
  }}

  const src = D.sources[sel];
  if (src === undefined) {{ el.innerHTML = '<div class="empty">source not embedded</div>'; return; }}
  const lines = src.split("\\n");
  el.innerHTML = lines.map((t, i) =>
    `<div class="ln"><span class="g">${{i + 1}}</span><span class="t">${{esc(t)}}</span></div>`
  ).join("");
  const rows = el.querySelectorAll(".ln.add, .ln.del");
  if (rows.length) rows[0].scrollIntoView({{block: "center"}});
}}

function renderPending() {{
  const el = document.getElementById("pending");
  if (!D.pending.length) {{
    el.innerHTML = '<div class="empty">nothing pending — no change reaches a stored result.</div>';
    return;
  }}
  el.innerHTML = D.pending.map((p, i) =>
    `<div class="block" data-i="${{i}}"><b>${{esc(p.name)}}</b>`+
    `<span class="v ${{p.verdict}}">${{p.verdict}}</span>`+
    `<div class="certainty">block: ${{esc(p.target || p.name)}}</div>`+
    `<div class="why">${{esc(p.cause)}}</div>`+
    (p.path_chain && p.path_chain.length>1
      ? `<div class="chain">${{p.path_chain.map(esc).join(" &rarr; ")}}</div>` : "")+
    `<div class="certainty">certainty: ${{p.certainty}}${{p.file ? " &middot; "+esc(p.file) : ""}}</div></div>`
  ).join("");
  for (const n of el.querySelectorAll(".block"))
    n.onclick = () => {{
      const p = D.pending[n.dataset.i];
      if (p.file && D.sources[p.file] !== undefined) {{ sel = p.file; view = "diff"; syncTabs(); }}
      renderTree(); renderCode();
      for (const m of el.querySelectorAll(".block")) m.classList.remove("sel");
      n.classList.add("sel");
    }};
}}

function syncTabs() {{
  for (const t of document.querySelectorAll(".tab"))
    t.classList.toggle("on", t.dataset.view === view);
}}

function renderWave() {{
  const w = D.wave;
  if (!w || !w.signals || !w.signals.length) return;
  document.getElementById("wave").classList.remove("hidden");
  document.getElementById("wavesrc").textContent =
    w.source + " — " + w.cycles + " cycles";
  if (w.fail_at !== null && w.fail_at !== undefined)
    document.getElementById("wavefail").textContent =
      "property fails at cycle " + w.fail_at;

  const GUT = 160, CW = 46, ROW = 24, PAD = 10;
  const n = w.cycles, rows = w.signals.length;
  const W = GUT + n * CW + PAD * 2, H = rows * ROW + PAD * 2 + 18;
  const svg = document.getElementById("wavesvg");
  svg.setAttribute("width", W); svg.setAttribute("height", H);
  svg.setAttribute("viewBox", `0 0 ${{W}} ${{H}}`);
  let s = "";

  for (let i = 0; i < n; i++) {{
    const x = GUT + i * CW + PAD;
    s += `<line x1="${{x}}" y1="${{PAD}}" x2="${{x}}" y2="${{H - PAD - 14}}"`+
         ` stroke="#26262A"/>`;
    s += `<text x="${{x + CW / 2}}" y="${{H - 4}}" fill="#6B7280" font-size="10"`+
         ` text-anchor="middle">${{i}}</text>`;
  }}
  if (w.fail_at !== null && w.fail_at !== undefined) {{
    const x = GUT + w.fail_at * CW + PAD;
    s += `<rect x="${{x}}" y="${{PAD}}" width="${{CW}}" height="${{H - PAD - 14}}"`+
         ` fill="#FF6A00" opacity="0.10"/>`;
    s += `<line x1="${{x}}" y1="${{PAD}}" x2="${{x}}" y2="${{H - PAD - 14}}"`+
         ` stroke="#FF6A00"/>`;
  }}

  w.signals.forEach((sig, r) => {{
    const y = PAD + r * ROW, hi = y + 4, lo = y + ROW - 6, mid = (hi + lo) / 2;
    s += `<text x="${{GUT - 10}}" y="${{mid + 4}}" fill="#A9A9B0" font-size="11"`+
         ` text-anchor="end">${{esc(sig.name)}}</text>`;
    const v = sig.values;
    if (sig.width === 1) {{
      let d = "";
      for (let i = 0; i < n; i++) {{
        const x0 = GUT + i * CW + PAD, x1 = x0 + CW;
        const lvl = v[i] ? hi : lo;
        if (i === 0) d += `M ${{x0}} ${{lvl}}`;
        else if (v[i - 1] !== v[i]) d += ` L ${{x0}} ${{lvl}}`;
        d += ` L ${{x1}} ${{lvl}}`;
      }}
      s += `<path d="${{d}}" fill="none" stroke="#16A34A" stroke-width="1.6"/>`;
    }} else {{
      let i = 0;
      while (i < n) {{
        let j = i;
        while (j + 1 < n && v[j + 1] === v[i]) j++;
        const x0 = GUT + i * CW + PAD, x1 = GUT + (j + 1) * CW + PAD;
        const a = (i > 0 && v[i - 1] !== v[i]) ? 5 : 0;
        const b = (j + 1 < n && v[j + 1] !== v[i]) ? 5 : 0;
        s += `<path d="M ${{x0 + a}} ${{hi}} L ${{x1 - b}} ${{hi}} L ${{x1}} ${{mid}}`+
             ` L ${{x1 - b}} ${{lo}} L ${{x0 + a}} ${{lo}} L ${{x0}} ${{mid}} Z"`+
             ` fill="#2563EB" opacity="0.16" stroke="#4D8DFF" stroke-width="1"/>`;
        if (x1 - x0 > 28)
          s += `<text x="${{(x0 + x1) / 2}}" y="${{mid + 4}}" fill="#CFE0FF"`+
               ` font-size="10" text-anchor="middle">`+
               `${{v[i] == null ? "?" : "0x" + v[i].toString(16)}}</text>`;
        i = j + 1;
      }}
    }}
  }});
  svg.innerHTML = s;
}}

document.getElementById("filter").oninput = renderTree;
for (const t of document.querySelectorAll(".tab"))
  t.onclick = () => {{ view = t.dataset.view; syncTabs(); renderCode(); }};

renderTree(); renderCode(); renderPending(); renderWave(); syncTabs();
</script>
</body>
</html>
"""


def render(data: dict, project: str, revision: str, version: str) -> str:
    s = data["summary"]
    note = ""
    if s.get("not_embedded"):
        note = (f" {s['not_embedded']} file(s) not embedded (source too large) — "
                f"the changed files are always included.")
    return _TEMPLATE.format(
        project=project, revision=revision, version=version,
        ink=INK, panel=PANEL, line=LINE, orange=ORANGE, green=GREEN, blue=BLUE,
        grey=GREY, embed_note=note,
        n_files=s["files"], n_blocks=s["blocks"], n_changed=s["changed"],
        n_pending=s["pending"], n_unresolved=s["unresolved"],
        data=json.dumps(data, separators=(",", ":")),
    )


def build(root, graph, changed_files, befores=None, results=None,
          changes=None, project=None, revision="working copy",
          version="unknown", wave=None) -> str:
    """The whole IDE as one HTML string."""
    data = collect(Path(root), graph, changed_files, befores, results, changes,
                   wave)
    return render(data, project or Path(root).name, revision, version)

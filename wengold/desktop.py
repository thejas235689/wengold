"""WENGOLD Desktop — a local app, served from the standard library.

`wengold desktop ./rtl` builds the graph once, serves a small UI on localhost and
opens your browser. No Electron, no Node, no build step: the project's claim is
that the graph, kernel and CLI are standard library only, and a desktop shell
should not break that.

Why not Electron or Tauri: both need a Node toolchain to build and produce a
platform-specific binary. This produces nothing to distribute — it runs wherever
Python runs, which for a verification tool is the machine that already has the
design on it.

Endpoints:

| route | what it returns |
| --- | --- |
| `/` | the UI |
| `/api/summary` | files, nodes, edges, blocks, unresolved, coverage, complete |
| `/api/blocks` | every RTL block with its fan-in and fan-out |
| `/api/verdicts?change=X` | the kernel's verdict for every result after change X |
| `/api/singularity` | condition number and the blocks with the largest blast radius |

The server binds to 127.0.0.1 only. It has no authentication because it is not
reachable off the machine — binding it to 0.0.0.0 would make that untrue, so the
option is not offered.
"""
from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

__all__ = ["serve", "build_state", "HTML"]

HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>WENGOLD</title>
<style>
:root{--bg:#0B0B0C;--panel:#141416;--line:#26262A;--fg:#F5F5F5;
--dim:#9A9AA0;--orange:#FF6A00;--green:#16A34A;--blue:#2563EB}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
header{padding:18px 24px;border-bottom:1px solid var(--line);display:flex;
align-items:center;gap:16px}
h1{font-size:15px;margin:0;letter-spacing:.14em;font-weight:700}
h1 span{color:var(--orange)}
#path{color:var(--dim);font-size:12px}
nav{display:flex;gap:4px;padding:10px 24px;border-bottom:1px solid var(--line)}
button{background:transparent;border:1px solid transparent;color:var(--dim);
padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit;font-size:13px}
button.on{background:var(--panel);border-color:var(--line);color:var(--fg)}
button:hover{color:var(--fg)}
main{padding:22px 24px}
.cards{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:22px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:14px 18px;min-width:130px}
.card .k{color:var(--dim);font-size:11px;text-transform:uppercase;
letter-spacing:.08em}
.card .v{font-size:24px;font-weight:600;margin-top:4px}
.ok{color:var(--green)}.bad{color:var(--orange)}.info{color:var(--blue)}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--dim);font-weight:500;font-size:11px;
text-transform:uppercase;letter-spacing:.08em;padding:8px 10px;
border-bottom:1px solid var(--line)}
td{padding:7px 10px;border-bottom:1px solid #1b1b1e}
tr:hover td{background:#17171a}
.tag{padding:1px 7px;border-radius:4px;font-size:11px}
.t-valid{background:rgba(22,163,74,.16);color:var(--green)}
.t-inv{background:rgba(255,106,0,.16);color:var(--orange)}
.t-unk{background:rgba(37,99,235,.16);color:var(--blue)}
.bar{height:4px;background:var(--line);border-radius:2px;overflow:hidden;
margin-top:6px}
.bar i{display:block;height:100%;background:var(--orange)}
#msg{color:var(--dim);font-size:12px;padding:0 24px 18px}
</style></head><body>
<header><h1>WEN<span>GOLD</span></h1><span id="path"></span></header>
<nav>
<button data-t="summary" class="on">Summary</button>
<button data-t="blocks">Blocks</button>
<button data-t="verdicts">Verdicts</button>
<button data-t="singularity">Singularity</button>
</nav>
<main id="view"></main><div id="msg"></div>
<script>
const view=document.getElementById('view');
const esc=s=>String(s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
async function get(u){const r=await fetch(u);return r.json()}
function cards(rows){return '<div class="cards">'+rows.map(([k,v,c])=>
`<div class="card"><div class="k">${esc(k)}</div>
<div class="v ${c||''}">${esc(v)}</div></div>`).join('')+'</div>'}
const TABS={
async summary(){const s=await get('/api/summary');
 document.getElementById('path').textContent=s.path;
 return cards([['files',s.files],['nodes',s.nodes],['edges',s.edges],
 ['blocks',s.blocks],['unresolved',s.unresolved,s.unresolved?'bad':'ok'],
 ['coverage',s.coverage+'%',s.coverage>=80?'ok':s.coverage>=50?'info':'bad'],
 ['complete',s.complete?'yes':'no',s.complete?'ok':'bad']])
 +`<div class="bar"><i style="width:${s.coverage}%"></i></div>`
 +(s.notes.length?'<p style="color:#9A9AA0;margin-top:16px">'+
 esc(s.notes.join(' · '))+'</p>':'')},
async blocks(){const b=await get('/api/blocks');
 return '<table><tr><th>block</th><th>instantiates</th><th>instantiated by</th></tr>'
 +b.blocks.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.out}</td>
 <td>${r.in}</td></tr>`).join('')+'</table>'},
async verdicts(){const v=await get('/api/verdicts');
 const t={VALID:'t-valid',INVALIDATED:'t-inv',UNKNOWN:'t-unk'};
 return `<p style="color:#9A9AA0">change: <b style="color:#F5F5F5">${esc(v.change)}</b>
 — ${v.counts.VALID||0} valid, ${v.counts.INVALIDATED||0} invalidated,
 ${v.counts.UNKNOWN||0} unknown</p>`
 +'<table><tr><th>result</th><th>verdict</th><th>reason</th></tr>'
 +v.results.map(r=>`<tr><td>${esc(r.id)}</td>
 <td><span class="tag ${t[r.verdict]||''}">${esc(r.verdict)}</span></td>
 <td style="color:#9A9AA0">${esc(r.reason)}</td></tr>`).join('')+'</table>'},
async singularity(){const s=await get('/api/singularity');
 if(!s.blocks)return '<p>no blocks</p>';
 return cards([['blocks',s.blocks],['condition',s.condition_number,
 s.condition_number>10?'bad':'ok'],['worst radius',s.worst_radius],
 ['median',s.median]])+'<p style="color:#9A9AA0">'+esc(s.verdict)+'</p>'
 +'<table><tr><th>block</th><th>blast radius</th><th>share</th></tr>'
 +s.singular.map(r=>`<tr><td>${esc(r.name)}</td><td>${r.radius}</td>
 <td>${r.fraction}</td></tr>`).join('')+'</table>'}
};
async function show(t){document.querySelectorAll('nav button')
 .forEach(b=>b.classList.toggle('on',b.dataset.t===t));
 view.innerHTML='<p style="color:#9A9AA0">loading…</p>';
 try{view.innerHTML=await TABS[t]()}catch(e){view.innerHTML=
 '<p class="bad">'+esc(e.message)+'</p>'}}
document.querySelectorAll('nav button').forEach(b=>
 b.onclick=()=>show(b.dataset.t));
show('summary');
</script></body></html>
"""


def build_state(path: str) -> dict:
    """Everything the UI needs, computed once at startup."""
    from .cli import _collect
    from .graph.builder import GraphBuilder
    from .graph.model import NodeKind

    files = _collect(path)
    g = GraphBuilder().build_from_files(files, backend="auto")
    c = g.completeness()
    blocks = sorted(n for n, d in g.nodes.items() if d.kind is NodeKind.RTL)

    rows = []
    for b in blocks:
        rows.append({"name": b,
                     "out": len(g.rtl_ancestors(b)) if hasattr(g, "rtl_ancestors") else 0,
                     "in": len(g.rtl_descendants(b)) if hasattr(g, "rtl_descendants") else 0})

    return {
        "path": str(path),
        "files": len(files), "nodes": len(g.nodes), "edges": len(g.edges),
        "blocks": len(blocks), "unresolved": len(c["unresolved"]),
        "coverage": round(c["file_coverage"] * 100),
        "complete": bool(c["complete"]),
        "notes": [n for n in dict.fromkeys(g.notes)][:3],
        "graph": g, "block_names": blocks,
    }


def _verdicts(state: dict) -> dict:
    from .agent.perception import perceive
    from .kernel.validity import Result

    g = state["graph"]
    names = state["block_names"]
    if not names:
        return {"change": "-", "results": [], "counts": {}}
    # change the block with the largest blast radius: the most interesting default
    change = max(names, key=lambda b: len(g.descendants(b))
                 if hasattr(g, "descendants") else 0)
    results = [Result(f"{b}_sim", "sim", depends_on={b}) for b in names]
    ctx = perceive(g, results, {change})
    # `ctx.verdicts` and `ctx.reasons` are dicts keyed by result id; `ctx.results`
    # is a dict as well, not a list. Iterating it as a sequence gave every row an
    # id of "?" and an empty reason — the panel looked broken while the kernel was
    # working correctly underneath.
    out, counts = [], {}
    for rid, verdict in ctx.verdicts.items():
        v = str(getattr(verdict, "value", verdict)).split(".")[-1].upper()
        counts[v] = counts.get(v, 0) + 1
        out.append({"id": rid, "verdict": v,
                    "reason": (ctx.reasons.get(rid, "") or "")[:150]})
    out.sort(key=lambda r: r["id"])
    return {"change": change, "results": out[:400], "counts": counts}


def _singularity(state: dict) -> dict:
    from .graph.singularity import conditioning, singular_nodes

    c = conditioning(state["graph"])
    nodes = singular_nodes(state["graph"], threshold=0.25)
    return {"blocks": c["blocks"], "condition_number": c["condition_number"],
            "worst_radius": c["worst_radius"], "median": c["median"],
            "verdict": c["verdict"],
            "singular": [{"name": s.node, "radius": s.blast_radius,
                          "fraction": f"{s.fraction:.1%}"} for s in nodes[:20]]}


def _handler(state: dict):
    cache: dict = {}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, body: bytes, ctype: str, code: int = 200):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj):
            self._send(json.dumps(obj).encode(), "application/json")

        def do_GET(self):
            u = urlparse(self.path)
            if u.path == "/":
                self._send(HTML.encode(), "text/html; charset=utf-8")
                return
            if u.path == "/api/summary":
                self._json({k: v for k, v in state.items()
                            if k not in ("graph", "block_names")})
                return
            if u.path == "/api/blocks":
                from .graph.builder import GraphBuilder  # noqa: F401
                g = state["graph"]
                rows = []
                for b in state["block_names"]:
                    rows.append({"name": b,
                                 "out": len(g.rtl_ancestors(b)),
                                 "in": len(g.rtl_descendants(b))})
                self._json({"blocks": rows})
                return
            if u.path == "/api/verdicts":
                if "v" not in cache:
                    cache["v"] = _verdicts(state)
                self._json(cache["v"])
                return
            if u.path == "/api/singularity":
                if "s" not in cache:
                    cache["s"] = _singularity(state)
                self._json(cache["s"])
                return
            self._send(b'{"error":"not found"}', "application/json", 404)

    return H


def serve(path: str = ".", port: int = 8765, open_browser: bool = True,
          quiet: bool = False) -> None:
    """Build the graph, serve the UI on 127.0.0.1 and open a browser."""
    state = build_state(path)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(state))
    url = f"http://127.0.0.1:{port}/"
    if not quiet:
        print(f"  WENGOLD desktop  {state['files']} files, "
              f"{state['blocks']} blocks, {state['unresolved']} unresolved")
        print(f"  serving {url}   (Ctrl-C to stop)")
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()

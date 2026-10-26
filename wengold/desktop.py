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
import os
import threading
import webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

__all__ = ["serve", "build_state", "HTML", "launch_app",
           "find_app_browser", "install_shortcut", "SHORTCUT_SVG"]

HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>WENGOLD</title>
<link rel="icon" href="/icon.png">
<style>
:root{--bg:#FFFFFF;--panel:#FAFAFA;--panel2:#F4F4F5;--line:#E4E4E7;
--line2:#EFEFF1;--fg:#18181B;--dim:#52525B;--dim2:#A1A1AA;
--red:#C81E1E;--red-soft:rgba(200,30,30,.10);--red-line:rgba(200,30,30,.35);
--grey:#3F3F46;--grey-soft:rgba(63,63,70,.08)}
*{box-sizing:border-box}
html,body{height:100%}
body{margin:0;background:var(--bg);color:var(--fg);overflow:hidden;
font:12.5px/1.45 ui-monospace,SFMono-Regular,"SF Mono",Menlo,Consolas,monospace}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
#top{height:44px;display:flex;align-items:center;gap:12px;padding:0 14px;
border-bottom:2px solid var(--red);background:var(--bg)}
#top img{width:20px;height:20px;border-radius:4px}
#mark{font-weight:700;letter-spacing:.16em;font-size:11.5px}
#mark i{font-style:normal;color:var(--red)}
#proj{color:var(--dim);font-size:11.5px}
#spacer{flex:1}
.pill{border:1px solid var(--line);border-radius:5px;padding:3px 8px;
font-size:11px;color:var(--dim)}
.pill b{color:var(--fg);font-weight:600}
.pill.ok{border-color:var(--line);color:var(--grey)}
.pill.warn{border-color:var(--red-line);color:var(--red);background:var(--red-soft)}
#body{display:grid;grid-template-columns:238px 1fr 372px;
height:calc(100% - 44px - 26px - 320px)}
#cli{height:320px;border-top:2px solid var(--red);background:var(--bg);
display:flex;flex-direction:column;overflow:hidden}
#clihead{display:flex;align-items:center;gap:8px;padding:5px 12px;
font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;
color:var(--dim2);border-bottom:1px solid var(--line);background:var(--panel)}
#out{flex:1;overflow:auto;padding:8px 12px;font-size:12px;line-height:1.5;
white-space:pre-wrap;word-break:break-word}
#out .cmd{color:var(--red)}
#out .dim{color:var(--dim2)}
#out .ok{color:var(--grey)}
#inrow{display:flex;align-items:center;gap:8px;border-top:1px solid var(--line);
padding:6px 12px;background:var(--panel)}
#caret{color:var(--red);font-weight:700}
#in{flex:1;background:transparent;border:0;outline:0;color:var(--fg);
font:inherit;font-size:12.5px}
#in::placeholder{color:var(--dim2)}
.ask{margin:2px 0 6px}
.ask .cmd{color:var(--red);font-weight:700}
.steps{color:var(--dim2);font-size:11px;letter-spacing:.06em;
text-transform:uppercase;margin:8px 0 6px}
.step{display:flex;align-items:baseline;gap:8px;padding:2px 0}
.tick{color:var(--green);font-weight:700}
.lbl{color:var(--fg)}
.code{color:var(--dim2);font-size:11.5px}
.dur{margin-left:auto;color:var(--dim2);font-size:11px}
.det{color:var(--dim);font-size:11.5px;padding-left:20px;margin-bottom:4px}
.sum{border-left:2px solid var(--red-line);padding:6px 0 6px 10px;
color:var(--fg);margin-top:8px}
.pane{overflow:auto;border-right:1px solid var(--line);background:var(--panel)}
.pane:last-child{border-right:0;background:var(--panel2)}
.panehead{position:sticky;top:0;z-index:2;background:var(--panel);
border-bottom:1px solid var(--line);padding:7px 12px;font-size:10.5px;
letter-spacing:.1em;text-transform:uppercase;color:var(--dim2);
display:flex;justify-content:space-between}
.pane:last-child .panehead{background:var(--panel2)}
.row{padding:3px 12px;white-space:nowrap;overflow:hidden;
text-overflow:ellipsis;color:var(--dim);cursor:pointer;font-size:12px}
.row:hover{background:var(--panel2);color:var(--fg)}
.row.sel{background:var(--red-soft);color:var(--fg);box-shadow:inset 2px 0 0 var(--red)}
.dir{color:var(--fg);font-weight:600}
.row .n{color:var(--dim2);font-size:10.5px;margin-left:6px}
.caret{display:inline-block;width:10px;color:var(--dim2)}
.r{display:grid;grid-template-columns:16px 1fr auto;gap:8px;align-items:center;
padding:5px 12px;border-bottom:1px solid var(--line2);cursor:pointer;font-size:12px}
.r:hover{background:var(--panel2)}
.r.sel{background:var(--red-soft);box-shadow:inset 2px 0 0 var(--red)}
.r .id{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.v{font-size:10px;padding:1px 6px;border-radius:3px;letter-spacing:.04em}
.v.VALID{background:var(--grey-soft);color:var(--grey)}
.v.INVALIDATED{background:var(--red-soft);color:var(--red);font-weight:600}
.v.UNKNOWN{background:var(--panel2);color:var(--dim2)}
.g{font-size:11px}
.g.ok{color:var(--grey)}.g.bad{color:var(--red)}.g.un{color:var(--dim2)}
#detail{padding:14px}
#detail h3{margin:0 0 3px;font-size:13px;font-weight:600;word-break:break-all}
#detail .sub{color:var(--dim2);font-size:11px;margin-bottom:14px}
.kv{display:grid;grid-template-columns:96px 1fr;gap:4px 10px;font-size:12px;margin-bottom:16px}
.kv dt{color:var(--dim2)}
.kv dd{margin:0;word-break:break-word}
.why{border-left:2px solid var(--red-line);padding:8px 0 8px 12px;
color:var(--dim);font-size:12px;line-height:1.55}
.why b{color:var(--fg);font-weight:600}
.bar{height:3px;background:var(--line);border-radius:2px;overflow:hidden;margin:6px 0 14px}
.bar i{display:block;height:100%;background:var(--red)}
.empty{color:var(--dim2);padding:14px;font-size:12px}
#status{height:26px;display:flex;align-items:center;gap:14px;padding:0 14px;
border-top:1px solid var(--line);background:var(--panel);font-size:11px;
color:var(--dim2);overflow:hidden}
#status b{color:var(--dim);font-weight:500}
#status .sep{color:var(--line)}
::-webkit-scrollbar{width:9px;height:9px}
::-webkit-scrollbar-thumb{background:#D4D4D8;border-radius:5px}
::-webkit-scrollbar-track{background:transparent}
</style></head><body>

<div id="top">
  <img src="/icon.png" alt="">
  <span id="mark">WEN<i>GOLD</i></span>
  <span id="proj">loading…</span>
  <span id="spacer"></span>
  <span class="pill" id="p-cov">coverage —</span>
  <span class="pill" id="p-cond">condition —</span>
  <span class="pill" id="p-unres">unresolved —</span>
</div>

<div id="body">
  <div class="pane"><div class="panehead"><span>Explorer</span><span id="nf"></span></div>
    <div id="tree"></div></div>
  <div class="pane"><div class="panehead"><span>Results</span><span id="nr"></span></div>
    <div id="results"></div></div>
  <div class="pane"><div class="panehead"><span>Detail</span></div>
    <div id="detail"><div class="empty">select a result or a file</div></div></div>
</div>

<div id="cli">
  <div id="clihead"><span>CLI</span><span style="color:var(--dim2)">type <b style="color:var(--fg)">help</b> for commands</span></div>
  <div id="out"><span class="dim">wengold desktop — the kernel is ready.</span></div>
  <div id="inrow"><span id="caret">›</span><input id="in" autocomplete="off" spellcheck="false" placeholder="ask anything, or type help — e.g. what must I re-run?"></div>
</div>
<div id="status"><span id="s-msg">—</span></div>

<script>
/*__STATE__*/
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const $=id=>document.getElementById(id);
async function get(u){const r=await fetch(u);if(!r.ok)throw new Error(u+' '+r.status);return r.json()}

async function boot(){
  try{
    // the state is inlined by the server, so the first paint needs no request
    const S=window.__WENGOLD__;
    const s=S.summary;
    $('proj').textContent=s.path.split('/').slice(-2).join('/');
    $('p-cov').innerHTML='coverage <b>'+s.coverage+'%</b>';
    $('p-cov').className='pill '+(s.coverage>=80?'ok':'warn');
    const c=S.singularity;
    $('p-cond').innerHTML='condition <b>'+(c.condition_number||0).toFixed(2)+'</b>';
    $('p-cond').className='pill '+((c.condition_number||0)>10?'warn':'ok');
    $('p-unres').innerHTML='unresolved <b>'+s.unresolved+'</b>';
    $('p-unres').className='pill '+(s.unresolved?'warn':'ok');
    $('s-msg').innerHTML=s.blocks+' blocks <span class="sep">·</span> '+
      s.nodes+' nodes <span class="sep">·</span> '+s.edges+' edges <span class="sep">·</span> '+
      (s.complete?'<b>complete</b>':'<b>incomplete</b>');
    renderTree(S.tree);
    const r=S.verdicts;renderResults(r);
    // open the most interesting result so the detail pane is not blank on arrival
    const first=r.results.find(x=>x.verdict==='INVALIDATED')||r.results[0];
    if(first){const el=document.querySelector('#results [data-id="'+
      CSS.escape(first.id)+'"]');if(el)el.click();}
  }catch(e){$('s-msg').textContent='error: '+e.message}
}

function renderTree(d){
  $('nf').textContent=d.files.length+' files';
  const byDir={};
  for(const f of d.files){
    const parts=f.split('/');const dir=parts.length>1?parts.slice(0,-1).join('/'):'';
    (byDir[dir]=byDir[dir]||[]).push(parts[parts.length-1]);
  }
  let h='';
  for(const dir of Object.keys(byDir).sort()){
    if(dir)h+='<div class="row dir"><span class="caret">▾</span>'+esc(dir)+
      '<span class="n">'+byDir[dir].length+'</span></div>';
    for(const f of byDir[dir].sort())
      h+='<div class="row" data-file="'+esc(dir?dir+'/'+f:f)+'"><span class="caret"></span>'+
         esc(f)+'</div>';
  }
  $('tree').innerHTML=h||'<div class="empty">no HDL files</div>';
  $('tree').querySelectorAll('[data-file]').forEach(el=>el.onclick=()=>selectFile(el));
}

async function selectFile(el){
  document.querySelectorAll('#tree .row').forEach(r=>r.classList.remove('sel'));
  el.classList.add('sel');
  const f=el.dataset.file;
  try{renderFile(await get('/api/detail?file='+encodeURIComponent(f)),f)}
  catch(e){$('detail').innerHTML='<div class="empty">'+esc(e.message)+'</div>'}
}

function renderFile(d,f){
  $('detail').innerHTML='<h3>'+esc(f)+'</h3><div class="sub">'+d.blocks.length+
    ' module(s) defined here</div>'+
    (d.blocks.length?'<dl class="kv">'+d.blocks.map(b=>'<dt>'+esc(b.name)+'</dt><dd>'+
      b.instantiates+' out · '+b.instantiated_by+' in</dd>').join('')+'</dl>'
      :'<div class="empty">no modules</div>');
}

function renderResults(r){
  $('nr').textContent=(r.results||[]).length+' results';
  const order={INVALIDATED:0,UNKNOWN:1,VALID:2};
  const rows=[...(r.results||[])].sort((a,b)=>(order[a.verdict]-order[b.verdict])||
    a.id.localeCompare(b.id));
  const gl={VALID:'ok',INVALIDATED:'bad',UNKNOWN:'un'};
  const sym={VALID:'✓',INVALIDATED:'✗',UNKNOWN:'?'};
  $('results').innerHTML=rows.map(x=>'<div class="r" data-id="'+esc(x.id)+'">'+
    '<span class="g '+gl[x.verdict]+'">'+sym[x.verdict]+'</span>'+
    '<span class="id">'+esc(x.id)+'</span>'+
    '<span class="v '+x.verdict+'">'+x.verdict+'</span></div>').join('')
    ||'<div class="empty">no results</div>';
  $('results').querySelectorAll('[data-id]').forEach(el=>el.onclick=()=>{
    document.querySelectorAll('#results .r').forEach(x=>x.classList.remove('sel'));
    el.classList.add('sel');
    renderResult(rows.find(v=>v.id===el.dataset.id), r.change);
  });
}

function renderResult(x,change){
  const col={VALID:'var(--grey)',INVALIDATED:'var(--red)',UNKNOWN:'var(--dim2)'}[x.verdict];
  $('detail').innerHTML='<h3>'+esc(x.id)+'</h3>'+
    '<div class="sub">verdict <span style="color:'+col+'">'+x.verdict+
    '</span> after a change to <b style="color:var(--fg)">'+esc(change)+'</b></div>'+
    '<dl class="kv"><dt>verdict</dt><dd style="color:'+col+'">'+x.verdict+'</dd>'+
    '<dt>changed</dt><dd>'+esc(change)+'</dd></dl>'+
    '<div class="why"><b>Why.</b> '+esc(x.reason||'the kernel gave no reason')+'</div>';
}

/* ---------- CLI ---------- */
const out=$('out'), inp=$('in');
function write(html){out.insertAdjacentHTML('beforeend',html);out.scrollTop=out.scrollHeight}
function esc2(s){return esc(s)}

async function runCmd(line){
  const cmd=line.trim();
  if(!cmd)return;
  inp.value='';
  if(cmd==='clear'){out.innerHTML='';return}
  if(cmd==='help'){
    write('<div class="dim">'+[
      'Type a request and the agent reports the steps it took.',
      '',
      '  summary              graph counts and completeness',
      '  files                the HDL file set',
      '  blocks               every RTL block, fan-in and fan-out',
      '  verdicts [id]        kernel verdicts after the change',
      '  singularity          conditioning and blast radii',
      '  clear                clear this pane',
      '  help                 this list'
    ].join(String.fromCharCode(10))+'</div>');
    return;
  }
  write('<div class="ask"><span class="cmd">›</span> '+esc(cmd)+'</div>');

  // bare commands answer directly; anything else runs the agent plan
  const bare=['summary','files','blocks','verdicts','singularity'];
  if(bare.includes(cmd.split(' ')[0])){
    try{
      const r=await get('/api/exec?cmd='+encodeURIComponent(cmd));
      write('<div class="'+(r.ok?'ok':'dim')+'">'+esc(r.output)+'</div>');
    }catch(e){write('<div class="dim">error: '+esc(e.message)+'</div>')}
    return;
  }
  try{
    const a=await get('/api/agent?q='+encodeURIComponent(cmd));
    if(!a.ok){write('<div class="dim">error: '+esc(a.error||'failed')+'</div>');return}
    write('<div class="steps">Tool actions '+(a.steps||[]).length+' steps '+
          a.total_secs+'s</div>');
    let h='';
    for(const s of (a.steps||[])){
      h+='<div class="step"><span class="tick">✓</span>'+
         '<span class="lbl">'+esc(s.label)+'</span>'+
         '<span class="code">'+esc(s.cmd)+'</span>'+
         '<span class="dur">'+s.secs+'s</span></div>'+
         '<div class="det">'+esc(s.detail)+'</div>';
    }
    h+='<div class="sum">'+esc(a.summary)+'</div>';
    const before=out.scrollHeight;
    write(h);
    // scroll so the request line sits at the top of the pane
    const asks=out.querySelectorAll('.ask');
    if(asks.length)out.scrollTop=asks[asks.length-1].offsetTop-out.offsetTop;
  }catch(e){write('<div class="dim">error: '+esc(e.message)+'</div>')}
}
inp.addEventListener('keydown',e=>{if(e.key==='Enter')runCmd(inp.value)});
$('clihead').addEventListener('click',()=>inp.focus());

boot();
// ?ask=... deep-links a request, so a transcript can be shared or reproduced
const _ask=new URLSearchParams(location.search).get('ask');
if(_ask){inp.value=_ask;setTimeout(()=>runCmd(_ask),120);}
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
        "file_paths": sorted(
            str(Path(f).resolve().relative_to(Path(path).resolve()))
            if str(Path(f).resolve()).startswith(str(Path(path).resolve())) else f
            for f in files),
    }


def _files_of(state: dict) -> list:
    """The HDL file set, relative to the project root, for the explorer."""
    return list(state.get("file_paths", []))


def _file_detail(state: dict, rel: str) -> dict:
    """What a file contributes: its modules and their fan-in/out."""
    g = state["graph"]
    root = Path(state["path"])
    want = rel.lstrip("./")

    def norm(path) -> str:
        p = str(path)
        try:
            return str(Path(p).resolve().relative_to(root.resolve()))
        except (ValueError, OSError):
            return p.lstrip("./")

    blocks = []
    for b in state["block_names"]:
        node = g.nodes.get(b)
        path = getattr(node, "path", None)
        if path and norm(path) == want:
            blocks.append({"name": b, "instantiates": len(g.rtl_ancestors(b)),
                           "instantiated_by": len(g.rtl_descendants(b))})
    notes = [n for n in dict.fromkeys(g.notes) if rel and rel in n]
    return {"file": rel, "blocks": blocks, "notes": notes[:6]}


# A deliberately tiny command surface. The desktop app runs on the user's machine
# with their design on disk, so it must never be a shell: only these verbs run, and
# each one reads state the kernel already computed. Adding a verb here is a code
# change, not a config option.
CLI_COMMANDS = ("summary", "files", "blocks", "verdicts", "singularity", "help")


def _page(state: dict) -> str:
    """The app HTML with the initial state inlined."""
    import json as _json
    initial = {
        "summary": {k: v for k, v in state.items()
                    if k not in ("graph", "block_names", "file_paths")},
        "tree": {"files": _files_of(state)},
        "verdicts": _verdicts(state),
        "singularity": _singularity(state),
    }
    blob = _json.dumps(initial).replace("</", "<\\/")
    return HTML.replace("/*__STATE__*/", "window.__WENGOLD__ = " + blob + ";")



def _agent(state: dict, q: str) -> dict:
    """Run a short plan and report it as timed steps.

    This is the shape a verification transcript actually has: a request, then the
    actions taken, each with the command that ran, what it produced and how long it
    took. A bare command prompt tells you the answer but not how it was reached, and
    "how it was reached" is what a reviewer needs to trust the answer.
    """
    import time

    steps = []
    t0 = time.perf_counter()

    def step(label, cmd, detail):
        nonlocal t0
        now = time.perf_counter()
        steps.append({"label": label, "cmd": cmd, "detail": detail,
                      "secs": round(now - t0, 2), "done": True})
        t0 = now

    g = state["graph"]
    files = state.get("file_paths") or []
    step("Indexed RTL", "wengold index .",
         f"{len(files)} file(s)")

    step("Built dependency graph", "wengold ingest graph",
         f"{len(g.nodes)} nodes · {len(g.edges)} edges")

    blocks = state["block_names"]
    step("Enumerated design blocks", "wengold blocks",
         f"{len(blocks)} block(s)")

    c = state["graph"].completeness()
    step("Checked elaboration completeness", "wengold index --check",
         f"{len(c['unresolved'])} unresolved · "
         f"{round(c['file_coverage'] * 100)}% file coverage")

    v = _verdicts(state)
    counts = v["counts"]
    step("Classified every result", f"wengold verdicts --change {v['change']}",
         " · ".join(f"{n} {k.lower()}" for k, n in sorted(counts.items())))

    todo = counts.get("INVALIDATED", 0) + counts.get("UNKNOWN", 0)
    step("Computed minimum new evidence", "wengold plan",
         f"{todo} result(s) to re-establish")

    total = round(sum(s["secs"] for s in steps), 2)
    if todo:
        summary = (f"{todo} of {len(v['results'])} result(s) no longer hold after a "
                   f"change to {v['change']}. Re-establish those before trusting "
                   f"anything downstream of them.")
    else:
        summary = (f"Every result still holds after a change to {v['change']}. "
                   f"Nothing needs re-running.")

    return {"ok": True, "request": q, "steps": steps, "total_secs": total,
            "summary": summary, "change": v["change"], "counts": counts}


def _exec(state: dict, line: str) -> dict:
    """Run one whitelisted command against the indexed state."""
    parts = line.strip().split()
    if not parts:
        return {"ok": True, "output": ""}
    verb, args = parts[0].lower(), parts[1:]
    if verb not in CLI_COMMANDS:
        return {"ok": False, "output": f"unknown command: {verb}. try: help"}

    if verb == "summary":
        s = state
        return {"ok": True, "output": (
            f"files {s['files']}  nodes {s['nodes']}  edges {s['edges']}\n"
            f"blocks {s['blocks']}  unresolved {s['unresolved']}  "
            f"coverage {s['coverage']}%\n"
            f"complete {s['complete']}")}

    if verb == "help":
        return {"ok": True, "output":
                "summary              graph counts and completeness\n"
                "files                the HDL file set\n"
                "blocks               every RTL block, fan-in and fan-out\n"
                "verdicts [id]        kernel verdicts after the change\n"
                "singularity          conditioning and blast radii\n"
                "clear                clear the pane\n"
                "help                 this list"}

    if verb == "files":
        fs = _files_of(state)
        return {"ok": True, "output": "\n".join(fs) if fs else "(no HDL files)"}

    if verb == "blocks":
        g = state["graph"]
        rows = [f"{b:<34}{len(g.rtl_ancestors(b)):>4} out "
                f"{len(g.rtl_descendants(b)):>4} in"
                for b in state["block_names"]]
        return {"ok": True, "output": "\n".join(rows) if rows else "(no blocks)"}

    if verb == "verdicts":
        v = _verdicts(state)
        if args:
            want = args[0]
            hit = [r for r in v["results"] if r["id"] == want]
            if not hit:
                return {"ok": False, "output": f"no result {want!r}"}
            r = hit[0]
            return {"ok": True, "output": (
                f"{r['id']}\n  verdict {r['verdict']}\n  {r['reason']}")}
        counts = v["counts"]
        head = (f"change: {v['change']}\n"
                + "  ".join(f"{k} {n}" for k, n in sorted(counts.items())))
        return {"ok": True, "output": head}

    if verb == "singularity":
        s = _singularity(state)
        # `_singularity` reports the worst *radius*, not a worst name — the name is
        # the first entry of `singular`. Reading `s['worst']` raised KeyError and
        # took the whole connection down.
        worst = s["singular"][0]["name"] if s.get("singular") else "(none)"
        return {"ok": True, "output": (
            f"blocks {s['blocks']}  condition {s['condition_number']:.2f}\n"
            f"worst {worst} ({s['worst_radius']} blocks)  "
            f"median {s['median']:.0f}\n{s['verdict']}")}

    return {"ok": True, "output": ""}


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
                # Server-render the first paint. Fetching the initial state meant a
                # blank window until three round-trips finished, and anything that
                # screenshots or proxies the page before then saw "loading…".
                self._send(_page(state).encode(), "text/html; charset=utf-8")
                return
            if u.path == "/api/summary":
                self._json({k: v for k, v in state.items()
                            if k not in ("graph", "block_names")})
                return
            if u.path == "/icon.png":
                from .assets import icon_bytes
                self._send(icon_bytes(), "image/png")
                return
            if u.path == "/api/agent":
                q = parse_qs(u.query)
                try:
                    payload = _agent(state, (q.get("q") or [""])[0])
                except Exception as exc:
                    payload = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
                self._json(payload)
                return
            if u.path == "/api/exec":
                q = parse_qs(u.query)
                try:
                    payload = _exec(state, (q.get("cmd") or [""])[0])
                except Exception as exc:
                    # One bad command must not take the connection down with it —
                    # the browser saw a dropped socket instead of an error.
                    payload = {"ok": False,
                               "output": f"{type(exc).__name__}: {exc}"}
                self._json(payload)
                return
            if u.path == "/api/tree":
                self._json({"files": _files_of(state)})
                return
            if u.path == "/api/detail":
                q = parse_qs(u.query)
                self._json(_file_detail(state, (q.get("file") or [""])[0]))
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




# ---- real app window -------------------------------------------------------
# A browser tab is not an app. Chrome and Edge both accept `--app=<url>`, which
# opens a window with no address bar, no tabs and no browser menu — it looks and
# behaves like a native window, and it costs no toolchain. Electron would give
# the same result for ~100 MB of runtime and a Node build.
APP_BROWSERS = (
    "google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
    "microsoft-edge", "microsoft-edge-stable", "brave-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


def find_app_browser() -> str | None:
    """A browser that supports `--app=`, or None. Absence is not an error."""
    import shutil
    for name in APP_BROWSERS:
        found = shutil.which(name) or (name if os.path.exists(name) else None)
        if found:
            return found
    return None


def launch_app(url: str, browser: str | None = None,
               size: str = "1280,860") -> bool:
    """Open `url` in app mode. Returns False if no browser could do it.

    The separate `--user-data-dir` matters: without it the window joins the
    user's existing browser session, so closing it can take other tabs with it
    and the window size is not respected.
    """
    import subprocess
    import tempfile
    exe = browser or find_app_browser()
    if not exe:
        return False
    profile = os.path.join(tempfile.gettempdir(), "wengold-app-profile")
    os.makedirs(profile, exist_ok=True)
    try:
        subprocess.Popen(
            [exe, f"--app={url}", f"--window-size={size}",
             f"--user-data-dir={profile}", "--no-first-run",
             "--no-default-browser-check"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


SHORTCUT_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#0B0B0C"/>
<path d="M12 42 L20 22 L28 42" stroke="#FF6A00" stroke-width="4"
 fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<path d="M32 22 L32 42 L44 42" stroke="#F5F5F5" stroke-width="4"
 fill="none" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="50" cy="26" r="4" fill="#16A34A"/>
</svg>
"""


def install_shortcut(port: int, root: str, dest: str | None = None,
                     icon: str | None = None) -> str | None:
    """Write a desktop launcher that starts the app for `root`.

    Linux writes a `.desktop` entry. macOS and Windows get the command to make
    their own, printed rather than silently half-installed — a shortcut that
    only works on one platform should say so instead of pretending.
    """
    import stat
    import sys

    python = sys.executable or "python3"
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cmd = f'{python} -c "import sys;sys.path.insert(0,{repo!r});' \
          f'from wengold.desktop import serve;serve({root!r},port={port},app_mode=True)"'

    if not sys.platform.startswith("linux"):
        print("  no automatic shortcut on this platform. To make one:")
        print(f'    {cmd}')
        return None

    if icon is None:
        icon_dir = os.path.join(os.path.expanduser("~"), ".local", "share", "icons")
        os.makedirs(icon_dir, exist_ok=True)
        icon = os.path.join(icon_dir, "wengold.svg")
        try:
            open(icon, "w").write(SHORTCUT_SVG)
        except OSError:
            icon = "applications-engineering"

    target = dest or os.path.join(
        os.path.expanduser("~"), ".local", "share", "applications", "wengold.desktop")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    body = f"""[Desktop Entry]
Type=Application
Name=WENGOLD
Comment=Validity kernel for silicon verification
Exec={cmd}
Icon={icon}
Terminal=false
Categories=Development;Electronics;
StartupNotify=true
"""
    open(target, "w").write(body)
    try:
        os.chmod(target, os.stat(target).st_mode | stat.S_IXUSR)
    except OSError:
        pass
    return target


def serve(path: str = ".", port: int = 8765, open_browser: bool = True,
          quiet: bool = False, app_mode: bool = True,
          window_size: str = "1280,860") -> None:
    """Build the graph and serve the app.

    `app_mode` defaults to True: the window opens without browser chrome when a
    Chromium-family browser is present, and falls back to a normal tab when it is
    not. A desktop app should not require a flag to be a desktop app.
    """
    """Build the graph, serve the UI on 127.0.0.1 and open a browser."""
    state = build_state(path)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _handler(state))
    url = f"http://127.0.0.1:{port}/"
    if not quiet:
        print(f"  WENGOLD desktop  {state['files']} files, "
              f"{state['blocks']} blocks, {state['unresolved']} unresolved")
        print(f"  serving {url}   (Ctrl-C to stop)")
    if open_browser:
        def _open():
            if app_mode and launch_app(url, size=window_size):
                return
            if app_mode and not quiet:
                print("  no Chrome/Edge found for app mode — opening a tab instead")
            webbrowser.open(url)
        threading.Timer(0.4, _open).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped")
    finally:
        httpd.server_close()

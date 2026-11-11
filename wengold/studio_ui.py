"""Silicon Studio extended panes, using only inline HTML/CSS/JS."""

STYLE = """
#studio{display:none;flex:1;min-height:0;flex-direction:column;background:#fff;overflow:hidden}
#studio.open{display:flex}
#studio-bar{background:#fff6d5;border-bottom:1px solid #e8dfbb;padding:10px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
#studio-bar select,#studio-bar button{padding:8px;border-radius:6px;border:1px solid #d5bb69;background:#fff}
#studio-bar button{background:#ffdf4e;font-weight:700}
#studio-state{font-size:11px;color:#65562d}
#studio-content{flex:1;min-height:0;overflow:auto;padding:12px}
#studio-editor{width:100%;height:100%;min-height:220px;resize:none;display:none;background:#fffefa;border:1px solid #e5d49c;border-radius:8px;padding:12px;color:#252525;font:13px/1.5 monospace}
#studio-wave{display:none;overflow:auto}
#studio-formal{display:none;font:12px/1.5 monospace;white-space:pre-wrap;overflow:auto}
#studio-agent{display:none;font:12px/1.6 system-ui,sans-serif}
.studio-step{padding:12px;margin:7px 0;background:#fffbeb;border:1px solid #e8dba9;border-left:4px solid #e9bb29;border-radius:5px}
.studio-step small{display:block;color:#756b4c}
#studio-wave table{border-collapse:collapse;width:100%;font:11px monospace}
#studio-wave td,#studio-wave th{padding:8px;border-bottom:1px solid #eae1c6;text-align:left}
#studio-wave svg{width:100%;min-width:320px}
"""

HTML = """
<section id="studio" aria-label="Engineering workspaces">
 <div id="studio-bar"><label for="studio-file">Artifact</label><select id="studio-file"></select>
 <button type="button" id="studio-open">Open</button>
 <button type="button" id="studio-save" style="display:none">Save RTL</button>
 <button type="button" id="studio-plan" style="display:none">Inspect agent plan</button>
 <span id="studio-state" role="status"></span></div>
 <div id="studio-content"><textarea id="studio-editor" spellcheck="false" aria-label="RTL source editor"></textarea>
 <div id="studio-wave"></div><pre id="studio-formal"></pre><div id="studio-agent"></div></div>
</section>
"""

JS = r"""
(function(){
const $=id=>document.getElementById(id), studio=$('studio'),pick=$('studio-file'),info=$('studio-state'),edit=$('studio-editor');
const save=$('studio-save'),plan=$('studio-plan'),open=$('studio-open'),panes={editor:edit,wave:$('studio-wave'),formal:$('studio-formal'),orchestrate:$('studio-agent')};
let view='',sha='',file='',dirty=false;
function status(t){info.textContent=t}
function option(f){const o=document.createElement('option');o.textContent=f;o.value=f;pick.appendChild(o)}
async function api(url,body){const r=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||'HTTP '+r.status);return d}
const previous=setWorkspace;
setWorkspace=function(v){
 if(!panes[v]){studio.classList.remove('open');$('body').style.display='grid';$('metrics').style.display='grid';return previous(v)}
 view=v;studio.classList.add('open');$('body').style.display='none';$('metrics').style.display='none';
 document.querySelectorAll('.workspace-tab').forEach(t=>{const active=t.dataset.view===v;t.classList.toggle('active',active);t.setAttribute('aria-pressed',String(active))});
 Object.entries(panes).forEach(([key,p])=>p.style.display=key===v?'block':'none');
 pick.replaceChildren();dirty=false;sha='';file='';save.disabled=true;
 save.style.display=v==='editor'?'inline':'none';plan.style.display=v==='orchestrate'?'inline':'none';
 pick.style.display=open.style.display=v==='orchestrate'?'none':'inline';
 if(v==='orchestrate'){status('Graph-based inspection plan; not tool execution.');panes.orchestrate.textContent='Inspect a bounded agent plan derived from the current graph.';return}
 if(v==='editor'){(window.__WENGOLD__.tree.files||[]).forEach(option);status('Select an RTL source file to edit.');return}
 status('Searching project evidence…');
 api('/api/studio/files').then(d=>{(v==='wave'?d.waveforms:d.formal_reports).forEach(option);status(pick.options.length?'Select an artifact and click Open.':'No supported evidence files found.');}).catch(e=>status(e.message));
};
edit.addEventListener('input',()=>{dirty=true;save.disabled=false;status('Unsaved changes; saving requires a subsequent verification rerun.')});
open.onclick=async()=>{
 const name=pick.value;if(!name)return status('Choose a file.');if(view==='editor'&&dirty&&!confirm('Discard unsaved changes?'))return;
 status('Opening '+name+'…');file=name;
 try{
 const q=encodeURIComponent(name);
 if(view==='editor'){const d=await api('/api/studio/source?file='+q);edit.value=d.content;sha=d.sha256;dirty=false;save.disabled=true;status('Loaded '+d.bytes+' bytes; save checks file hash.')}
 if(view==='wave'){const d=await api('/api/studio/wave?file='+q);draw(d);status('VCD trace: '+d.cycles+' timestamps, '+d.signals.length+' signals.')}
 if(view==='formal'){const d=await api('/api/studio/formal?file='+q);panes.formal.textContent=JSON.stringify(d.report,null,2);status(d.note)}
 }catch(e){status('Open error: '+e.message)}
};
save.onclick=async()=>{try{const d=await api('/api/studio/save',{token:window.__WENGOLD_STUDIO_TOKEN__,file,content:edit.value,expected_sha256:sha});sha=d.sha256;dirty=false;save.disabled=true;status('Saved. '+d.note)}catch(e){status('Save failed: '+e.message)}};
plan.onclick=async()=>{try{status('Inspecting graph…');const d=await api('/api/agent?q=inspect%20verification%20plan');if(!d.ok)throw Error(d.error||'Unavailable');const host=panes.orchestrate;host.replaceChildren();for(const step of d.steps||[]){const box=document.createElement('div'),b=document.createElement('strong'),sm=document.createElement('small');box.className='studio-step';b.textContent=step.label;sm.textContent=step.cmd+' — '+step.detail;box.append(b,sm);host.appendChild(box)}const p=document.createElement('p');p.textContent=d.summary;host.appendChild(p);status('Inspection transcript only; no simulation or proof executed.')}catch(e){status(e.message)}};
function draw(d){
 const host=panes.wave;host.replaceChildren();if(!d.cycles){host.textContent='No VCD samples';return}
 const table=document.createElement('table'),thead=document.createElement('tr');
 for(const str of ['Signal','Samples']){const th=document.createElement('th');th.textContent=str;thead.appendChild(th)}table.appendChild(thead);
 for(const sig of d.signals){const row=document.createElement('tr'),td=document.createElement('td'),v=document.createElement('td');td.textContent=sig.name+' ['+sig.width+']';
 const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 600 32');svg.setAttribute('height','36');
 const values=sig.values.slice(0,300);
 if(sig.width===1){const line=document.createElementNS('http://www.w3.org/2000/svg','polyline');line.setAttribute('points',values.map((x,i)=>(i*600/Math.max(values.length-1,1))+','+(x===1?5:x===0?26:16)).join(' '));line.setAttribute('stroke','#b58b00');line.setAttribute('stroke-width','2');line.setAttribute('fill','none');svg.appendChild(line)}
 else {const t=document.createElementNS('http://www.w3.org/2000/svg','text');t.setAttribute('x','3');t.setAttribute('y','20');t.setAttribute('font-size','11');t.textContent=values.slice(0,30).map(x=>x===null?'X':x).join(' | ')+(values.length>30?' …':'');svg.appendChild(t)}
 v.appendChild(svg);row.append(td,v);table.appendChild(row)}
 host.appendChild(table)
}
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue=''}});
})();
"""

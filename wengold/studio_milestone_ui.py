"""Milestone controls injected into the existing studio without third-party assets."""

CSS = """
#milestone-controls{display:flex;align-items:center;flex-wrap:wrap;gap:7px;padding:8px 12px;background:#fffbea;border-bottom:1px solid #e5d8a7}
#milestone-controls button{padding:6px 10px;background:#ffdf4e;color:#332700;border:1px solid #d3b42d;border-radius:6px;cursor:pointer;font-size:11px}
#milestone-controls input{min-width:110px;max-width:220px;padding:7px;border:1px solid #d9cb9f;border-radius:6px;background:white;color:#2c281c}
#milestone-output{padding:10px 14px;white-space:pre-wrap;max-height:175px;overflow:auto;font:11px/1.5 ui-monospace,monospace;color:#373127;background:#fffdf6;border-bottom:1px solid #eee4cb}
"""

HTML = """
<div id="milestone-controls" style="display:none">
 <input id="ms-property" placeholder="Formal property e.g. count <= 3" aria-label="Safety property">
 <button id="ms-formal">Run Formal</button>
 <button id="ms-syntax">Syntax Diagnostics</button>
 <button id="ms-jobs">Refresh Jobs</button>
 <input id="ms-reviewer" placeholder="Reviewer identity" aria-label="Reviewer identity">
 <button id="ms-accept">Accept Proof</button>
 <button id="ms-reject">Reject Evidence</button>
 <input id="ms-signal" placeholder="Signal for cross-probe" aria-label="Waveform signal name">
 <button id="ms-probe">Cross-Probe RTL</button>
</div>
<pre id="milestone-output" style="display:none" role="status"></pre>
"""

JS = r"""
(function(){
const $=id=>document.getElementById(id),panel=$('milestone-controls'),out=$('milestone-output');
let jobId='';
const editor=$('studio-editor'),pick=$('studio-file');
function message(value){out.style.display='block';out.textContent=typeof value==='string'?value:JSON.stringify(value,null,2)}
function sync(){
 const v=document.querySelector('.workspace-tab.active')?.dataset.view||'';
 const enabled=['editor','wave','formal','orchestrate'].includes(v);
 panel.style.display=enabled?'flex':'none';
 out.style.display=enabled?'block':'none';
 for(const [id,condition] of [
 ['ms-formal',v==='formal'],['ms-syntax',v==='editor'],['ms-jobs',v==='orchestrate'||v==='formal'],
 ['ms-reviewer',v==='orchestrate'||v==='formal'],['ms-accept',v==='orchestrate'||v==='formal'],
 ['ms-reject',v==='orchestrate'||v==='formal'],['ms-property',v==='formal'],
 ['ms-signal',v==='wave'],['ms-probe',v==='wave']]){
  $(id).style.display=condition?'inline-block':'none';
 }
}
document.querySelectorAll('.workspace-tab').forEach(b=>b.addEventListener('click',()=>setTimeout(sync,0)));
async function request(url,body){
 const response=await fetch(url,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...body,token:window.__WENGOLD_STUDIO_TOKEN__})}:{});
 const data=await response.json();if(!response.ok)throw Error(data.error||response.status);return data;
}
async function launch(kind){
 const rtl=(window.__WENGOLD__?.tree?.files||[]);
 const f=kind==='syntax'?pick.value:rtl[0];
 if(!f)return message('No indexed RTL file selected.');
 if(kind==='syntax'&&$('studio-save').disabled===false)return message('Save RTL changes before diagnostics.');
 try{
  const d=await request('/api/studio/job',{kind,file:f,engine:'explicit',depth:12,expr:$('ms-property').value});
  jobId=d.id;message('Job queued: '+jobId+'\nSelect Refresh Jobs to inspect the result.');
 }catch(e){message('Job refused: '+e.message)}
}
$('ms-syntax').addEventListener('click',()=>launch('syntax'));
$('ms-formal').addEventListener('click',()=>launch('formal'));
$('ms-jobs').addEventListener('click',async()=>{
 try{
  const d=await request('/api/studio/jobs'),a=await request('/api/studio/audit');
  if(d.jobs.length)jobId=d.jobs[d.jobs.length-1].id;
  message({ledger_audit:a,jobs:d.jobs});
 }catch(e){message(e.message)}
});
async function signoff(decision){
 try{const d=await request('/api/studio/signoff',{id:jobId,decision,reviewer:$('ms-reviewer').value});message(d)}
 catch(e){message('Review refused: '+e.message)}
}
$('ms-accept').addEventListener('click',()=>signoff('accept'));
$('ms-reject').addEventListener('click',()=>signoff('reject'));
$('ms-probe').addEventListener('click',async()=>{
 const sig=$('ms-signal').value.trim();
 if(!sig)return message('Enter an exact waveform signal or leaf name.');
 try{message(await request('/api/studio/probe?signal='+encodeURIComponent(sig)))}
 catch(e){message('Cross-probe: '+e.message)}
});
sync();
})();
"""

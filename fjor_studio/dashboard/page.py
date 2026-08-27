"""The single page. Plain string, no templating engine and no build step."""

PAGE = r"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FJOR Studio</title>
<style>
:root{
  --bg:#0e1013; --panel:#161a20; --panel2:#1c222a; --line:#262d37;
  --ink:#e8ecf1; --dim:#8d99a8; --faint:#5d6875;
  --accent:#d6c46a; --ok:#3fb950; --warn:#d29922; --bad:#f85149; --live:#58a6ff;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Helvetica,Arial,sans-serif}
a{color:var(--live);text-decoration:none}
button{font:inherit;cursor:pointer;border-radius:7px;border:1px solid var(--line);
  background:var(--panel2);color:var(--ink);padding:7px 13px}
button:hover:not(:disabled){border-color:var(--faint)}
button:disabled{opacity:.4;cursor:not-allowed}
button.primary{background:var(--accent);border-color:var(--accent);color:#1a1a12;font-weight:600}
button.danger{border-color:#5c2b2b;color:#ff9d95}
input,select,textarea{font:inherit;background:#0b0d10;color:var(--ink);
  border:1px solid var(--line);border-radius:7px;padding:7px 9px;width:100%}
textarea{resize:vertical;min-height:64px}
label{display:block;font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--faint);margin:0 0 4px}
.layout{display:grid;grid-template-columns:290px 1fr;height:100vh}
.side{background:var(--panel);border-right:1px solid var(--line);
  display:flex;flex-direction:column;overflow:hidden}
.brand{padding:16px 18px;border-bottom:1px solid var(--line);
  display:flex;align-items:center;justify-content:space-between}
.brand h1{margin:0;font-size:14px;letter-spacing:.16em;text-transform:uppercase}
.joblist{overflow-y:auto;flex:1;padding:8px}
.jobcard{padding:10px 12px;border-radius:9px;cursor:pointer;border:1px solid transparent;
  margin-bottom:4px}
.jobcard:hover{background:var(--panel2)}
.jobcard.sel{background:var(--panel2);border-color:var(--line)}
.jobcard .idline{display:flex;justify-content:space-between;align-items:center;gap:8px}
.jobcard .jid{font-weight:600;letter-spacing:.03em}
.jobcard .sub{color:var(--faint);font-size:12px;margin-top:2px}
.main{overflow-y:auto;padding:22px 26px 60px}
.head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;
  flex-wrap:wrap;margin-bottom:18px}
.head h2{margin:0;font-size:24px;letter-spacing:.02em}
.pill{display:inline-block;padding:2px 9px;border-radius:99px;font-size:11px;
  text-transform:uppercase;letter-spacing:.07em;border:1px solid var(--line);color:var(--dim)}
.pill.gate{border-color:var(--accent);color:var(--accent)}
.pill.run{border-color:var(--live);color:var(--live)}
.pill.bad{border-color:var(--bad);color:var(--bad)}
.pill.done{border-color:var(--ok);color:var(--ok)}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
  padding:16px 18px;margin-bottom:16px}
.card h3{margin:0 0 12px;font-size:12px;text-transform:uppercase;
  letter-spacing:.09em;color:var(--faint)}
.track{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:16px}
.step{padding:5px 10px;border-radius:7px;font-size:11px;border:1px solid var(--line);
  color:var(--faint);background:var(--panel)}
.step.past{color:var(--ok);border-color:#1d3a24}
.step.now{color:#1a1a12;background:var(--accent);border-color:var(--accent);font-weight:700}
.step.gate{border-style:dashed}
.money{font-size:30px;font-weight:700;letter-spacing:-.01em}
.money.warn{color:var(--warn)}
.grid{display:grid;gap:12px}
.scenes{grid-template-columns:repeat(auto-fill,minmax(210px,1fr))}
.scene{background:var(--panel2);border:1px solid var(--line);border-radius:10px;
  overflow:hidden;display:flex;flex-direction:column}
.scene.picked{border-color:var(--accent)}
.scene .media{background:#000;aspect-ratio:9/16;display:flex;align-items:center;
  justify-content:center;overflow:hidden}
.scene .media img,.scene .media video{width:100%;height:100%;object-fit:cover;display:block}
.scene .meta{padding:9px 11px;font-size:12px}
.scene .prompt{color:var(--dim);font-size:11px;max-height:52px;overflow:hidden;margin-top:5px}
.shots{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;align-items:flex-start;
  min-height:96px;padding:6px;border-radius:10px;border:1px solid transparent}
.shots.over{border-color:var(--line);background:#141414}
.shot{background:var(--panel2);border:1px solid var(--line);border-radius:9px;
  padding:7px;width:104px;cursor:grab;position:relative;
  transition:outline-color .35s,opacity .15s}
.shot:active{cursor:grabbing}
.shot:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.shot.out{opacity:.45;border-style:dashed}
/* the eye has to be able to follow a shot that just moved: two boxes swapping
   places in a row of near-identical boxes is not a visible event */
.shot.moved{outline:2px solid var(--accent);outline-offset:2px}
.shot.dragging{opacity:.25}
.shot.ghost{box-shadow:0 12px 28px #000a;border-color:var(--accent);cursor:grabbing}
/* where it will land, drawn on the neighbour rather than by moving anything:
   re-rendering the strip mid-drag cancels the drag */
.shot.dropL{box-shadow:inset 3px 0 0 var(--accent)}
.shot.dropR{box-shadow:inset -3px 0 0 var(--accent)}
.shot .thumb{background:#000;border-radius:6px;overflow:hidden;aspect-ratio:9/16;
  display:flex;align-items:center;justify-content:center}
.shot .thumb img,.shot .thumb video{width:100%;height:100%;object-fit:cover;
  display:block;pointer-events:none}
.shot .n{font-weight:700;font-size:12px;margin-top:6px}
.shot .x{position:absolute;top:4px;right:4px;padding:1px 6px;font-size:12px;
  line-height:1.25;opacity:0;transition:opacity .12s}
.shot:hover .x,.shot:focus-within .x{opacity:1}
.tray{display:flex;gap:8px;flex-wrap:wrap;align-items:flex-start;padding:8px;
  border:1px dashed var(--line);border-radius:10px;margin-bottom:12px}
.tray.over{border-color:var(--accent);background:#141410}
.tray .lbl{font-size:11px;text-transform:uppercase;letter-spacing:.07em;
  color:var(--faint);align-self:center;padding:0 6px}
.stale{border:1px solid #3d3218;background:#241f10;color:var(--warn);
  border-radius:9px;padding:9px 12px;font-size:12px;margin-bottom:12px}
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap}
.row.end{justify-content:flex-end}
.qa{font-size:11px;padding:1px 7px;border-radius:99px;border:1px solid var(--line)}
.qa.ok{color:var(--ok);border-color:#1d3a24}
.qa.minor{color:var(--warn);border-color:#3d3218}
.qa.critical{color:var(--bad);border-color:#5c2b2b}
.qa.error,.qa.unclear{color:var(--faint)}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:5px 8px;border-bottom:1px solid var(--line);text-align:left}
th{color:var(--faint);font-weight:500;text-transform:uppercase;font-size:10px;
  letter-spacing:.07em}
td.num{text-align:right;font-variant-numeric:tabular-nums}
.formgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.muted{color:var(--faint)}
.log{font-size:12px;max-height:260px;overflow-y:auto}
.log div{padding:3px 0;border-bottom:1px solid var(--line);color:var(--dim)}
.log b{color:var(--ink);font-weight:600}
dialog{background:var(--panel);color:var(--ink);border:1px solid var(--line);
  border-radius:14px;padding:22px;max-width:620px;width:92vw}
dialog::backdrop{background:rgba(0,0,0,.62)}
.err{background:#2a1417;border:1px solid #5c2b2b;color:#ff9d95;padding:10px 13px;
  border-radius:9px;margin-bottom:14px;font-size:13px}
.empty{color:var(--faint);padding:40px;text-align:center}
.drop{border:2px dashed var(--line);border-radius:11px;padding:22px 18px;text-align:center;
  cursor:pointer;background:#0b0d10;transition:border-color .12s,background .12s}
.drop:hover{border-color:var(--faint)}
.drop.over{border-color:var(--accent);background:#15150e}
.drop.has{border-style:solid;border-color:#1d3a24;text-align:left;cursor:default}
.drop .big{font-size:13px}
.drop .hint{color:var(--faint);font-size:11px;margin-top:5px}
.hint{color:var(--faint);font-size:11px}
.hint b{color:var(--ink);font-weight:600}
.hint.bad{color:#ff9d95}
.bar{height:5px;border-radius:99px;background:var(--line);overflow:hidden;margin-top:10px}
.bar i{display:block;height:100%;background:var(--accent);width:0;transition:width .15s}
video.draft{width:100%;max-width:340px;border-radius:10px;background:#000;display:block}
video.final{width:100%;border-radius:10px;background:#000;display:block}
.finals{grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
.opt{display:block;padding:10px 12px;border:1px solid var(--line);border-radius:9px;
  cursor:pointer;margin-bottom:6px;text-transform:none;letter-spacing:0;color:var(--ink)}
.opt:hover{border-color:var(--faint)}
.opt.sel{border-color:var(--accent);background:#15150e}
.opt .price{float:right;font-variant-numeric:tabular-nums}
</style></head><body>
<div class="layout">
  <aside class="side">
    <div class="brand"><h1>FJOR Studio</h1>
      <button id="newBtn" class="primary" style="padding:5px 11px">New</button></div>
    <div class="joblist" id="joblist"></div>
    <div style="padding:10px 14px;border-top:1px solid var(--line);font-size:11px"
         class="muted" id="workerline">idle</div>
  </aside>
  <main class="main" id="main"><div class="empty">Select a job, or create one.</div></main>
</div>

<dialog id="newDlg"><form method="dialog" id="newForm">
  <h3 style="margin:0 0 16px">New job</h3>
  <div id="newErr"></div>
  <div><label>Creative name</label>
    <input name="creative_name" id="f_name" spellcheck="false"
      placeholder="n-LIPIL025_ch-fb_t-video_c-test_pr-lp_ds-nano_w-34_s-1080x1350">
    <div class="hint" id="nameRead" style="margin-top:6px;min-height:16px"></div></div>
  <div class="formgrid" style="margin-top:12px">
    <div><label>Target vertical</label><select name="vertical" id="f_vertical"></select></div>
    <div><label>Packshot</label><select name="packshot" id="f_packshot"></select></div>
    <div><label>Crossfade (s)</label><input name="crossfade_s" type="number"
         step="0.1" placeholder="config default"></div>
  </div>
  <div class="hint" id="vertWarn" style="margin-top:6px;min-height:14px"></div>
  <div style="margin-top:6px"><label>Brief — anything the pipeline should know</label>
    <textarea name="brief" id="f_brief" placeholder="Angle, must-haves, what to avoid, who it is for. This outranks the house guidance where they disagree."></textarea></div>
  <div style="margin-top:12px"><label>Reference video</label>
    <div class="drop" id="drop">
      <div class="big">Drop the reference video here</div>
      <div class="hint">or click to choose &middot; mp4, mov, m4v, webm, avi, mkv</div>
      <div class="bar" id="dropBar" style="display:none"><i></i></div>
    </div>
    <input type="file" id="dropInput" accept="video/*" style="display:none">
  </div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="newDlg.close()">Cancel</button>
    <button type="button" class="primary" id="createBtn">Create &amp; run</button>
  </div>
</form></dialog>

<dialog id="okDlg"><form method="dialog">
  <h3 style="margin:0 0 6px" id="okTitle">Approve</h3>
  <p class="muted" style="margin:0 0 14px;font-size:12px" id="okHint"></p>
  <div id="okCost"></div>
  <div style="margin-top:12px"><label>Note (optional)</label>
    <input id="okNote" placeholder="what you checked"></div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="okDlg.close()">Cancel</button>
    <button type="button" class="primary" id="okGo">Approve</button>
  </div>
</form></dialog>

<dialog id="devDlg"><form method="dialog">
  <h3 style="margin:0 0 6px">Make a variation</h3>
  <p class="muted" style="margin:0 0 14px;font-size:12px" id="devHint"></p>
  <div id="devErr"></div>
  <div><label>New creative name</label>
    <input id="devName" spellcheck="false"><div class="hint" id="devRead"
      style="margin-top:6px;min-height:16px"></div></div>
  <div style="margin-top:14px"><label>Start from — everything earlier is inherited</label>
    <div id="devFrom"></div></div>
  <div class="formgrid" style="margin-top:6px">
    <div><label>Packshot</label><select id="devPackshot"></select></div>
    <div><label>Music bed</label><select id="devMusic"></select></div>
    <div><label>Crossfade (s)</label><input id="devXfade" type="number" step="0.1"
      placeholder="same as parent"></div>
  </div>
  <div id="devCastRow" style="margin-top:12px;display:none">
    <label>Who stars in it</label>
    <select id="devRecast">
      <option value="">The same person as the parent</option>
      <option value="1">A new person — same cast description, new face</option>
    </select>
    <div class="hint" id="devCastHint" style="margin-top:6px"></div>
    <textarea id="devCastDesc" style="margin-top:8px;display:none"
      placeholder="Optional: describe the new host instead. Another draw of the same words gives another woman of the same description; changing the words is how a variation gets a visibly different person."></textarea>
  </div>
  <div style="margin-top:12px"><label>What is different about this one</label>
    <textarea id="devNote" placeholder="This is what makes it a variation rather than a copy — it is appended to the brief and steers whatever gets regenerated."></textarea></div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="devDlg.close()">Cancel</button>
    <button type="button" class="primary" id="devGo">Create</button>
  </div>
</form></dialog>

<dialog id="revDlg"><form method="dialog">
  <h3 style="margin:0 0 6px">Revise</h3>
  <p class="muted" style="margin:0 0 14px;font-size:12px" id="revHint"></p>
  <div><label>What</label><select id="revWhat"></select></div>
  <div style="margin-top:12px"><label>Scenes (blank = all that need it)</label>
    <div class="row" id="revScenes"></div></div>
  <div style="margin-top:12px"><label>Note — this steers the regeneration</label>
    <textarea id="revNote" placeholder="e.g. she starts already lying on her side"></textarea></div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="revDlg.close()">Cancel</button>
    <button type="button" class="primary" id="revGo">Send back</button>
  </div>
</form></dialog>

<script>
const $=(s,r=document)=>r.querySelector(s);
let STATE=null, CUR=null, DETAIL=null, TIMER=null;

const fmt=n=>(n==null?'—':Number(n).toLocaleString(undefined,{maximumFractionDigits:1})+' cr');
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));

async function api(url,opts){
  const r=await fetch(url,opts);
  const j=await r.json().catch(()=>({error:'bad response'}));
  if(!r.ok) throw new Error(j.error||('HTTP '+r.status));
  return j;
}
// Polling used to rebuild the whole page every four seconds whether or not
// anything had moved -- which restarted the draft video, collapsed open panels
// and made the page twitch. A gate is exactly when a producer sits and watches,
// and exactly when the job is NOT changing, so the common case is now no render
// at all.
let LAST_RENDER=null, LAST_SIDE=null;
function signature(d){
  return JSON.stringify([d, (STATE.activity||[]).filter(a=>a.job_id===d.id)]);
}
async function refresh(){
  try{
    STATE=await api('/api/state');
    const side=JSON.stringify(STATE.jobs)+'|'+CUR+'|'+(STATE.busy||'');
    if(side!==LAST_SIDE){ LAST_SIDE=side; renderSide(); }
    if(CUR){
      DETAIL=await api('/api/jobs/'+CUR);
      const sig=signature(DETAIL);
      if(sig!==LAST_RENDER){ LAST_RENDER=sig; renderMain(); }
    }
  }catch(e){ console.error(e); }
}
function pillClass(s,gateReady){
  if(s==='done')return 'done'; if(s==='failed')return 'bad';
  if(STATE&&STATE.gates.includes(s))return 'gate';
  if(STATE&&STATE.terminal.includes(s))return '';
  return 'run';
}
function renderSide(){
  $('#workerline').textContent = STATE.busy ? ('working on '+STATE.busy) : 'idle';
  $('#joblist').innerHTML = STATE.jobs.map(j=>`
    <div class="jobcard ${j.id===CUR?'sel':''}" onclick="select('${j.id}')">
      <div class="idline"><span class="jid">${esc(j.id)}</span>
        <span class="pill ${pillClass(j.state)}">${esc(j.state)}</span></div>
      <div class="sub">${esc(j.vertical||'')} · w${esc(j.week||'?')} · ${fmt(j.spent)}
        ${j.busy?' · <span style="color:var(--live)">working</span>':''}</div>
    </div>`).join('') || '<div class="empty">No jobs yet.</div>';
}
async function select(id){
  CUR=id; DETAIL=await api('/api/jobs/'+id);
  DRAFT_NODE=null; DRAFT_SRC=null;          // a different job, a different cut
  LAST_RENDER=signature(DETAIL); renderMain();
  LAST_SIDE=null; renderSide();
}

function track(state){
  const idx=STATE.pipeline.indexOf(state);
  return '<div class="track">'+STATE.pipeline.map((s,i)=>{
    const gate=STATE.gates.includes(s);
    let cls='step'+(gate?' gate':'');
    if(idx>=0&&i<idx)cls+=' past'; else if(s===state)cls+=' now';
    return `<span class="${cls}">${esc(s)}</span>`;
  }).join('')+'</div>';
}
function qaBadge(q){
  if(!q) return '<span class="qa">no QA</span>';
  const extra=q.technical?' tech':(q.speech_only?' silent-ok':'');
  return `<span class="qa ${esc(q.severity)}">${esc(q.severity)}${extra}</span>`;
}
function sceneCard(s,kind){
  const media = kind==='clip'&&s.clip
    ? `<video src="/media/${CUR}/${s.clip}" muted preload="metadata"
        onmouseover="this.play()" onmouseout="this.pause();this.currentTime=0"></video>`
    : (s.plate?`<img src="/media/${CUR}/${s.plate}" loading="lazy">`:'<span class="muted">—</span>');
  const qa = kind==='clip'?s.clip_qa:s.plate_qa;
  const tries = kind==='clip'?s.clip_attempts:s.plate_attempts;
  const prompt = kind==='clip'?s.video_prompt:s.image_prompt;
  return `<div class="scene"><div class="media">${media}</div>
    <div class="meta"><div class="row" style="justify-content:space-between">
      <b>scene ${s.idx}</b><span>${qaBadge(qa)}</span></div>
      <div class="muted" style="font-size:11px;margin-top:3px">
        ${s.duration_s}s · ${tries||0} attempt${tries===1?'':'s'}</div>
      <div class="prompt">${esc((prompt||'').slice(0,150))}</div>
      ${qa&&qa.issues&&qa.issues.length?`<div class="prompt" style="color:var(--warn)">
        ${qa.issues.map(i=>esc(i)).join(' · ')}</div>`:''}
    </div></div>`;
}
// The producer's edit, held locally between renders: the page polls every few
// seconds and a select that resets itself mid-decision is unusable. Re-seeded
// when the job or its state changes, which is what a completed re-cut looks
// like from here.
let EDIT=null, EDIT_KEY=null;
function editState(d){
  const key=d.id+'|'+d.state+'|'+(d.busy?'busy':'idle');
  if(EDIT_KEY!==key){ EDIT=JSON.parse(JSON.stringify(d.edit||{})); EDIT_KEY=key; }
  return EDIT;
}
function editDirty(d){
  const a=editState(d), b=d.edit||{};
  return JSON.stringify([a.order,a.music,a.subtitles])!==
         JSON.stringify([b.order,b.music,b.subtitles]);
}
function moveShot(idx,dir){
  const o=EDIT.order, i=o.indexOf(idx), j=i+dir;
  if(i<0||j<0||j>=o.length) return;
  o[i]=o[j]; o[j]=idx; renderMain(); flashShot(idx);
}
// -- dragging the running order --------------------------------------------
// Pointer events, not HTML5 drag-and-drop. The native API needs a dataTransfer
// dance, ignores touch entirely, and cannot be driven by synthetic input --
// which means it cannot be tested, and an editor whose gesture nobody can
// verify is how the arrow buttons got shipped looking dead. This follows the
// pointer directly: mouse, trackpad and touch all work, and so does a test.
//
// The strip is NOT re-rendered mid-drag: a ghost follows the pointer and the
// landing place is drawn on the neighbour with a class. Replacing the element
// under the pointer would end the gesture.
let DRAG=null;                      // {idx, x0, y0, moved, ghost}
const DRAG_SLOP=4;                  // px before a press becomes a drag, not a click

function clearDrop(){
  document.querySelectorAll('.shot.dropL,.shot.dropR')
    .forEach(e=>e.classList.remove('dropL','dropR'));
  document.querySelectorAll('.shots.over,.tray.over')
    .forEach(e=>e.classList.remove('over'));
}
function shotDown(ev,idx){
  if(ev.button!==0||ev.target.closest('button')) return;
  // no setPointerCapture: the move/up listeners are on `document`, so capture
  // buys nothing -- and it throws on an id it does not recognise, which would
  // raise inside the handler and leave the gesture half-started
  DRAG={idx:idx,x0:ev.clientX,y0:ev.clientY,moved:false,ghost:null};
}
function shotMove(ev){
  if(!DRAG) return;
  if(!DRAG.moved){
    if(Math.abs(ev.clientX-DRAG.x0)+Math.abs(ev.clientY-DRAG.y0)<DRAG_SLOP) return;
    DRAG.moved=true;
    const src=document.querySelector(`.shot[data-shot="${DRAG.idx}"]`);
    if(src){
      const box=src.getBoundingClientRect();
      const g=src.cloneNode(true);
      g.className='shot ghost';
      Object.assign(g.style,{position:'fixed',width:box.width+'px',left:'0',top:'0',
        pointerEvents:'none',zIndex:'50',opacity:'.9',
        transform:`translate(${box.left}px,${box.top}px)`});
      g.dataset.dx=(DRAG.x0-box.left); g.dataset.dy=(DRAG.y0-box.top);
      document.body.appendChild(g);
      DRAG.ghost=g; src.classList.add('dragging');
    }
    document.body.style.userSelect='none';
  }
  ev.preventDefault();
  if(DRAG.ghost){
    DRAG.ghost.style.transform=
      `translate(${ev.clientX-DRAG.ghost.dataset.dx}px,${ev.clientY-DRAG.ghost.dataset.dy}px)`;
  }
  const under=document.elementFromPoint(ev.clientX,ev.clientY);
  const chip=under&&under.closest?under.closest('.shot:not(.ghost)'):null;
  const tray=under&&under.closest?under.closest('.tray'):null;
  const strip=under&&under.closest?under.closest('.shots'):null;
  clearDrop();
  if(chip&&+chip.dataset.shot!==DRAG.idx&&!chip.classList.contains('out')){
    const box=chip.getBoundingClientRect();
    chip.classList.add((ev.clientX-box.left)>box.width/2?'dropR':'dropL');
  }else if(tray&&EDIT.order.includes(DRAG.idx)){ tray.classList.add('over'); }
  else if(strip){ strip.classList.add('over'); }
}
function shotUp(ev){
  if(!DRAG) return;
  const d=DRAG, under=document.elementFromPoint(ev.clientX,ev.clientY);
  endDrag();
  if(!d.moved) return;                          // a press that never moved is a click
  const chip=under&&under.closest?under.closest('.shot:not(.ghost)'):null;
  const tray=under&&under.closest?under.closest('.tray'):null;
  if(chip&&+chip.dataset.shot!==d.idx&&!chip.classList.contains('out')){
    const box=chip.getBoundingClientRect();
    placeShot(d.idx,+chip.dataset.shot,(ev.clientX-box.left)>box.width/2);
  }else if(tray){ dropShot(d.idx); }
  else if(under&&under.closest&&under.closest('.shots')){ placeShot(d.idx,null,true); }
}
function endDrag(){
  if(DRAG&&DRAG.ghost) DRAG.ghost.remove();
  DRAG=null; clearDrop();
  document.body.style.userSelect='';
  document.querySelectorAll('.shot.dragging').forEach(e=>e.classList.remove('dragging'));
}
document.addEventListener('pointermove',shotMove,{passive:false});
document.addEventListener('pointerup',shotUp);
document.addEventListener('pointercancel',endDrag);
document.addEventListener('keydown',e=>{ if(e.key==='Escape'&&DRAG) endDrag(); });

function placeShot(idx,target,after){
  const o=EDIT.order.filter(i=>i!==idx);
  let at=(target===null)?o.length:o.indexOf(target)+(after?1:0);
  if(at<0) at=o.length;
  o.splice(at,0,idx);
  EDIT.order=o;
  renderMain(); flashShot(idx);
}
// Dragging is the gesture; the keys are here so the strip is still usable
// without one, and cost nothing on screen.
function shotKey(ev,idx){
  const k=ev.key;
  if(k==='ArrowLeft'||k==='ArrowRight'){
    ev.preventDefault(); moveShot(idx,k==='ArrowLeft'?-1:1);
    const el=document.querySelector(`.shot[data-shot="${idx}"]`); if(el) el.focus();
  }else if(k==='Backspace'||k==='Delete'){ ev.preventDefault(); dropShot(idx); }
}
function flashShot(idx){
  const el=document.querySelector(`.shot[data-shot="${idx}"]`);
  if(!el) return;
  el.classList.add('moved');
  setTimeout(()=>el.classList.remove('moved'),700);
}
function dropShot(idx){
  if(EDIT.order.length<2){ alert('A cut needs at least one shot.'); return; }
  EDIT.order=EDIT.order.filter(i=>i!==idx); renderMain();
}
function restoreShot(idx){
  // back where the plan had it, not on the end: a restored shot belongs in
  // story order unless the producer moves it
  EDIT.order=[...EDIT.order,idx].sort((a,b)=>a-b); renderMain();
}
function setEdit(k,v){ EDIT[k]=v; renderMain(); }
function setSubs(k,v){ EDIT.subtitles={...EDIT.subtitles,[k]:v}; renderMain(); }
function resetEdit(){ EDIT=null; EDIT_KEY=null; renderMain(); }
async function applyEdit(){
  const d=DETAIL, recut=d.state==='GATE_DRAFT';
  await act('edit',{edit:{order:EDIT.order,music:EDIT.music,subtitles:EDIT.subtitles},
                    recut:recut});
}
// The bed library is filed by mood, and its names carry the folder. A flat list
// of 109 is not something a producer can choose from, so the folder becomes an
// <optgroup> and the option shows only the bed's own name.
function musicOptions(library, current, firstLabel){
  const groups = new Map();
  for(const name of (library||[])){
    const cut = name.lastIndexOf('/');
    const folder = cut < 0 ? 'Loose' : name.slice(0, cut);
    const leaf = cut < 0 ? name : name.slice(cut + 1);
    if(!groups.has(folder)) groups.set(folder, []);
    groups.get(folder).push([name, leaf]);
  }
  // A bed recorded before the library was filed keeps its bare name, which is
  // not in the list any more -- it is shown as-is rather than dropped, and
  // labelled "as recorded" rather than "missing": it still resolves, the job
  // simply predates the folders.
  let html = firstLabel;
  if(current && !(library||[]).includes(current))
    html += `<option value="${esc(current)}" selected>${esc(current)} (as recorded)</option>`;
  for(const [folder, items] of [...groups.entries()].sort())
    html += `<optgroup label="${esc(folder)}">`
      + items.map(([value, leaf]) =>
          `<option value="${esc(value)}" ${value===current?'selected':''}>${esc(leaf)}</option>`).join('')
      + `</optgroup>`;
  return html;
}

function editorCard(d){
  if(!(d.edit&&d.edit.open)) return '';
  const e=editState(d), busy=d.busy, dirty=editDirty(d);
  const byIdx=Object.fromEntries(d.scenes.map(s=>[s.idx,s]));
  const out=d.scenes.map(s=>s.idx).filter(i=>!e.order.includes(i));
  const chip=(idx,pos)=>{
    const s=byIdx[idx]||{}, inCut=pos>=0;
    // the plate, not the clip: a still loads instantly and is what the producer
    // recognises the shot by. Without it the strip is five identical boxes.
    const thumb=s.plate?`<img src="/media/${CUR}/${s.plate}" loading="lazy">`
      :(s.clip?`<video src="/media/${CUR}/${s.clip}" muted preload="metadata"></video>`
      :'<span class="muted">—</span>');
    const drag=busy?'':`onpointerdown="shotDown(event,${idx})" draggable="false"
      ondragstart="return false" tabindex="0" onkeydown="shotKey(event,${idx})"`;
    return `<div class="shot ${inCut?'':'out'}" data-shot="${idx}" ${drag}
      title="${inCut?'drag to move it in the running order':'drag it into the cut'}">
      <div class="thumb">${thumb}</div>
      <div class="n">${inCut?pos+1+'.':'—'} scene ${idx}</div>
      <div class="muted" style="font-size:11px;margin-top:2px">
        ${s.duration_s?esc(s.duration_s)+'s':''} ${qaBadge(s.clip_qa)}</div>
      ${inCut?`<button class="x" ${busy?'disabled':''} onclick="dropShot(${idx})"
        title="take it out of the cut">✕</button>`
      :`<button class="x" style="opacity:1" ${busy?'disabled':''}
        onclick="restoreShot(${idx})" title="put it back in the cut">+</button>`}
      </div>`;
  };
  const sel=(val,opts,on)=>`<select ${busy?'disabled':''} onchange="${on}">
    ${opts.map(o=>`<option value="${esc(o[0])}" ${o[0]===val?'selected':''}>${esc(o[1])}</option>`).join('')}
    </select>`;
  const subs=e.subtitles||{};
  return `<div class="card"><h3>The edit — re-cutting costs nothing</h3>
    <div class="muted" style="font-size:12px;margin:-4px 0 10px">
      Drag a shot to move it in the running order, or out of the strip to drop it.
      ${d.state==='GATE_DRAFT'
        ? 'The player above keeps the old cut until you apply.'
        : 'The cut is made when you approve this gate.'}</div>
    <div class="shots">${e.order.map((i,p)=>chip(i,p)).join('')}</div>
    <div class="tray">
      <span class="lbl">${out.length?'Not in the cut':'Drag a shot here to take it out'}</span>
      ${out.map(i=>chip(i,-1)).join('')}</div>
    <div class="row" style="gap:18px">
      <div><label>Music bed</label>
        <select ${busy?'disabled':''} onchange="setEdit('music',this.value)">
          ${musicOptions(e.music_library, e.music||'',
            `<option value="" ${e.music?'':'selected'}>— none —</option>`)}
        </select></div>
      <div><label>Subtitles</label>
        ${sel(subs.enabled?'on':'off',[['on','burned in'],['off','none']],
              'setSubs(\'enabled\',this.value===\'on\')')}</div>
      <div><label>Colour</label>
        ${sel(subs.colour||'yellow',(d.edit.subtitle_colours||[]).map(c=>[c,c]),
              'setSubs(\'colour\',this.value)')}</div>
      <div><label>Size</label>
        ${sel(subs.size||'medium',(d.edit.subtitle_sizes||[]).map(c=>[c,c]),
              'setSubs(\'size\',this.value)')}</div>
    </div>
    <div class="row" style="margin-top:14px">
      <button class="primary" ${busy||!dirty?'disabled':''} onclick="applyEdit()">
        ${d.state==='GATE_DRAFT'?'Apply and re-cut':'Apply to this cut'}</button>
      <button ${busy||!dirty?'disabled':''} onclick="resetEdit()">Discard changes</button>
      <span class="muted" style="font-size:12px">
        ${dirty?(d.state==='GATE_DRAFT'
            ? 'Re-cuts the draft — ffmpeg only, nothing is bought again.'
            : 'Applied when you approve this gate, which is what cuts the draft.')
          :'Nothing changed yet.'}</span>
    </div></div>`;
}

function renderMain(){
  const d=DETAIL, atGate=STATE.gates.includes(d.state);
  const f=d.next_forecast;
  const showClips=STATE.pipeline.indexOf(d.state)>=STATE.pipeline.indexOf('clips');
  let html='';
  html+=`<div class="head"><div>
      <h2>${esc(d.id)} <span class="pill ${pillClass(d.state)}">${esc(d.state)}</span></h2>
      <div class="muted" style="margin-top:5px">${esc(d.intake.vertical||'')} ·
        week ${esc(d.intake.week)} · c-${esc(d.intake.concept)} ·
        pr-${esc(d.intake.producer||'lp')}
        ${d.intake.packshot?' · packshot '+esc(d.intake.packshot):''}
        ${(d.edit&&d.edit.music)?' · music '+esc(d.edit.music):''}</div></div>
    <div style="text-align:right"><div class="money">${fmt(d.spent)}</div>
      <div class="muted" style="font-size:11px">
        ${Object.entries(d.spent_by_backend).map(([k,v])=>esc(k)+' '+fmt(v)).join(' · ')||'nothing spent'}</div>
    </div></div>`;
  if(d.derived_from) html+=`<div class="card" style="padding:10px 14px">
    <span class="muted" style="font-size:12px">derived from
    <a href="#" onclick="select('${esc(d.derived_from)}');return false">${esc(d.derived_from)}</a>
    at '${esc(d.meta.derived_from_stage||'')}'
    ${d.meta.inherited?` · inherited ${fmt(d.meta.inherited.inherited_credits)} of work`:''}</span></div>`;
  if((d.derivatives||[]).length) html+=`<div class="card" style="padding:10px 14px">
    <span class="muted" style="font-size:12px">variations:
    ${d.derivatives.map(v=>`<a href="#" onclick="select('${esc(v)}');return false">${esc(v)}</a>`).join(', ')}</span></div>`;
  if(d.error) html+=`<div class="err"><b>failed:</b> ${esc(d.error)}</div>`;
  // an action can fail WITHOUT changing job state -- approving off a gate, a bad
  // revise target. Those were recorded by the API and shown nowhere.
  const mine=(STATE.activity||[]).filter(a=>a.job_id===d.id);
  const lastFail=mine.find(a=>a.state==='failed');
  if(lastFail && !(mine[0]&&mine[0].state==='done'&&mine[0].finished_at>lastFail.finished_at))
    html+=`<div class="err"><b>${esc(lastFail.action)} did not run:</b> ${esc(lastFail.detail)}</div>`;
  if(d.open_submissions.length) html+=`<div class="err">
    ${d.open_submissions.length} paid generation(s) submitted and not collected —
    these cannot be cancelled upstream. Retry to collect them.</div>`;
  html+=track(d.state);

  html+='<div class="card"><h3>Actions</h3><div class="row">';
  const busy=d.busy;
  if(atGate){
    html+=`<button class="primary" ${busy?'disabled':''} onclick="openApprove()">Approve ${esc(d.state)}</button>`;
    html+=`<button ${busy?'disabled':''} onclick="openRevise()">Revise…</button>`;
  } else if(d.state==='failed'){
    html+=`<button class="primary" ${busy?'disabled':''} onclick="act('retry')">Retry</button>`;
  } else if(!STATE.terminal.includes(d.state)){
    html+=`<button class="primary" ${busy?'disabled':''} onclick="act('run')">Run</button>`;
  }
  if(d.scenes.some(s=>s.clip)&&!atGate)
    html+=`<button ${busy?'disabled':''} onclick="act('reassemble')">Re-cut (free)</button>`;
  if((d.derive||[]).length)
    html+=`<button ${busy?'disabled':''} onclick="openDerive()">Make a variation…</button>`;
  if(!STATE.terminal.includes(d.state)||d.state==='failed')
    html+=`<button class="danger" ${busy?'disabled':''} onclick="act('cancel')">Cancel</button>`;
  if(busy) html+='<span class="muted">queued…</span>';
  html+='</div></div>';

  if(atGate&&f){
    const warn=!f.complete;
    html+=`<div class="card"><h3>Cost of the next stage — approve this and it is spent</h3>
      <div class="money ${warn?'warn':''}">${fmt(f.total)}${warn?' +':''}</div>
      ${warn?`<div class="muted" style="margin-top:6px">Incomplete: no measured rate for
        ${f.unpriced.map(esc).join(', ')}. The figure is a floor, not the price.</div>`
      :`<div class="muted" style="margin-top:6px">${f.items.length} item(s), all priced from measured rates.</div>`}
      </div>`;
  }
  const draft=(d.artifacts.draft||[]).find(p=>p.endsWith('draft.mp4'));
  if(draft&&d.state==='GATE_DRAFT'){
    // a SLOT, not a <video> tag: the element itself is kept alive across
    // re-renders by mountDraft(), or a poll would restart playback
    const stale=d.edit&&d.edit.open&&editDirty(d);
    html+=`<div class="card"><h3>The cut</h3>
      ${stale?`<div class="stale">This is the <b>old</b> cut — the player does not
        change until you apply the edit below. Nothing is bought when it does.</div>`:''}
      <div id="draftSlot"></div>
      <div class="muted" style="margin-top:8px;font-size:12px">
        ${d.meta.draft?`${d.meta.draft.duration_s}s · ${d.meta.draft.subtitle_lines||0} subtitle lines
        · crossfade ${d.meta.draft.crossfade_s||0}s
        · ${d.meta.draft.music?('music '+esc(d.meta.draft.music)):'no music'}`:''}</div></div>`;
  }
  html+=editorCard(d);
  if(d.scenes.length){
    html+=`<div class="card"><h3>Plates</h3><div class="grid scenes">
      ${d.scenes.map(s=>sceneCard(s,'plate')).join('')}</div></div>`;
    if(showClips&&d.scenes.some(s=>s.clip)){
      const cut=(d.edit&&d.edit.open)?editState(d).order:null;
      html+=`<div class="card"><h3>Clips — hover to play</h3><div class="grid scenes">
        ${d.scenes.map(s=>{
          const card=sceneCard(s,'clip');
          return (cut&&!cut.includes(s.idx))
            ? card.replace('class="scene', 'style="opacity:.42" class="scene')
                  .replace('</div></div>', '<div class="muted" style="font-size:11px;'
                           +'margin-top:5px">not in the cut</div></div></div>')
            : card;
        }).join('')}</div></div>`;
    }
  }
  if((d.finals||[]).length) html+=`<div class="card"><h3>Finals</h3>
    ${d.week_dir?`<div class="muted" style="font-size:12px;margin-bottom:12px">
      delivered to ${esc(d.week_dir)}</div>`:''}
    <div class="grid finals">${d.finals.map(f=>`<div>
      <video class="final" src="/media/${CUR}/${f.rel}" controls preload="metadata"></video>
      <div class="muted" style="font-size:11px;margin-top:6px;word-break:break-all">
        <b style="color:var(--ink)">${esc(f.format||'')}</b>
        ${f.actual?` · ${f.actual[0]}×${f.actual[1]}`:''}
        ${f.duration_s?` · ${f.duration_s}s`:''}
        ${f.subtitle_lines?` · ${f.subtitle_lines} subs`:''}
        <div style="margin-top:3px">${esc(f.file)}</div>
        <a href="/media/${CUR}/${f.rel}" download="${esc(f.file)}">download</a>
      </div></div>`).join('')}</div></div>`;
  if(d.ledger.length) html+=`<div class="card"><h3>Ledger</h3><table>
    <tr><th>stage</th><th>item</th><th>backend</th><th class="num">credits</th></tr>
    ${d.ledger.map(l=>`<tr><td>${esc(l.stage)}</td><td>${esc(l.item)}</td>
      <td class="muted">${esc(l.backend)}</td><td class="num">${fmt(l.credits)}</td></tr>`).join('')}
    </table></div>`;
  if(d.analysis) html+=`<div class="card"><h3>Reference analysis</h3>
    <details><summary class="muted" style="cursor:pointer;font-size:12px">
      what the model read off the reference (${d.analysis.length} chars)</summary>
    <pre style="white-space:pre-wrap;font:12px/1.55 ui-monospace,Menlo,monospace;
      color:var(--dim);margin:10px 0 0;max-height:340px;overflow:auto">${esc(d.analysis)}</pre>
    </details></div>`;
  if(d.scenes.length&&d.scenes[0].video_prompt) html+=`<div class="card"><h3>Prompts</h3>
    <details><summary class="muted" style="cursor:pointer;font-size:12px">
      the ${d.scenes.length} scene prompts as written</summary>
    ${d.scenes.map(s=>`<div style="margin-top:12px;padding-top:10px;
      border-top:1px solid var(--line)"><b>scene ${s.idx}</b> · ${s.duration_s}s
      <div class="muted" style="font-size:12px;margin-top:5px"><b>plate:</b> ${esc(s.image_prompt)}</div>
      <div class="muted" style="font-size:12px;margin-top:5px"><b>motion:</b> ${esc(s.video_prompt)}</div>
      </div>`).join('')}</details></div>`;
  html+=`<div class="card"><h3>Events</h3><div class="log">
    ${d.events.map(e=>`<div><b>${esc(e.type)}</b> ${esc(e.msg||'')}</div>`).join('')}</div></div>`;
  const openCards=[...document.querySelectorAll('.card details[open]')]
    .map(x=>x.closest('.card').querySelector('h3').textContent);
  $('#main').innerHTML=html;
  mountDraft(draft&&d.state==='GATE_DRAFT'?draft:null);
  // an expanded panel that collapses itself every four seconds is its own
  // small version of the same bug
  document.querySelectorAll('.card details').forEach(x=>{
    if(openCards.includes(x.closest('.card').querySelector('h3').textContent))
      x.open=true;
  });
}

// The one <video> the producer actually watches. Created once per source and
// re-parented on every render, so a poll cannot take it away mid-playback.
let DRAFT_NODE=null, DRAFT_SRC=null;
function mountDraft(rel){
  const slot=$('#draftSlot');
  if(!rel||!slot){ return; }
  const src=`/media/${CUR}/${rel}`;
  if(!DRAFT_NODE||DRAFT_SRC!==src){
    DRAFT_NODE=document.createElement('video');
    DRAFT_NODE.className='draft';
    DRAFT_NODE.controls=true;
    DRAFT_NODE.preload='metadata';
    DRAFT_NODE.src=src;
    DRAFT_SRC=src;
  }
  if(DRAFT_NODE.parentNode!==slot) slot.appendChild(DRAFT_NODE);
}
async function act(action,payload){
  try{ await api(`/api/jobs/${CUR}/${action}`,{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(payload||{})});
    LAST_RENDER=null;
    await refresh();
  }catch(e){ alert(e.message); }
}
let DERIVE_FROM='assembly';
function openDerive(){
  const d=DETAIL, o=STATE.options;
  devDlg.showModal();
  $('#devHint').textContent=`Inherits everything ${d.id} already paid for, up to the `
    +`point you start from. The reference does not need uploading again.`;
  $('#devErr').innerHTML='';
  $('#devName').value=d.derive_name
    ||(d.intake.creative_name||'').replace(/n-[A-Za-z0-9]+/,'n-'+(d.next_id||''));
  $('#devPackshot').innerHTML='<option value="">same as parent</option>'
    +o.packshots.map(p=>`<option>${esc(p)}</option>`).join('');
  $('#devMusic').innerHTML=musicOptions(o.music, '',
    '<option value="">same as parent</option><option value="none">no music</option>');
  $('#devXfade').value=''; $('#devNote').value='';
  $('#devRecast').value=''; $('#devCastDesc').value='';
  $('#devRecast').onchange=()=>{
    $('#devCastDesc').style.display=$('#devRecast').value?'block':'none';
  };
  renderCastRow();
  DERIVE_FROM=(d.derive[0]||{}).from||'assembly';
  renderDeriveOptions();
  readDeriveName();
}
function renderDeriveOptions(){
  const labels={assembly:'Re-cut only — same clips, different edit',
                clips:'New clips — same plates, new motion',
                plates:'New plates — same prompts, new pictures',
                prompts:'Rewrite — same analysis, new script'};
  $('#devFrom').innerHTML=DETAIL.derive.map(o=>`
    <label class="opt ${o.from===DERIVE_FROM?'sel':''}" onclick="DERIVE_FROM='${o.from}';renderDeriveOptions()">
      <span class="price">${o.cost>0?fmt(o.cost)+(o.cost_complete?'':' +'):'free'}</span>
      ${esc(labels[o.from]||o.from)}
      <div class="muted" style="font-size:11px;margin-top:3px">
        keeps ${o.keeps.map(esc).join(', ')}${o.rebuys.length?` · re-buys ${o.rebuys.map(esc).join(' + ')}`:''}</div>
    </label>`).join('');
  renderCastRow();
}
// Who the variation stars is only a question when the plates are re-bought.
// Inherit them and the face is already fixed; re-buy them and the pipeline
// cannot guess whether this is another cut of the same creative or a new test
// with a new host -- so it asks instead of choosing.
function renderCastRow(){
  const row=$('#devCastRow');
  if(!row) return;
  const cast=(DETAIL&&DETAIL.cast)||[];
  const rebuys=(DETAIL.derive||[]).find(o=>o.from===DERIVE_FROM);
  const asks=cast.length && rebuys && rebuys.rebuys.includes('plates');
  row.style.display=asks?'block':'none';
  if(asks) $('#devCastHint').textContent=
    `${cast.map(c=>c.id).join(', ')} — the parent's portrait${cast.length>1?'s':''} `
    + `${cast.length>1?'are':'is'} reused unless you ask for a new face.`;
}
function readDeriveName(){
  const el=$('#devRead');
  const raw=$('#devName').value.trim().replace(/\.(mp4|mov|m4v|webm)$/i,'');
  const m=NAME_RE.exec(raw);
  if(!m){ el.className='hint bad'; el.textContent='not a creative name'; return null; }
  el.className='hint';
  el.innerHTML=`<b>${esc(m[1])}</b> · week ${esc(m[7])} · c-${esc(m[4])} · pr-${esc(m[5])}`;
  return m[1];
}
$('#devName').addEventListener('input',readDeriveName);
$('#devGo').onclick=async()=>{
  if(!readDeriveName()){
    $('#devErr').innerHTML='<div class="err">Give the variation its own creative name.</div>';
    return; }
  const body={creative_name:$('#devName').value.trim(), from:DERIVE_FROM,
    note:$('#devNote').value, run:true};
  if($('#devPackshot').value) body.packshot=$('#devPackshot').value;
  if($('#devRecast').value){
    body.recast=true;
    const desc=$('#devCastDesc').value.trim();
    // one cast member is the normal case; with more, the note steers the rest
    if(desc && (DETAIL.cast||[]).length) body.cast_descriptions={[DETAIL.cast[0].id]:desc};
  }
  if($('#devMusic').value) body.music=($('#devMusic').value==='none'?'':$('#devMusic').value);
  if($('#devXfade').value!=='') body.crossfade_s=$('#devXfade').value;
  try{
    const r=await api(`/api/jobs/${CUR}/derive`,{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    devDlg.close(); LAST_SIDE=null; await refresh(); select(r.id);
  }catch(e){ $('#devErr').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
};

function openApprove(){
  const d=DETAIL, f=d.next_forecast;
  $('#okTitle').textContent='Approve '+d.state;
  if(f&&f.total>0){
    $('#okHint').textContent='This commits the next stage. Generations cannot be '
      +'cancelled once submitted.';
    $('#okCost').innerHTML=`<div class="card" style="margin:0;background:var(--panel2)">
      <div class="money ${f.complete?'':'warn'}">${fmt(f.total)}${f.complete?'':' +'}</div>
      <div class="muted" style="font-size:12px;margin-top:4px">
        ${f.complete?`${f.items.length} item(s), every one priced from a measured rate.`
        :`No measured rate for ${f.unpriced.map(esc).join(', ')} — this is a floor, not the price.`}
      </div></div>`;
    $('#okGo').textContent='Spend '+fmt(f.total);
  } else {
    $('#okHint').textContent='Nothing after this gate costs credits — it is all ffmpeg.';
    $('#okCost').innerHTML='';
    $('#okGo').textContent='Approve';
  }
  $('#okNote').value='';
  okDlg.showModal();
}
$('#okGo').onclick=async()=>{ const note=$('#okNote').value; okDlg.close();
  await act('approve',{note}); };

function openRevise(){
  const d=DETAIL;
  $('#revHint').textContent=`At ${d.state}. Anything you send back re-runs forward and stops here again.`;
  $('#revWhat').innerHTML=d.revisable.map(w=>`<option>${esc(w)}</option>`).join('');
  $('#revScenes').innerHTML=d.scenes.map(s=>
    `<label style="display:flex;gap:5px;align-items:center;text-transform:none;
      letter-spacing:0;font-size:13px;color:var(--ink);width:auto">
      <input type="checkbox" value="${s.idx}" style="width:auto"> ${s.idx}</label>`).join('');
  $('#revNote').value='';
  revDlg.showModal();
}
$('#revGo').onclick=async()=>{
  const scenes=[...document.querySelectorAll('#revScenes input:checked')].map(i=>+i.value);
  revDlg.close();
  await act('revise',{what:$('#revWhat').value,note:$('#revNote').value,scenes});
};
// The browser will not hand over a dropped file's path -- there isn't one to
// give -- so the bytes are uploaded and the server answers with a path it can
// actually read. It probes the file too, which is why the size line can say
// what the reference is before a job exists.
let UPLOAD=null;
function resetDrop(){
  UPLOAD=null;
  const d=$('#drop'); d.classList.remove('has','over');
  d.innerHTML=`<div class="big">Drop the reference video here</div>
    <div class="hint">or click to choose &middot; mp4, mov, m4v, webm, avi, mkv</div>
    <div class="bar" id="dropBar" style="display:none"><i></i></div>`;
}
function dropBusy(pct){
  const d=$('#drop');
  d.innerHTML=`<div class="big">Uploading…</div>
    <div class="hint">${pct}%</div>
    <div class="bar"><i style="width:${pct}%"></i></div>`;
}
function dropDone(u){
  const mb=(u.size/1048576).toFixed(1);
  $('#drop').classList.add('has');
  $('#drop').innerHTML=`<div class="big">${esc(u.name)}</div>
    <div class="hint">${u.duration_s}s &middot; ${u.width}&times;${u.height}
      &middot; ${mb} MB &middot; ${u.has_audio?'has audio':'<span style="color:var(--warn)">no audio track</span>'}</div>
    <div style="margin-top:9px"><button type="button" onclick="resetDrop()"
      style="padding:4px 10px;font-size:12px">Choose another</button></div>`;
}
function uploadRef(file){
  if(!file) return;
  dropBusy(0);
  const xhr=new XMLHttpRequest();
  xhr.open('POST','/api/uploads');
  xhr.setRequestHeader('X-Filename',file.name);
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=e=>{ if(e.lengthComputable) dropBusy(Math.round(e.loaded/e.total*100)); };
  xhr.onload=()=>{
    let r={}; try{ r=JSON.parse(xhr.responseText); }catch(e){}
    if(xhr.status>=400||r.error){
      resetDrop();
      $('#newErr').innerHTML=`<div class="err">${esc(r.error||('upload failed: HTTP '+xhr.status))}</div>`;
      return;
    }
    $('#newErr').innerHTML=''; UPLOAD=r; dropDone(r);
  };
  xhr.onerror=()=>{ resetDrop();
    $('#newErr').innerHTML='<div class="err">upload failed — is the server still running?</div>'; };
  xhr.send(file);
}
function wireDrop(){
  const d=$('#drop'), input=$('#dropInput');
  d.onclick=()=>{ if(!UPLOAD) input.click(); };
  input.onchange=()=>{ uploadRef(input.files[0]); input.value=''; };
  ['dragenter','dragover'].forEach(ev=>d.addEventListener(ev,e=>{
    e.preventDefault(); if(!UPLOAD) d.classList.add('over'); }));
  ['dragleave','drop'].forEach(ev=>d.addEventListener(ev,e=>{
    e.preventDefault(); d.classList.remove('over'); }));
  d.addEventListener('drop',e=>{ if(!UPLOAD) uploadRef(e.dataTransfer.files[0]); });
  // a file dropped anywhere else would otherwise navigate the page away
  ['dragover','drop'].forEach(ev=>window.addEventListener(ev,e=>e.preventDefault()));
}
wireDrop();

// Mirrors fjor_studio/naming.py -- the server parses it again and is the
// authority; this is only so a typo shows up before anything is created.
// The prefix suggests the vertical; the producer decides it. Once they have
// picked one by hand, re-parsing the name must not quietly put it back.
let VERTICAL_TOUCHED=false;
const NAME_RE=/^n-([A-Za-z0-9]+)_ch-([a-z0-9]+)_t-([a-z0-9]+)_c-([a-z0-9-]+)_pr-([a-z0-9-]+)_ds-([a-z0-9-]+)_w-(\d+)_s-(\d+)x(\d+)$/;
function readName(){
  const el=$('#nameRead');
  const raw=$('#f_name').value.trim().replace(/^["']|["']$/g,'')
    .replace(/\.(mp4|mov|m4v|webm)$/i,'');
  if(!raw){ el.className='hint'; el.textContent=''; return null; }
  const m=NAME_RE.exec(raw);
  if(!m){ el.className='hint bad';
    el.textContent='not a creative name — expected n-ID_ch-…_t-…_c-…_pr-…_ds-…_w-…_s-WxH';
    return null; }
  const [,id,ch,t,concept,pr,ds,week]=m;
  const vert=(STATE.options.prefix_map||{})[(id.match(/^[A-Za-z]+/)||[''])[0].toUpperCase()];
  const sel=$('#f_vertical');
  if(vert && !VERTICAL_TOUCHED && sel && [...sel.options].some(o=>o.value===vert))
    sel.value=vert;
  el.className='hint';
  el.innerHTML=`<b>${esc(id)}</b> · week ${esc(week)} · c-${esc(concept)} · pr-${esc(pr)}`
    +` <span style="opacity:.6">· both sizes are built regardless of the s- you pasted</span>`;
  checkVertical(vert);
  return {id,concept,pr,week,vert};
}
function checkVertical(derived){
  const sel=$('#f_vertical'), warn=$('#vertWarn');
  if(!sel||!warn) return;
  const chosen=sel.value;
  if(!derived||!chosen||chosen===derived){ warn.textContent=''; warn.className='hint'; return; }
  // Not an error -- an adaptation can legitimately target another vertical --
  // but the id and the delivery folder come from different places, so the file
  // would land somewhere its own name does not suggest.
  warn.className='hint bad';
  warn.textContent=`the id prefix says ${derived}, so this will deliver into the `
    +`${chosen} folder under a ${derived} name`;
}

$('#newBtn').onclick=()=>{
  // showModal FIRST: populating the selects used to run before it, so one dead
  // selector threw and the dialog silently never opened -- while the fields it
  // contains still existed in the DOM, which made it look like it had.
  newDlg.showModal();
  const o=STATE.options;
  $('#f_vertical').innerHTML=o.verticals.map(v=>`<option>${esc(v)}</option>`).join('');
  VERTICAL_TOUCHED=false;
  $('#f_packshot').innerHTML='<option value="">none</option>'+o.packshots.map(p=>`<option${p==='formula'?' selected':''}>${esc(p)}</option>`).join('');
  $('#newErr').innerHTML='';
  $('#f_name').value=''; $('#f_brief').value=''; $('#nameRead').textContent='';
  resetDrop();
  setTimeout(()=>$('#f_name').focus(),40);
};
$('#f_name').addEventListener('input',readName);
$('#f_vertical').addEventListener('change',()=>{ VERTICAL_TOUCHED=true; readName(); });
$('#createBtn').onclick=async()=>{
  if(!readName()){
    $('#newErr').innerHTML='<div class="err">Paste the full creative name — it carries '
      +'the id, week, concept and producer.</div>';
    return;
  }
  if(!UPLOAD){
    $('#newErr').innerHTML='<div class="err">Drop a reference video first.</div>';
    return;
  }
  const fd=new FormData($('#newForm')), body={run:true,reference:UPLOAD.path};
  fd.forEach((v,k)=>{ if(v!=='') body[k]=v; });
  try{
    const r=await api('/api/jobs',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    newDlg.close(); await refresh(); select(r.id);
  }catch(e){ $('#newErr').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
};
refresh(); TIMER=setInterval(refresh,4000);
</script></body></html>
"""

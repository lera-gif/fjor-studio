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
/* a tick-and-word, not a field caption: the uppercase field label above would
   make "shot 0" read as a heading for something that is not there */
label.tick{display:inline-flex;align-items:center;gap:6px;font-size:13px;
  white-space:nowrap;flex:0 0 auto;
  text-transform:none;letter-spacing:0;color:var(--ink);margin:0;cursor:pointer}
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
/* a transformation is two 9:16 frames side by side, so the box is twice as
   wide -- squeezing them into one frame's width crops both to slivers */
.scene .media.pair{aspect-ratio:9/8}
.scene .media.pair img{width:50%}
.scene .media.pair img+img{border-left:1px solid var(--accent)}
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
<div id="kitBar"></div>
<input type="file" id="kitInput" accept="application/json,.json" style="display:none">
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
  <div style="margin-top:12px"><label>Source</label>
    <div class="drop" id="drop">
      <div class="big">Drop the reference video, or a client banner</div>
      <div class="hint">or click to choose &middot; a VIDEO is analysed and re-created &middot;
        an IMAGE is expanded to 9:16 and animated</div>
      <div class="bar" id="dropBar" style="display:none"><i></i></div>
    </div>
    <input type="file" id="dropInput" accept="video/*,image/*" style="display:none">
  </div>
  <div id="modeNote" class="hint" style="margin-top:8px;min-height:14px"></div>
  <div id="ugcOnly">
    <div style="margin-top:12px"><label>Reference kind</label>
      <select name="ref_kind" id="f_refkind"></select>
      <div class="hint" id="refKindNote" style="margin-top:4px"></div></div>
    <div style="margin-top:12px"><label>Transformation on camera — optional</label>
      <input name="morph" id="f_morph" spellcheck="false"
        placeholder="what changes in shot, with no cut: e.g. her posture straightens and the swelling goes down">
      <div class="hint" style="margin-top:4px">One shot carries it, and the writer builds
        the creative around it. Two plates are bought for that shot, not one.</div></div>
    <div style="margin-top:12px"><label>Text card in the reference&rsquo;s style — optional</label>
      <textarea name="text_card" id="f_card" style="min-height:52px"
        placeholder="our words, set the way the reference sets its own"></textarea>
      <div class="hint" style="margin-top:4px">The manner is copied; the words are ours.
        Asking for one also asks the analysis about typography.</div></div>
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

<dialog id="wvDlg"><form method="dialog">
  <h3 style="margin:0 0 6px">Accept and ship</h3>
  <p class="muted" style="margin:0 0 14px;font-size:12px">The verdict is kept,
    not deleted: preflight still reports the check as failed, and the finding
    travels into the delivered manifest. Per scene — there is no accept-all.</p>
  <div id="wvErr"></div>
  <div><label>Which shots</label>
    <div id="wvScenes" class="row" style="flex-wrap:wrap;gap:10px"></div></div>
  <div style="margin-top:12px"><label>Why it ships anyway</label>
    <input id="wvNote" placeholder="what you looked at, and why it is acceptable"></div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="wvDlg.close()">Cancel</button>
    <button type="button" class="primary" id="wvGo">Accept</button>
  </div>
</form></dialog>

<dialog id="drvDlg"><form method="dialog" id="drvForm">
  <h3 style="margin:0 0 6px">Put shots on a motion driver</h3>
  <p class="muted" style="margin:0 0 14px;font-size:12px">A slice of someone
    else&rsquo;s creative. Its motion, timing and camera are transferred onto our
    photograph. The driver&rsquo;s own soundtrack never reaches the final.</p>
  <div id="drvErr"></div>
  <div><label>Driver video</label>
    <div class="drop" id="drvDrop" style="padding:18px">
      <div class="big">Drop the cut you want the movement from</div>
      <div class="hint">or click to choose &middot; mp4 or mov</div>
    </div>
    <input type="file" id="drvInput" accept="video/*" style="display:none"></div>
  <div class="formgrid" style="margin-top:12px">
    <div><label>Engine</label><select id="drvEngine">
      <option value="seedance">Seedance video reference — 4-15s, the shot may speak</option>
      <option value="kling-mc-3.0">Kling Motion Control 3.0 — runs as long as the driver, silent</option>
      <option value="kling-mc-2.6">Kling Motion Control 2.6 — runs as long as the driver, silent</option>
    </select></div>
    <div><label>Note (optional)</label><input id="drvNote"
      placeholder="what this movement is"></div>
  </div>
  <div class="hint" id="drvEngineNote" style="margin-top:6px"></div>
  <div style="margin-top:12px"><label>Which shots ride it</label>
    <div id="drvScenes" class="row" style="flex-wrap:wrap;gap:10px"></div></div>
  <div class="row end" style="margin-top:18px">
    <button type="button" onclick="drvDlg.close()">Cancel</button>
    <button type="button" class="primary" id="drvGo">Attach</button>
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
// Keys arrive with the producer. Nothing here ever shows a VALUE -- the page is
// told which providers answered and nothing else, because a key that never
// reaches the browser cannot be copied out of it.
function renderKit(){
  const bar=$('#kitBar'), k=(STATE.options&&STATE.options.keys)||{};
  if(!bar) return;
  const have=k.providers||[];
  bar.innerHTML = have.length
    ? `<div class="muted" style="padding:8px 14px;font-size:11px;
        border-bottom:1px solid var(--line)">keys: ${have.map(esc).join(', ')}
        <span style="opacity:.6">${k.source?'· '+esc(k.source):''}</span>
        <a href="#" onclick="kitInput.click();return false" style="margin-left:6px">replace</a></div>`
    : `<div class="err" style="margin:10px 12px">
        <b>No API keys.</b> Nothing can be generated until a kit is loaded.
        <div style="margin-top:8px"><button onclick="kitInput.click()">Load a kit…</button></div>
        <div class="muted" style="font-size:11px;margin-top:6px">A JSON file of keys.
        It is read into this process and never written to disk — restart and it is gone.</div></div>`;
}
$('#kitInput').onchange=async e=>{
  const f=e.target.files[0]; e.target.value='';
  if(!f) return;
  try{
    const r=await api('/api/kit',{method:'POST',
      headers:{'Content-Type':'application/json'},body:await f.text()});
    await refresh();
    alert('Keys loaded for: '+r.providers.join(', ')
      +'\nHeld in memory only — a restart clears them.');
  }catch(err){ alert('That kit was refused:\n\n'+err.message); }
};

function renderSide(){
  renderKit();
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
  // A transformation is TWO photographs of one shot. Showing only the first
  // hides half of what was bought, and the half that decides whether the morph
  // works is whether they are the same frame.
  const pair = kind!=='clip' && s.plate && s.plate_end;
  const plate = pair
    ? `<img src="/media/${CUR}/${s.plate}" loading="lazy">`
      +`<img src="/media/${CUR}/${s.plate_end}" loading="lazy">`
    : (s.plate?`<img src="/media/${CUR}/${s.plate}" loading="lazy">`:'<span class="muted">—</span>');
  const media = kind==='clip'&&s.clip
    ? `<video src="/media/${CUR}/${s.clip}" muted preload="metadata"
        onmouseover="this.play()" onmouseout="this.pause();this.currentTime=0"></video>`
    : plate;
  const qa = kind==='clip'?s.clip_qa:s.plate_qa;
  const tries = kind==='clip'?s.clip_attempts:s.plate_attempts;
  const prompt = kind==='clip'?s.video_prompt:s.image_prompt;
  return `<div class="scene"><div class="media${pair?' pair':''}">${media}</div>
    <div class="meta"><div class="row" style="justify-content:space-between">
      <b>scene ${s.idx}</b><span>${qaBadge(qa)}</span></div>
      <div class="muted" style="font-size:11px;margin-top:3px">
        ${s.duration_s}s · ${tries||0} attempt${tries===1?'':'s'}
        ${s.driver?` · <b style="color:var(--ink)">driver ${esc(s.driver)}</b>`:''}
        ${s.plate_end?' · <b style="color:var(--ink)">transforms</b>':''}
        ${(s.voice==='vo'&&s.line)?' · line spoken separately':''}</div>
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

// What is stopping the delivery, and the two ways past it. Without this the
// producer sees a gate they cannot approve and no way to act: AW024's remedy
// lived entirely in the CLI, and the error naming it named a command `revise`
// would not accept.
function blockingCard(d){
  const bad=d.blocking||[];
  if(!bad.length) return '';
  const at=STATE.gates.includes(d.state);
  return `<div class="card"><h3>Blocking the delivery</h3>
    ${bad.map(i=>{
      const s=d.scenes.find(x=>x.idx===i)||{}, q=s.clip_qa||{};
      return `<div style="margin-bottom:10px">
        <b>scene ${i}</b> <span class="qa critical">critical</span>
        <div class="muted" style="font-size:12px;margin-top:3px">
          ${(q.issues||[]).map(esc).join(' · ')||'no detail'}</div></div>`;
    }).join('')}
    ${at?`<div class="row" style="margin-top:12px">
      <button ${d.busy?'disabled':''} onclick="openRevise()">Buy it again…</button>
      <button ${d.busy?'disabled':''} onclick="openWaive()">Accept and ship…</button>
    </div>
    <div class="muted" style="font-size:11px;margin-top:8px">
      A fault already in the STILL is not repaired by buying the animation
      again — revise <b>plates</b>, not <b>clip</b>. Accepting keeps the finding
      in the report and in the delivered manifest.</div>`
    :'<div class="muted" style="font-size:12px">Run the job to reach the gate where this can be decided.</div>'}
  </div>`;
}

// Movement has ONE source per shot. A driver is chosen before the plates are
// bought, because the plate of a driven shot is generated as that driver's
// opening frame -- deciding afterwards means re-buying it.
function motionCard(d){
  const drivers=(d.meta&&d.meta.drivers)||[];
  const canAdd=d.state==='GATE_PLAN'&&d.scenes.length&&!d.busy;
  if(!drivers.length&&!canAdd) return '';
  const riders=id=>d.scenes.filter(s=>s.driver===id).map(s=>s.idx);
  return `<div class="card"><h3>Motion drivers</h3>
    ${drivers.length?`<div class="grid" style="gap:10px">${drivers.map(v=>{
      const on=riders(v.id);
      return `<div class="row" style="justify-content:space-between;gap:12px">
        <div><b>${esc(v.id)}</b> <span class="muted">${v.duration_s}s ·
          ${esc(v.engine)}${v.note?' · '+esc(v.note):''}</span>
          <div class="muted" style="font-size:11px;margin-top:2px">from ${esc(v.source)}</div></div>
        <div class="muted" style="font-size:12px">${on.length
          ? 'shot'+(on.length>1?'s':'')+' '+on.join(', ')
          : '<span style="color:var(--warn)">attached to nothing</span>'}</div>
      </div>`; }).join('')}</div>`
    :'<div class="muted" style="font-size:12px">None. Every shot moves on its own.</div>'}
    ${canAdd?`<div style="margin-top:12px"><button onclick="openDriver()">Add a driver…</button>
      <span class="muted" style="font-size:11px;margin-left:8px">before the plates are bought:
      a driven shot&rsquo;s plate IS the driver&rsquo;s opening frame</span></div>`:''}
  </div>`;
}

// Banner mode. The one number that matters is the survival check -- everything
// printed on the banner was approved by a client.
function bannerCard(d){
  const b=(d.meta&&d.meta.banner)||null;
  if(!b) return '';
  const sv=b.survived;
  const src=b.source?`/media/${CUR}/${b.source}`:'';
  return `<div class="card"><h3>Banner</h3>
    <div class="row" style="gap:16px;align-items:flex-start">
      ${src?`<img src="${src}" style="max-width:170px;border-radius:6px">`:''}
      <div class="muted" style="font-size:12px">
        <div>${b.width}&times;${b.height} · ${b.needs_expansion
          ? `${b.placement.top}px painted above, ${b.placement.bottom}px below`
          : 'already vertical — nothing expanded'}</div>
        ${sv?`<div style="margin-top:8px;color:${sv.intact?'var(--ok)':'var(--bad)'}">
          <b>${sv.intact?'the banner survived':'THE BANNER WAS CHANGED'}</b> —
          ${sv.changed_pixels} changed pixel(s) inside it, ${sv.allowed} allowed</div>`
        :'<div style="margin-top:8px">not expanded yet</div>'}
        <div style="margin-top:8px">Silent by construction: no analysis, no cast,
          no voice, no subtitles.</div>
      </div></div></div>`;
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
        ${d.intake.ref_kind==='replica'?' · <b style="color:var(--ink)">replica</b>':''}
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
  if(d.error) html+=`<div class="err"><b>${STATE.gates.includes(d.state)
    ?'blocked, and back at this gate:':'failed:'}</b> ${esc(d.error)}</div>`;
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
  html+=blockingCard(d);
  html+=motionCard(d);
  html+=bannerCard(d);
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

function openWaive(){
  $('#wvErr').innerHTML=''; $('#wvNote').value='';
  $('#wvScenes').innerHTML=(DETAIL.blocking||[]).map(i=>{
    const s=DETAIL.scenes.find(x=>x.idx===i)||{}, q=s.clip_qa||{};
    return `<label class="tick" title="${esc((q.issues||[]).join('; '))}">
      <input type="checkbox" class="wvScene" value="${i}"> scene ${i}</label>`;
  }).join('');
  wvDlg.showModal();
}
$('#wvGo').onclick=async()=>{
  const scenes=[...document.querySelectorAll('.wvScene:checked')].map(c=>+c.value);
  const note=$('#wvNote').value.trim();
  if(!scenes.length){ $('#wvErr').innerHTML='<div class="err">Tick the shots you accept.</div>'; return; }
  if(!note){ $('#wvErr').innerHTML='<div class="err">A reason is required — it ships with the creative.</div>'; return; }
  try{
    await act('waive',{scenes,note});
    wvDlg.close();
  }catch(e){ $('#wvErr').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
};

let DRV=null;
function openDriver(){
  DRV=null;
  $('#drvErr').innerHTML=''; $('#drvNote').value=''; $('#drvEngine').value='seedance';
  $('#drvDrop').classList.remove('has');
  $('#drvDrop').innerHTML=`<div class="big">Drop the cut you want the movement from</div>
    <div class="hint">or click to choose &middot; mp4 or mov</div>`;
  $('#drvScenes').innerHTML=DETAIL.scenes.map(s=>
    `<label class="tick">
      <input type="checkbox" class="drvScene" value="${s.idx}">
      shot ${s.idx} <span class="muted">${s.duration_s}s</span></label>`).join('');
  drvEngineNote();
  drvDlg.showModal();
}
// What choosing the engine COSTS, said where it is chosen. Motion Control runs
// for exactly as long as the driver and takes no duration at all, so the plan's
// clamp does not apply -- their tool let a 23s driver quietly become a 15s clip.
function drvEngineNote(){
  const mc=$('#drvEngine').value.startsWith('kling-mc');
  const secs=DRV?DRV.duration_s:null;
  $('#drvEngineNote').innerHTML=mc
    ? 'Motion Control: each shot becomes '
      +(secs?`<b>${secs}s</b>`:'exactly as long as the driver')
      +' — the plan&rsquo;s length is overwritten — and is generated SILENT. '
      +'Any line it had is spoken separately and laid over the clip.'
    : 'Seedance video reference: the shot keeps its planned length (4-15s) and may speak.';
}
$('#drvEngine').addEventListener('change',drvEngineNote);
function uploadDriver(file){
  if(!file) return;
  const d=$('#drvDrop');
  d.innerHTML='<div class="big">Uploading…</div>';
  const xhr=new XMLHttpRequest();
  xhr.open('POST','/api/uploads');
  xhr.setRequestHeader('X-Filename',file.name);
  xhr.setRequestHeader('Content-Type','application/octet-stream');
  xhr.upload.onprogress=e=>{ if(e.lengthComputable)
    d.innerHTML=`<div class="big">Uploading…</div><div class="hint">${Math.round(e.loaded/e.total*100)}%</div>`; };
  xhr.onload=()=>{
    let r={}; try{ r=JSON.parse(xhr.responseText); }catch(e){}
    if(xhr.status>=400||r.error||r.kind!=='reference'){
      DRV=null;
      d.innerHTML='<div class="big">Drop the cut you want the movement from</div>'
        +'<div class="hint">or click to choose &middot; mp4 or mov</div>';
      $('#drvErr').innerHTML=`<div class="err">${esc(r.error
        ||(r.kind==='banner'?'that is an image — a driver is a video':'upload failed'))}</div>`;
      return;
    }
    DRV=r; $('#drvErr').innerHTML=''; d.classList.add('has');
    d.innerHTML=`<div class="big">${esc(r.name)}</div>
      <div class="hint">${r.duration_s}s &middot; ${r.width}&times;${r.height}</div>`;
    drvEngineNote();
  };
  xhr.onerror=()=>{ $('#drvErr').innerHTML='<div class="err">upload failed</div>'; };
  xhr.send(file);
}
(function(){
  const d=$('#drvDrop'), input=$('#drvInput');
  d.onclick=()=>input.click();
  input.onchange=()=>{ uploadDriver(input.files[0]); input.value=''; };
  ['dragenter','dragover'].forEach(ev=>d.addEventListener(ev,e=>{e.preventDefault();d.classList.add('over');}));
  ['dragleave','drop'].forEach(ev=>d.addEventListener(ev,e=>{e.preventDefault();d.classList.remove('over');}));
  d.addEventListener('drop',e=>uploadDriver(e.dataTransfer.files[0]));
})();
$('#drvGo').onclick=async()=>{
  const scenes=[...document.querySelectorAll('.drvScene:checked')].map(c=>+c.value);
  if(!DRV){ $('#drvErr').innerHTML='<div class="err">Drop a driver video first.</div>'; return; }
  if(!scenes.length){ $('#drvErr').innerHTML='<div class="err">Tick at least one shot — '
    +'a driver attached to nothing changes nothing.</div>'; return; }
  try{
    await api(`/api/jobs/${CUR}/driver`,{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({source:DRV.path,engine:$('#drvEngine').value,
                           note:$('#drvNote').value,scenes})});
    drvDlg.close(); await refresh();
  }catch(e){ $('#drvErr').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
};

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
  d.innerHTML=`<div class="big">Drop the reference video, or a client banner</div>
    <div class="hint">or click to choose &middot; a VIDEO is analysed and re-created &middot;
      an IMAGE is expanded to 9:16 and animated</div>
    <div class="bar" id="dropBar" style="display:none"><i></i></div>`;
  showMode(null);
}
// Which pipeline this job will run, said BEFORE it is created. Their tool
// toasts it for the same reason: the two modes look alike from the outside and
// mixing them wastes a whole generation.
function showMode(u){
  const note=$('#modeNote'), ugc=$('#ugcOnly');
  if(!note) return;
  if(!u){ note.textContent=''; if(ugc) ugc.style.display=''; return; }
  const banner=u.kind==='banner';
  if(ugc) ugc.style.display=banner?'none':'';
  if(!banner){
    note.className='hint';
    note.innerHTML='<b>UGC pipeline</b> — the reference is analysed, a plan is written, '
      +'plates and shots are bought.';
    return;
  }
  const e=u.expansion||{top:0,bottom:0};
  note.className='hint';
  note.innerHTML='<b>Banner mode</b> — '+(e.top||e.bottom
      ? `${e.top}px will be painted above and ${e.bottom}px below, and the banner itself `
        +'is held to zero changed pixels'
      : 'already vertical, so nothing is expanded')
    +'. No analysis, no cast, no voice: the clip is silent and the banner is the brief.';
}
function dropBusy(pct){
  const d=$('#drop');
  d.innerHTML=`<div class="big">Uploading…</div>
    <div class="hint">${pct}%</div>
    <div class="bar"><i style="width:${pct}%"></i></div>`;
}
function dropDone(u){
  // a banner is often well under a megabyte, and "0.0 MB" reads as broken
  const mb=u.size>=1048576?(u.size/1048576).toFixed(1)+' MB'
                          :Math.max(1,Math.round(u.size/1024))+' KB';
  const facts=u.kind==='banner'
    ? `${u.width}&times;${u.height} &middot; ${mb}`
    : `${u.duration_s}s &middot; ${u.width}&times;${u.height} &middot; ${mb}`
      +` &middot; ${u.has_audio?'has audio':'<span style="color:var(--warn)">no audio track</span>'}`;
  $('#drop').classList.add('has');
  $('#drop').innerHTML=`<div class="big">${esc(u.name)}</div>
    <div class="hint">${facts}</div>
    <div style="margin-top:9px"><button type="button" onclick="resetDrop()"
      style="padding:4px 10px;font-size:12px">Choose another</button></div>`;
  showMode(u);
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
  const RK={ugc:'UGC with people — we re-create the idea, not the frame',
            replica:'Match the reference — reproduce its material, composition and finish 1:1'};
  $('#f_refkind').innerHTML=(o.ref_kinds||['ugc']).map(k=>
    `<option value="${esc(k)}"${k===(o.ref_kind_default||'ugc')?' selected':''}>${esc(RK[k]||k)}</option>`).join('');
  refKindNote();
  $('#newErr').innerHTML='';
  $('#f_name').value=''; $('#f_brief').value=''; $('#nameRead').textContent='';
  $('#f_morph').value=''; $('#f_card').value='';
  resetDrop();
  setTimeout(()=>$('#f_name').focus(),40);
};
// What choosing it COSTS and what it BUYS, said where it is chosen.
function refKindNote(){
  const el=$('#refKindNote'); if(!el) return;
  el.innerHTML=$('#f_refkind').value==='replica'
    ? 'Stills are cut from your reference and attached to every plate — the look '
      +'is carried by a PICTURE, not by words. AW024 said "3D cartoon animation '
      +'style" in every prompt and still came back photoreal.'
    : 'The reference is a source of ideas; the frames are ours.';
}
$('#f_refkind').addEventListener('change',refKindNote);
$('#f_name').addEventListener('input',readName);
$('#f_vertical').addEventListener('change',()=>{ VERTICAL_TOUCHED=true; readName(); });
$('#createBtn').onclick=async()=>{
  if(!readName()){
    $('#newErr').innerHTML='<div class="err">Paste the full creative name — it carries '
      +'the id, week, concept and producer.</div>';
    return;
  }
  if(!UPLOAD){
    $('#newErr').innerHTML='<div class="err">Drop a reference video or a banner first.</div>';
    return;
  }
  const fd=new FormData($('#newForm')), body={run:true};
  const banner=UPLOAD.kind==='banner';
  body[banner?'banner':'reference']=UPLOAD.path;
  // Hidden is not the same as absent. A transformation typed before the banner
  // was dropped would otherwise be carried into a job whose writer never reads
  // it -- a setting the producer believes is in force and nothing consults.
  fd.forEach((v,k)=>{ if(v!==''&&!(banner&&(k==='morph'||k==='text_card'||k==='ref_kind'))) body[k]=v; });
  try{
    const r=await api('/api/jobs',{method:'POST',
      headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    newDlg.close(); await refresh(); select(r.id);
  }catch(e){ $('#newErr').innerHTML=`<div class="err">${esc(e.message)}</div>`; }
};
refresh(); TIMER=setInterval(refresh,4000);
</script></body></html>
"""

// Continuum — simple, private home for your AI chats
async function getJSON(p){const r=await fetch(p);if(!r.ok)throw new Error(p+" "+r.status);return r.json();}
async function postJSON(p,o){const r=await fetch(p,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(o||{})});
  let d=null; try{d=await r.json();}catch(e){} if(!r.ok)throw new Error((d&&d.detail)||("Error "+r.status)); return d;}

async function streamNDJSON(url, body, {onMeta, onDelta, onDone, onError}={}){
  let r;
  try{ r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body||{})}); }
  catch(e){ onError&&onError(e); return; }
  if(!r.ok){ let msg=url+" "+r.status; try{ msg=(await r.json()).detail||msg; }catch(e){} onError&&onError(new Error(msg)); return; }
  const reader=r.body.getReader(), dec=new TextDecoder(); let buf="";
  while(true){ const {value,done}=await reader.read(); if(done)break; buf+=dec.decode(value,{stream:true});
    let nl; while((nl=buf.indexOf("\n"))>=0){ const line=buf.slice(0,nl).trim(); buf=buf.slice(nl+1); if(!line)continue;
      let ev; try{ ev=JSON.parse(line); }catch(e){ continue; }
      if(ev.type==="meta")onMeta&&onMeta(ev);
      else if(ev.type==="delta")onDelta&&onDelta(ev.text);
      else if(ev.type==="done")onDone&&onDone(ev);
      else if(ev.type==="error")onError&&onError(new Error(ev.message||"error"));
    }
  }
}
function el(id){return document.getElementById(id);}
function esc(s){return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));}
function normModel(n){return String(n||"").replace(/:latest$/,"");}
function isInstalled(name,installed){const nn=normModel(name);return (installed||[]).some(i=>normModel(i)===nn);}
function findPull(name,pulls){const nn=normModel(name);for(const k in (pulls||{})){if(normModel(k)===nn)return pulls[k];}return null;}
function humanStatus(s){s=String(s||"").toLowerCase();if(s==="starting"||(s.includes("manifest")&&!s.includes("writing")))return "Preparing";if(s.includes("verif"))return "Verifying";if(s.includes("writing")||s.includes("removing"))return "Finishing";if(s==="success")return "Done";return "Downloading";}
function toast(m){const t=el("toast");t.textContent=m;t.hidden=false;clearTimeout(t._t);t._t=setTimeout(()=>t.hidden=true,4600);}

const VIEWS=["home","conv","search","paste","onboarding","settings","compare","memory"];
function showView(name){ const sc=el("scrim"); if(sc)sc.hidden=true; document.body.classList.remove("nav-open"); VIEWS.forEach(v=>{const e=el(v+"-view"); if(e)e.hidden=(v!==name);}); }

const PROVIDER={claude:"Claude",chatgpt:"ChatGPT",grok:"Grok",paste:"the app",generic:"the app",notes:"the app"};
let OLLAMA={available:false,models:[]}, SELECTED_MODEL=null, CURRENT_CONV=null, POLL=null, CONVS=[], UPDATE_DISMISSED=false;
let MEM_FILTER={type:null,provider:null}, MEM_MERGE=null;

function aiReady(){ return OLLAMA.available && OLLAMA.models && OLLAMA.models.length>0; }

async function boot(){
  try{ OLLAMA=(await getJSON("/api/status")).ollama||OLLAMA; }catch(e){}
  await refreshConversations();
  if(CONVS.length===0){ renderOnboarding(); } else { renderHome(); showView("home"); }
  checkUpdates();
}

async function checkUpdates(){
  let u; try{ u=await getJSON("/api/updates"); }catch(e){ return; }
  const bar=el("update-bar"); if(!bar)return;
  let msg="";
  if(u.app_update_available){ msg=`<b>Continuum ${esc(u.latest)} is available.</b> ${u.notes?esc(u.notes)+" ":""}<a href="${esc(u.url)}" target="_blank" rel="noopener">Download the update</a>`; }
  else if(u.ollama_update_available){ msg=`A newer offline-AI engine is available (Ollama ${esc(u.ollama_recommended)}). <a href="${esc(u.ollama_url)}" target="_blank" rel="noopener">Update Ollama</a>`; }
  if(msg && !UPDATE_DISMISSED){ bar.innerHTML=`<span>${msg}</span><button class="bar-x" id="update-x" aria-label="Dismiss">\u00d7</button>`; bar.hidden=false; el("update-x").onclick=()=>{ UPDATE_DISMISSED=true; bar.hidden=true; }; }
  else { bar.hidden=true; }
}

async function refreshConversations(){
  try{ const d=await getJSON("/api/conversations"); CONVS=d.conversations; }catch(e){ CONVS=[]; }
  el("conv-count").textContent = CONVS.length? "("+CONVS.length+")" : "";
  el("conv-list").innerHTML = CONVS.length ? CONVS.map(c=>
    `<div class="conv-item${c.id===CURRENT_CONV?' active':''}" data-id="${esc(c.id)}">
       <div class="conv-title">${esc(c.title)}</div>
       <div class="conv-meta">${esc(c.source)} · ${c.messages} messages</div></div>`).join("")
    : '<div class="muted pad" style="font-size:12px">No chats yet.</div>';
  document.querySelectorAll(".conv-item").forEach(n=>n.onclick=()=>openConversation(n.dataset.id));
}

/* ---------- home ---------- */
function renderHome(){
  const recents = CONVS.slice(0,5).map(c=>
    `<div class="recent" data-id="${esc(c.id)}"><span>${esc(c.title)} <span class="muted">· ${esc(c.source)}</span></span><span class="go">Open →</span></div>`).join("");
  el("home-view").innerHTML=`
    <div class="hero">
      <h1>Your AI chats, together and private</h1>
      <p class="sub">Bring your Claude, ChatGPT and Grok conversations into one place you own — search them, revisit them, and keep any of them going for free when you hit a limit. Nothing ever leaves your computer.</p>
      <div class="choices">
        <div class="choice feature" id="c-paste">
          <span class="tag">Easiest</span>
          <div class="ti">⧉</div><h3>Paste a chat</h3>
          <p>Copy a conversation from Claude, ChatGPT or Grok and paste it in.</p>
        </div>
        <div class="choice" id="c-upload">
          <div class="ti" style="margin-top:26px">↥</div><h3>Add from a file</h3>
          <p>Upload the data export you downloaded from Claude or ChatGPT.</p>
        </div>
      </div>
      ${recents?`<div class="section-label">Recent chats</div>${recents}`:""}
    </div>`;
  el("c-paste").onclick=openPaste;
  el("c-upload").onclick=()=>el("file-input").click();
  document.querySelectorAll("#home-view .recent").forEach(n=>n.onclick=()=>openConversation(n.dataset.id));
}

/* ---------- conversation ---------- */
async function openConversation(id){
  let d; try{ d=await getJSON("/api/conversations/"+encodeURIComponent(id)); }catch(e){ toast("Couldn't open that chat"); return; }
  CURRENT_CONV=id; refreshConversations();
  const prov=PROVIDER[d.conversation.source]||"the app";
  const topics=d.graph.nodes.filter(n=>n.type==="entity").slice(0,30).map(n=>`<span class="chip">${esc(n.label)}</span>`).join("");
  el("conv-view").innerHTML=`
    <div class="conv-header">
      <h2>${esc(d.conversation.title)}</h2>
      <span class="src ${esc(d.conversation.source)}">${esc(d.conversation.source)}</span>
      <button class="btn" id="handback-btn" title="Copy a summary you can paste into ${esc(prov)}">Continue in ${esc(prov)} →</button>
    </div>
    <details class="kgwrap"><summary>Details — topics &amp; saving a copy</summary>
      <div class="kgbody">
        <div class="muted" style="font-size:12px;margin-bottom:6px">What this chat is about</div>
        <div class="chips">${topics||'<span class="muted">No topics picked out yet.</span>'}</div>
        <div style="margin-top:14px"><button class="btn" id="export-btn">Save a copy of this chat</button></div>
      </div></details>
    <div class="messages">${d.messages.map(m=>
      `<div class="msg ${esc(m.role)}${m.local?' local':''}"><div class="role">${esc(m.role)}${m.local?' · written here':''}</div><div class="body">${esc(m.content)}</div></div>`).join("")}</div>
    <div class="composer">
      <div class="composer-bar">
        <textarea id="composer-input" rows="1" placeholder="Type to continue this chat…"></textarea>
        <button id="composer-send" class="btn primary">Send</button>
      </div>
      <div id="composer-hint" class="composer-hint"></div>
    </div>`;
  showView("conv");
  showComposer();
  el("export-btn").onclick=()=>{ const a=document.createElement("a");
    a.href="/api/conversations/"+encodeURIComponent(id)+"/export"; a.download=""; document.body.appendChild(a); a.click(); a.remove();
    toast("Saved a copy to your downloads."); };
  el("handback-btn").onclick=async()=>{ const b=el("handback-btn"); b.disabled=true; b.textContent="Preparing…";
    try{ const d2=await postJSON("/api/conversations/"+encodeURIComponent(id)+"/handoff-brief",{model:SELECTED_MODEL}); showBrief(d2.brief, prov); }
    catch(e){ toast(e.message); } b.disabled=false; b.textContent="Continue in "+prov+" →"; };
  el("composer-send").onclick=sendContinuation;
  el("composer-input").addEventListener("keydown",e=>{ if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendContinuation();} });
}

function showComposer(){
  const hint=el("composer-hint"), send=el("composer-send"), input=el("composer-input"); if(!hint)return;
  if(aiReady()){
    SELECTED_MODEL=SELECTED_MODEL&&OLLAMA.models.includes(SELECTED_MODEL)?SELECTED_MODEL:OLLAMA.models[0];
    hint.innerHTML='Replies here are written by the free offline AI on your computer — handy for keeping going, not a Claude replacement.';
    send.disabled=false; input.disabled=false;
  } else {
    hint.innerHTML='To keep chatting here for free, <b><a href="#" id="hint-setup">turn on offline AI</a></b> (a one-time setup). You can still search, save and continue in your other apps without it.';
    send.disabled=true; input.disabled=true;
    const h=el("hint-setup"); if(h)h.onclick=(e)=>{e.preventDefault();renderSettings();};
  }
}
function appendMessage(m){
  const wrap=document.querySelector("#conv-view .messages"); if(!wrap)return;
  const div=document.createElement("div"); div.className="msg "+m.role+(m.local?" local":"");
  div.innerHTML=`<div class="role">${esc(m.role)}${m.local?' · written here':''}</div><div class="body">${esc(m.content)}</div>`;
  wrap.appendChild(div); el("content").scrollTop=el("content").scrollHeight;
}
function appendAssistantStub(){
  const wrap=document.querySelector("#conv-view .messages"); if(!wrap)return null;
  const div=document.createElement("div"); div.className="msg assistant local";
  div.innerHTML='<div class="role">assistant \u00b7 written here</div><div class="body"></div>';
  wrap.appendChild(div); el("content").scrollTop=el("content").scrollHeight;
  return div.querySelector(".body");
}
async function sendContinuation(){
  const input=el("composer-input"); const text=(input.value||"").trim(); if(!text||!CURRENT_CONV)return;
  const send=el("composer-send"); send.disabled=true; send.textContent="Writing…"; input.value="";
  appendMessage({role:"user",content:text,local:true});
  const body=appendAssistantStub(); let acc="";
  if(body)body.innerHTML='<span class="muted">\u2026</span>';
  await streamNDJSON("/api/conversations/"+encodeURIComponent(CURRENT_CONV)+"/continue/stream",
    {message:text,model:SELECTED_MODEL},{
    onDelta:(t)=>{ acc+=t; if(body){ body.textContent=acc; el("content").scrollTop=el("content").scrollHeight; } },
    onError:(e)=>{ if(body)body.textContent=acc||("\u26a0 "+e.message); toast(e.message); },
  });
  if(body&&!acc)body.textContent="(no reply)";
  send.disabled=false; send.textContent="Send";
}

/* ---------- search + ask ---------- */
let searchTimer;
el("omni").addEventListener("input",e=>{ clearTimeout(searchTimer); const q=e.target.value;
  searchTimer=setTimeout(()=>{ if(q.trim()){ runSearch(q); } else { if(CONVS.length){ renderHome(); showView("home"); } else { renderOnboarding(); } } },220); });
el("omni").addEventListener("keydown",e=>{ if(e.key==="Enter"){e.preventDefault(); const q=e.target.value.trim(); if(q)runAsk(q);} });

async function runSearch(q){
  showView("search");
  let results=[]; try{ results=(await getJSON("/api/search?q="+encodeURIComponent(q))).results; }catch(e){}
  el("search-view").innerHTML=`
    <div class="ask-bar"><textarea id="ask-input" rows="1">${esc(q)}</textarea><button class="btn primary" id="ask-go">Ask the AI</button></div>
    <div id="ask-answer"></div>
    <div class="section-label">Found in your chats</div>
    <div id="search-results">${
      results.length? results.map(r=>`<div class="sr" data-id="${esc(r.conversation_id)}"><div class="sr-title">${esc(r.title)} <span class="muted">· ${esc(r.role)}</span></div><div class="sr-snip">${esc(r.snippet)}</div></div>`).join("")
      : '<div class="muted pad">No matches.</div>'}</div>`;
  el("ask-go").onclick=()=>runAsk(el("ask-input").value.trim());
  document.querySelectorAll("#search-results .sr").forEach(n=>n.onclick=()=>openConversation(n.dataset.id));
}
async function runAsk(q){
  if(!q)return; if(el("search-view").hidden) await runSearch(q);
  const ans=el("ask-answer");
  if(!aiReady()){ ans.innerHTML='<div class="muted pad">To get a written answer, turn on offline AI in <b>Settings \u2699</b>. Search results above work without it.</div>'; return; }
  ans.innerHTML='<div class="ask-reply"><div class="role">answer</div><div class="body" id="ask-body"><span class="muted">Reading your chats\u2026</span></div></div><div id="ask-src"></div>';
  const body=el("ask-body"); let acc="";
  await streamNDJSON("/api/ask/stream",{question:q,model:SELECTED_MODEL},{
    onDelta:(t)=>{ if(!acc&&body)body.textContent=""; acc+=t; if(body)body.textContent=acc; },
    onDone:(d)=>{ const ctx=(d&&d.context)||[]; const src=el("ask-src"); if(ctx.length&&src){ src.innerHTML=`<div class="section-label">Based on</div>`+ctx.map(c=>`<div class="sr" data-id="${esc(c.conversation_id)}"><div class="sr-title">${esc(c.title)} <span class="muted">\u00b7 ${esc(c.role)}</span></div><div class="sr-snip">${esc(c.snippet)}</div></div>`).join(""); src.querySelectorAll(".sr").forEach(n=>n.onclick=()=>openConversation(n.dataset.id)); } if(body&&!acc)body.textContent="(no answer)"; },
    onError:(e)=>{ if(body)body.textContent=acc||e.message; },
  });
}

/* ---------- add a chat (paste) ---------- */
function openPaste(){
  el("paste-view").innerHTML=`
    <div class="hero"><h1>Add a chat</h1>
      <p class="sub">Open a conversation in Claude, ChatGPT or Grok, select all of it, copy, and paste it below. (An exported file works too.)</p></div>
    <input id="paste-title" class="textfield" placeholder="Give it a name (optional)"/>
    <textarea id="paste-text" class="paste-text" placeholder="Paste your conversation here…"></textarea>
    <div class="row-actions"><button class="btn primary" id="paste-go">Add it</button><button class="btn" id="paste-cancel">Cancel</button></div>`;
  showView("paste");
  el("paste-go").onclick=runPaste;
  el("paste-cancel").onclick=()=>{ renderHome(); showView("home"); };
}
async function runPaste(){
  const text=(el("paste-text").value||"").trim(); if(!text){toast("Paste a conversation first");return;}
  const title=(el("paste-title").value||"").trim(); const go=el("paste-go"); go.disabled=true; go.textContent="Adding…";
  try{ const d=await postJSON("/api/paste",{text,title}); await refreshConversations();
    const id=d.conversation_ids&&d.conversation_ids[0];
    if(id){ openConversation(id); toast("Added."); } else toast("That chat is already here.");
  }catch(e){ toast(e.message); } go.disabled=false; go.textContent="Add it";
}

el("file-input").addEventListener("change",async e=>{
  const f=e.target.files[0]; if(!f)return; toast("Adding "+f.name+"…");
  try{ const content=await f.text(); const d=await postJSON("/api/import",{filename:f.name,content}); const im=d.import;
    await refreshConversations();
    let msg;
    if(im.conversations_added) msg=`Added ${im.conversations_added} chat(s) · ${im.messages_added} messages`;
    else if(im.conversations_updated) msg=`Updated ${im.conversations_updated} chat(s) with ${im.messages_added} new message(s)`;
    else msg="Already up to date.";
    toast(msg);
    if(CONVS.length){ renderHome(); showView("home"); }
  }catch(err){ toast("Couldn't add that file: "+err.message); }
  e.target.value="";
});

/* ---------- continue-in-cloud summary ---------- */
function showBrief(brief, prov){
  prov=prov||"your AI app";
  let ov=el("brief-overlay"); if(!ov){ ov=document.createElement("div"); ov.id="brief-overlay"; ov.className="overlay"; document.body.appendChild(ov); }
  ov.innerHTML=`<div class="overlay-card"><div class="ttl">Copy this and paste it into a new ${esc(prov)} message to pick up where you left off</div>
    <textarea id="brief-text" class="brief-text" readonly></textarea>
    <div class="overlay-actions"><button class="btn primary" id="brief-copy">Copy</button><button class="btn" id="brief-close">Close</button></div></div>`;
  el("brief-text").value=brief;
  el("brief-copy").onclick=async()=>{ try{ await navigator.clipboard.writeText(brief); toast("Copied. Paste it into "+prov+"."); }
    catch(e){ const t=el("brief-text"); t.focus(); t.select(); toast("Press Ctrl/Cmd+C to copy."); } };
  el("brief-close").onclick=()=>ov.remove();
}

/* ---------- onboarding ---------- */
function renderOnboarding(){
  el("onboarding-view").innerHTML=`
    <div class="hero"><h1>Welcome to Continuum</h1>
      <p class="sub">A private home for all your AI chats. Let's bring in your first one — it stays on your computer.</p></div>
    <div class="choices">
      <div class="choice feature" id="onb-paste"><span class="tag">Easiest</span><div class="ti">⧉</div><h3>Paste a chat</h3><p>Copy a conversation from Claude, ChatGPT or Grok and paste it in.</p></div>
      <div class="choice" id="onb-upload"><div class="ti" style="margin-top:26px">↥</div><h3>Add from a file</h3><p>Upload a data export from Claude or ChatGPT.</p></div>
    </div>
    <div class="muted" style="margin-top:18px;font-size:13px">You can turn on free offline AI later (Settings ⚙) to keep chats going on your computer.</div>`;
  el("onb-paste").onclick=openPaste;
  el("onb-upload").onclick=()=>el("file-input").click();
  showView("onboarding");
}

/* ---------- settings: Offline AI / Privacy / Advanced ---------- */
el("settings-btn").addEventListener("click",renderSettings);
async function renderSettings(){
  showView("settings");
  el("settings-view").innerHTML=`<div class="hero"><h1>Settings</h1></div>
    <div id="set-ai" class="panel"></div>
    <div id="set-privacy" class="panel"></div>
    <div id="set-about" class="panel"></div>
    <details class="panel"><summary class="adv-summary">Advanced</summary><div id="set-adv" style="margin-top:12px"></div></details>`;
  renderAIPanel();
  renderPrivacyPanel();
  renderAboutPanel();
  renderAdvanced();
}
async function renderAIPanel(){
  const p=el("set-ai"); if(!p)return;
  let m; try{ m=await getJSON("/api/models"); }catch(e){ m={available:false,installed:[]}; }
  OLLAMA=(await getJSON("/api/status")).ollama||OLLAMA;
  if(!m.available){
    p.innerHTML=`<h3>Offline AI</h3><div class="muted" style="font-size:13px">Offline AI runs on your computer (it comes with Continuum). If you just installed, restart your computer once, then come back here.</div>`;
    return;
  }
  const installed=m.installed||[];
  let head;
  if(installed.length){
    const opts=installed.map(x=>`<option value="${esc(x)}"${x===SELECTED_MODEL?' selected':''}>${esc(x)}</option>`).join("");
    head=`<div class="ok" style="font-size:14px">✓ Offline AI is on.</div>
      <div style="display:flex;align-items:center;gap:8px;margin-top:10px;flex-wrap:wrap">
        <span class="muted" style="font-size:13px">Model in use:</span>
        <select id="active-model" class="textfield" style="max-width:240px">${opts}</select></div>
      <div class="muted" style="font-size:12px;margin-top:6px">It runs on your computer — great for keeping chats going. It's smaller than Claude, so it won't match Claude's depth.</div>`;
  } else {
    head=`<div class="muted" style="font-size:13px">Turn on free offline AI to keep chats going and get written answers — all on your computer. Pick a model for your computer below (it downloads once).</div>`;
  }
  p.innerHTML=`<h3>Offline AI</h3>${head}<div class="section-label" style="margin-top:16px">Models for your computer</div><div id="ai-system"></div>`;
  const sel=el("active-model"); if(sel){ if(!SELECTED_MODEL||!installed.includes(SELECTED_MODEL))SELECTED_MODEL=installed[0]; sel.value=SELECTED_MODEL; sel.onchange=()=>{ SELECTED_MODEL=sel.value; toast("Now using "+SELECTED_MODEL); }; }
  loadSystemInto("ai-system");
}
function renderPrivacyPanel(){
  const p=el("set-privacy"); if(!p)return;
  Promise.all([getJSON("/api/status").catch(()=>({})), getJSON("/api/analytics").catch(()=>({consent:null}))]).then(([s,a])=>{
    const on=a.consent===true;
    p.innerHTML=`<h3>Privacy</h3>
      <div style="font-size:14px">Your imported chats and everything you write stay on your computer. Continuum only reaches out to check for updates and to send an anonymous usage count (on by default \u2014 switch it off below anytime). It never sends your chats or files.</div>
      <div class="kv" style="margin-top:10px"><span class="muted">Your files are here</span><span class="mono">${esc(s.home||"")}</span></div>
      <div class="kv" style="align-items:flex-start"><span style="max-width:62%"><b>Anonymous usage count</b><div class="muted" style="font-size:12px;margin-top:2px">A random ID + app version only \u2014 never your chats or files. On by default. Helps us see how many people use Continuum.</div></span>
        <button class="btn ${on?'':'primary'}" id="consent-toggle">${on?'On \u00b7 turn off':'Off \u00b7 turn on'}</button></div>`;
    el("consent-toggle").onclick=async()=>{ try{ await postJSON("/api/analytics/consent",{consent:!on}); toast(on?"Anonymous count turned off.":"Thanks \u2014 anonymous count is on."); renderPrivacyPanel(); }catch(e){ toast(e.message); } };
  });
}
function renderAboutPanel(){
  const p=el("set-about"); if(!p)return;
  getJSON("/api/updates").then(u=>{
    const on=u.check_enabled!==false;
    let status;
    if(u.app_update_available) status=`<span class="ok">Continuum ${esc(u.latest)} is available</span> \u00b7 <a href="${esc(u.url)}" target="_blank" rel="noopener">Download</a>`;
    else if(u.latest) status=`<span class="muted">You\u2019re on the latest version.</span>`;
    else status=`<span class="muted">Couldn\u2019t check just now.</span>`;
    let oll = u.ollama_update_available? `<div class="kv"><span class="muted">Offline AI engine</span><span><a href="${esc(u.ollama_url)}" target="_blank" rel="noopener">Update Ollama ${esc(u.ollama_recommended)}</a></span></div>`:"";
    p.innerHTML=`<h3>About</h3>
      <div class="kv"><span class="muted">Version</span><span class="mono">${esc(u.current||"")}</span></div>
      <div class="kv"><span class="muted">Updates</span><span>${status}</span></div>
      ${oll}
      <div class="kv" style="align-items:flex-start"><span style="max-width:62%"><b>Check for updates</b><div class="muted" style="font-size:12px;margin-top:2px">Continuum checks skiframework.org for a newer version. This is the only thing it connects to \u2014 no chats or personal data are sent.</div></span>
        <button class="btn ${on?'':'primary'}" id="upd-toggle">${on?'On \u00b7 turn off':'Off \u00b7 turn on'}</button></div>
      <div class="row-actions"><button class="btn" id="upd-now">Check now</button><a class="btn" href="https://skiframework.org/continuum" target="_blank" rel="noopener">What\u2019s new</a></div>`;
    el("upd-toggle").onclick=async()=>{ try{ await postJSON("/api/updates/settings",{check_enabled:!on}); renderAboutPanel(); }catch(e){ toast(e.message); } };
    el("upd-now").onclick=async()=>{ toast("Checking\u2026"); try{ await getJSON("/api/updates"); }catch(e){} UPDATE_DISMISSED=false; renderAboutPanel(); checkUpdates(); };
  }).catch(()=>{ p.innerHTML='<h3>About</h3><div class="muted">Version info unavailable.</div>'; });
}
async function renderAdvanced(){
  const host=el("set-adv"); if(!host)return;
  host.innerHTML='<div id="adv-status"></div><div id="adv-models" class="subpanel"></div><div class="row-actions" style="margin-top:14px"><button class="btn" id="quit-btn">Quit Continuum</button></div>';
  try{ const s=await getJSON("/api/status");
    el("adv-status").innerHTML=`<div class="kv"><span class="muted">Device fingerprint</span><span class="mono">${esc(s.identity.fingerprint)}</span></div>
      <div class="kv"><span class="muted">History check</span><span class="${s.ledger.verified?'ok':'bad'}">${s.ledger.verified?'✓ intact ('+s.ledger.entries+' records)':'problem detected'}</span></div>`;
  }catch(e){}
  loadModelsInto("adv-models");
  el("quit-btn").onclick=async()=>{ if(!confirm("Quit Continuum?"))return;
    try{ await fetch("/api/quit",{method:"POST"}); }catch(e){}
    document.body.innerHTML='<div style="padding:60px;text-align:center;color:#9a9aa3;font-family:sans-serif">Continuum has closed. You can close this tab.</div>'; };
}

async function setupOfflineAI(){
  let m; try{ m=await getJSON("/api/models"); }catch(e){ m={available:false}; }
  if(!m.available){ toast("Offline AI isn't ready. If you just installed Continuum, restart your computer once."); return; }
  let name="llama3.2";
  try{ const sys=await getJSON("/api/system"); const rec=sys.recommendation.cards.find(c=>c.tier==="Recommended")||sys.recommendation.cards[0]; if(rec)name=rec.name; }catch(e){}
  try{ await postJSON("/api/models/pull",{name}); toast("Setting up offline AI… this downloads once and can take a few minutes."); 
    if(!POLL)POLL=setInterval(refreshAISetup,2000);
  }catch(e){ toast(e.message); }
}
async function refreshAISetup(){
  try{ const m=await getJSON("/api/models"); const active=Object.values(m.pulls||{}).some(p=>!p.done);
    OLLAMA=(await getJSON("/api/status")).ollama||OLLAMA;
    if(!el("settings-view").hidden) renderAIPanel();
    if(!active){ clearInterval(POLL); POLL=null; if(aiReady()) toast("Offline AI is on."); }
  }catch(e){}
}

async function loadSystemInto(target){
  const panel=el(target); if(!panel)return;
  let d; try{ d=await getJSON("/api/system"); }catch(e){ return; }
  let mdl; try{ mdl=await getJSON("/api/models"); }catch(e){ mdl={installed:[],pulls:{}}; }
  const installed=mdl.installed||[], pulls=mdl.pulls||{};
  const sy=d.system, rec=d.recommendation;
  let anyPull=false;
  const cards=rec.cards.map(c=>{ let act; const pl=findPull(c.name,pulls);
    if(pl&&!pl.done&&!pl.error){ anyPull=true; const pct=pl.percent||0;
      act=`<div class="dl-prog"><div class="dl-bar"><div class="dl-fill" style="width:${pct}%"></div></div><div class="muted" style="font-size:11px;margin-top:5px">${esc(humanStatus(pl.status))} · ${pct}%</div></div>`;
    } else if(pl&&pl.error){ act=`<span class="bad">Download failed</span> <button class="btn mini" data-pull="${esc(c.name)}">Retry</button>`;
    } else if(isInstalled(c.name,installed)){ act=`<span class="ok">✓ installed</span> <button class="btn mini ghost" data-pull="${esc(c.name)}" title="Re-download the latest version">Update</button>`;
    } else if(!c.feasible){ act='<span class="bad">needs more memory</span>';
    } else if(!d.ollama){ act='<span class="muted">offline AI not ready</span>';
    } else { act=`<button class="btn mini" data-pull="${esc(c.name)}">Download</button>`; }
    return `<div class="tier-card ${c.feasible?'':'dim'}"><div class="tier-name">${esc(c.tier)}</div><div class="tier-model"><b>${esc(c.name)}</b></div><div class="muted" style="font-size:12px">${esc(c.note)}</div><div class="tier-action">${act}</div></div>`;}).join("");
  panel.innerHTML=`<div class="muted" style="font-size:12px;margin:10px 0 8px">Models for your computer · ${esc(sy.ram_gb)} GB RAM · ${esc(rec.accelerator)}</div><div class="tier-grid">${cards}</div>`;
  panel.querySelectorAll("[data-pull]").forEach(b=>b.onclick=()=>pullModel(b.dataset.pull));
  if(anyPull&&!POLL)POLL=setInterval(refreshAISetup,1500);
}
async function loadModelsInto(target){
  const panel=el(target); if(!panel)return;
  let d; try{ d=await getJSON("/api/models"); }catch(e){ return; }
  if(!d.available){ panel.innerHTML=''; return; }
  let emb=""; try{ const es=await getJSON("/api/embeddings/status"); let a;
    if(es.building)a=`<span class="muted">improving… ${es.done}/${es.todo}</span>`;
    else if(!es.model_available)a=`<span class="muted">needs a model first</span>`;
    else if(es.indexed>=es.total&&es.total>0)a=`<span class="ok">✓ done</span>`;
    else a=`<button class="btn mini" id="emb-build">Improve search &amp; answers</button>`;
    emb=`<div class="mp-row" style="margin-top:10px"><div><b>Sharper search</b> <span class="muted">optional, one-time</span></div><div>${a}</div></div>`;
    if(es.building&&!POLL)POLL=setInterval(()=>{ if(!el("settings-view").hidden)loadModelsInto(target); },1500);
  }catch(e){}
  panel.innerHTML=emb;
  const eb=el("emb-build"); if(eb)eb.onclick=buildEmbeddings;
}
async function pullModel(name){ try{ await postJSON("/api/models/pull",{name}); toast("Downloading "+name+"…");
  if(!POLL)POLL=setInterval(refreshAISetup,1500); refreshAISetup(); }catch(e){ toast(e.message); } }
async function buildEmbeddings(){ try{ await postJSON("/api/embeddings/build",{}); toast("Improving search… this runs once."); if(!el("settings-view").hidden)loadModelsInto("adv-models"); }catch(e){ toast(e.message); } }

/* ---------- compare ---------- */
let OVERLAPS=[], cmpCount=2;
async function openCompare(){
  showView("compare");
  try{ OVERLAPS=(await getJSON("/api/overlaps")).overlaps; }catch(e){ OVERLAPS=[]; }
  el("compare-view").innerHTML=`
    <div class="hero"><h1>Compare answers</h1><p class="sub">Sometimes you ask the same thing in different apps and get different answers. Continuum finds those and can combine them into one.</p></div>
    <div class="section-label">Same question, different apps</div>
    <div id="ov-list">${OVERLAPS.length? OVERLAPS.map(ovCard).join("") : '<div class="muted pad">Nothing to compare yet. Add chats from a couple of different apps, then check back.</div>'}</div>
    <div style="margin-top:18px"><button class="btn" id="manual-toggle">Or paste answers to compare</button></div>
    <div id="manual-compare" hidden></div>`;
  el("compare-view").querySelectorAll(".ovcard").forEach(c=>c.onclick=()=>openOverlap(c.dataset.id));
  el("manual-toggle").onclick=()=>{ const m=el("manual-compare"); m.hidden=!m.hidden; if(!m.hidden) renderManualCompare(); };
}
function ovCard(o){
  return `<div class="ovcard panel" data-id="${esc(o.id)}" style="cursor:pointer">
    <div style="font-size:14px;margin-bottom:6px">You asked: ${esc(o.question)}</div>
    <div class="muted" style="font-size:12px">In ${o.members.length} chats · ${esc(o.providers.join(", "))}</div></div>`;
}
function ans(m){return m.answer||"(no answer saved)";}
function openOverlap(id){
  const o=OVERLAPS.find(x=>x.id===id); if(!o)return;
  const cols=o.members.map(m=>`<div class="panel" style="flex:1;min-width:200px"><div class="muted" style="font-size:12px;margin-bottom:6px"><span class="src ${esc(m.source)}">${esc(m.source)}</span></div><div style="white-space:pre-wrap;font-size:13px;line-height:1.5">${esc(ans(m))}</div></div>`).join("");
  el("compare-view").innerHTML=`
    <div class="hero"><h1>${esc(o.question)}</h1><p class="sub">Here's what each app answered. Combine them into one answer you can keep.</p></div>
    <div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px">${cols}</div>
    <div class="row-actions"><button class="btn" id="ov-back">← Back</button><button class="btn primary" id="ov-combine">Combine into one answer</button></div>
    <div id="ov-result"></div>`;
  el("ov-back").onclick=openCompare;
  el("ov-combine").onclick=async()=>{
    if(!aiReady()){ toast("Turn on offline AI in Settings to combine answers."); return; }
    const btn=el("ov-combine"); btn.disabled=true; btn.textContent="Combining…";
    try{ const d=await postJSON("/api/consolidate",{question:o.question,answers:o.members.map(m=>({model:(PROVIDER[m.source]||m.source),text:m.answer})),model:SELECTED_MODEL});
      el("ov-result").innerHTML=`<div class="ask-reply" style="margin-top:16px"><div class="role">combined answer</div><div class="body">${esc(d.consolidation)}</div></div><div class="row-actions"><button class="btn primary" id="ov-save">Save to your memory</button></div>`;
      el("ov-save").onclick=()=>memEditor(o.question.slice(0,120), d.consolidation, {sources:d.sources, type:"consolidation"});
    }catch(e){ toast(e.message); } btn.disabled=false; btn.textContent="Combine into one answer";
  };
}
function answerBlock(i){ return `<div class="cmp-block"><input class="textfield cmp-model" data-i="${i}" placeholder="Which app? (Claude, ChatGPT…)" style="margin-bottom:6px"/><textarea class="paste-text cmp-text" data-i="${i}" style="min-height:120px" placeholder="Paste this app's answer…"></textarea></div>`; }
function renderManualCompare(){
  el("manual-compare").innerHTML=`
    <input id="cmp-q" class="textfield" style="margin:10px 0" placeholder="The question you asked"/>
    <div id="cmp-answers"></div>
    <div class="row-actions"><button class="btn" id="cmp-add">+ Add another app</button><button class="btn primary" id="cmp-go">Combine</button></div>
    <div id="cmp-result"></div>`;
  cmpCount=2; el("cmp-answers").innerHTML=[0,1].map(answerBlock).join("");
  el("cmp-add").onclick=()=>{ el("cmp-answers").insertAdjacentHTML("beforeend",answerBlock(cmpCount++)); };
  el("cmp-go").onclick=runConsolidate;
}
async function runConsolidate(){
  const question=(el("cmp-q").value||"").trim();
  const models=[...document.querySelectorAll(".cmp-model")], texts=[...document.querySelectorAll(".cmp-text")];
  const answers=[]; texts.forEach((t,i)=>{ const v=(t.value||"").trim(); if(v) answers.push({model:(models[i]&&models[i].value.trim())||("App "+(i+1)),text:v}); });
  if(!question){toast("Add the question first");return;}
  if(!answers.length){toast("Paste at least one answer");return;}
  if(!aiReady()){ toast("Turn on offline AI in Settings to combine answers."); return; }
  const go=el("cmp-go"); go.disabled=true; go.textContent="Combining…";
  try{ const d=await postJSON("/api/consolidate",{question,answers,model:SELECTED_MODEL});
    el("cmp-result").innerHTML=`<div class="ask-reply" style="margin-top:18px"><div class="role">combined answer</div><div class="body">${esc(d.consolidation)}</div></div>
      <div class="row-actions"><button class="btn primary" id="cmp-save">Save to your memory</button></div>`;
    el("cmp-save").onclick=()=>memEditor(question.slice(0,120), d.consolidation, {sources:d.sources, type:"consolidation"});
  }catch(e){ toast(e.message); }
  go.disabled=false; go.textContent="Combine";
}

/* ---------- your memory (brain) ---------- */
function memGraphUrl(){ const p=new URLSearchParams(); if(MEM_FILTER.type)p.set("type",MEM_FILTER.type); if(MEM_FILTER.provider)p.set("provider",MEM_FILTER.provider); p.set("limit","50"); return "/api/memory/graph?"+p.toString(); }
async function openMemory(){
  showView("memory");
  let g; try{ g=await getJSON(memGraphUrl()); }catch(e){ g={nodes:[],edges:[],total:0}; }
  el("memory-view").innerHTML=`
    <div class="hero"><h1>Your memory</h1><p class="sub">The things you've talked about across your AIs — your second brain. The bigger a bubble, the more it has come up. Click one to see what you remember and where it came from.</p></div>
    <div class="mem-filters">
      <span class="mfilter ${!MEM_FILTER.type?'on':''}" data-type="">Everything</span>
      <span class="mfilter ${MEM_FILTER.type==='entity'?'on':''}" data-type="entity">Topics</span>
      <span class="mfilter ${MEM_FILTER.type==='note'?'on':''}" data-type="note">Notes</span>
      <button class="btn mini" id="mem-new" style="margin-left:auto">+ Add a note</button>
    </div>
    <div id="mem-merge-hint"></div>
    <div class="mem-body">
      <svg id="mem-svg" class="brain-svg" viewBox="0 0 640 470" preserveAspectRatio="xMidYMid meet"></svg>
      <div id="mem-panel" class="mem-panel"><div class="muted pad" style="font-size:13px">Click a bubble to see what you remember.</div></div>
    </div>`;
  renderBrain(g);
  el("memory-view").querySelectorAll(".mfilter").forEach(f=>f.onclick=()=>{
    if(f.hasAttribute("data-type")) MEM_FILTER.type=f.dataset.type||null;
    openMemory();
  });
  el("mem-new").onclick=()=>memEditor("","",{type:"note"});
}
function _seed(str){ let h=2166136261; for(let i=0;i<str.length;i++){ h^=str.charCodeAt(i); h=Math.imul(h,16777619); } return ((h>>>0)/4294967296); }
function renderBrain(g){
  const svg=el("mem-svg"); if(!svg)return;
  const W=640,H=470,cx=W/2,cy=H/2;
  if(!g.nodes.length){ svg.innerHTML=`<text x="${cx}" y="${cy}" text-anchor="middle" fill="#9a9aa3" font-size="13">Your memory fills in as you add chats.</text>`; return; }
  const center={id:"__c__",label:"You",type:"center",x:cx,y:cy,fx:cx,fy:cy,vx:0,vy:0,importance:0};
  const nodes=[center,...g.nodes.map(n=>({...n,x:cx+(_seed(n.id)-.5)*460,y:cy+(_seed(n.id+'_y')-.5)*340,vx:0,vy:0}))];
  const byId={}; nodes.forEach(n=>byId[n.id]=n);
  const links=[];
  for(const n of g.nodes) links.push({s:center,t:byId[n.id],c:true});
  for(const e of (g.edges||[])) if(byId[e.src]&&byId[e.dst]) links.push({s:byId[e.src],t:byId[e.dst],c:false});
  for(let it=0;it<280;it++){
    for(let i=0;i<nodes.length;i++)for(let j=i+1;j<nodes.length;j++){const a=nodes[i],b=nodes[j];
      let dx=a.x-b.x,dy=a.y-b.y,d2=dx*dx+dy*dy||0.01,d=Math.sqrt(d2),rep=3400/d2,fx=dx/d*rep,fy=dy/d*rep;
      a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}
    for(const l of links){const a=l.s,b=l.t;let dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||0.01,target=l.c?130:95,k=(d-target)*0.02,fx=dx/d*k,fy=dy/d*k;
      a.vx+=fx;a.vy+=fy;b.vx-=fx;b.vy-=fy;}
    for(const n of nodes){ if(n.fx!=null){n.x=n.fx;n.y=n.fy;continue;} n.vx+=(cx-n.x)*0.002;n.vy+=(cy-n.y)*0.002;n.vx*=0.85;n.vy*=0.85;n.x+=n.vx;n.y+=n.vy;
      n.x=Math.max(30,Math.min(W-30,n.x));n.y=Math.max(24,Math.min(H-24,n.y));}
  }
  const col={center:"#6ee7b7",entity:"#9ad0ff",note:"#ffd9a0",decision:"#ffb0a0",person:"#c9a7ff",topic:"#a0e8c8"};
  let out="";
  for(const l of links)out+=`<line x1="${l.s.x.toFixed(1)}" y1="${l.s.y.toFixed(1)}" x2="${l.t.x.toFixed(1)}" y2="${l.t.y.toFixed(1)}" stroke="#2c2c34" stroke-width="${l.c?1.4:0.8}"/>`;
  // center
  out+=`<circle cx="${cx}" cy="${cy}" r="22" fill="#11261f" stroke="#6ee7b7" stroke-width="2"/><text x="${cx}" y="${(cy+4)}" text-anchor="middle" fill="#6ee7b7" font-size="12">You</text>`;
  for(const n of nodes){ if(n.type==="center")continue; const r=10+Math.min(16,n.importance*2),c=col[n.type]||"#9ad0ff";
    out+=`<g class="brain-node" data-id="${esc(n.id)}"><circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r}" fill="${c}" fill-opacity="0.25" stroke="${c}" stroke-width="1.5"${n.pinned?' stroke-dasharray="0"':''}/><text x="${n.x.toFixed(1)}" y="${(n.y+3).toFixed(1)}" text-anchor="middle" fill="#e7e7ea" font-size="10">${esc((n.label||"").slice(0,16))}</text></g>`;}
  svg.innerHTML=out;
  svg.querySelectorAll(".brain-node").forEach(gn=>gn.addEventListener("click",()=>loadMemNode(gn.getAttribute("data-id"))));
}
async function loadMemNode(id){
  if(MEM_MERGE){ if(id===MEM_MERGE){toast("Pick a different bubble.");return;}
    if(confirm("Combine these two into one?")){ await postJSON("/api/memory/edit",{target:MEM_MERGE,op:"merge",value:id}); MEM_MERGE=null; toast("Combined."); openMemory(); } return; }
  let d; try{ d=await getJSON("/api/memory/node?id="+encodeURIComponent(id)); }catch(e){ return; }
  const facts=(d.facts||[]).map(f=>`<div style="font-size:13px;margin:2px 0">• ${esc(f)}</div>`).join("")||'<div class="muted" style="font-size:12px">Nothing noted yet.</div>';
  const srcs=(d.conversations||[]).map(c=>`<span class="chip" data-cid="${esc(c.id)}" style="cursor:pointer">${esc(c.title)} <span class="muted">· ${esc(c.source)}</span></span>`).join("")||'<span class="muted" style="font-size:12px">—</span>';
  el("mem-panel").innerHTML=`
    <div style="font-size:16px;margin-bottom:2px">${esc(d.label)}</div>
    <div class="muted" style="font-size:11px;margin-bottom:10px">${d.pinned?'marked important · ':''}${esc(d.type==='note'?'note':'topic')}</div>
    ${d.body?`<div style="white-space:pre-wrap;font-size:13px;margin-bottom:10px">${esc(d.body)}</div>`:''}
    <div class="muted" style="font-size:12px">What you remember</div>${facts}
    <div class="muted" style="font-size:12px;margin-top:12px">From these chats</div><div class="chips" style="margin-top:6px">${srcs}</div>
    <div class="row-actions" style="flex-wrap:wrap;margin-top:16px">
      <button class="btn mini" id="me-rename">Rename</button>
      <button class="btn mini" id="me-pin">${d.pinned?'Unmark':'Mark important'}</button>
      <button class="btn mini" id="me-fact">Add a note</button>
      <button class="btn mini" id="me-merge">Combine…</button>
      <button class="btn mini" id="me-hide">Remove</button>
    </div>`;
  el("mem-panel").querySelectorAll("[data-cid]").forEach(n=>n.onclick=()=>openConversation(n.dataset.cid));
  el("me-rename").onclick=async()=>{ const v=prompt("Rename to:",d.label); if(v&&v.trim()){ await postJSON("/api/memory/edit",{target:d.id,op:"rename",value:v.trim()}); openMemory(); } };
  el("me-pin").onclick=async()=>{ await postJSON("/api/memory/edit",{target:d.id,op:"pin",value:!d.pinned}); openMemory(); };
  el("me-fact").onclick=async()=>{ const v=prompt("Add a note about this:"); if(v&&v.trim()){ await postJSON("/api/memory/edit",{target:d.id,op:"fact",value:v.trim()}); loadMemNode(d.id); } };
  el("me-hide").onclick=async()=>{ if(confirm("Remove this from your memory?")){ await postJSON("/api/memory/edit",{target:d.id,op:"hide",value:true}); openMemory(); } };
  el("me-merge").onclick=()=>{ MEM_MERGE=d.id; el("mem-merge-hint").innerHTML=`<div class="banner">Now click another bubble to combine <b>${esc(d.label)}</b> with it. <span style="margin-left:auto;cursor:pointer;text-decoration:underline" id="merge-cancel">cancel</span></div>`; el("merge-cancel").onclick=()=>{ MEM_MERGE=null; el("mem-merge-hint").innerHTML=""; }; };
}
function memEditor(title, body, provenance){
  let ov=el("mem-overlay"); if(!ov){ ov=document.createElement("div"); ov.id="mem-overlay"; ov.className="overlay"; document.body.appendChild(ov); }
  ov.innerHTML=`<div class="overlay-card"><div class="ttl">Save this to your memory</div>
    <input id="mem-title" class="textfield" style="margin-bottom:8px" placeholder="Title"/>
    <textarea id="mem-body" class="brief-text" placeholder="What do you want to remember?"></textarea>
    <div class="overlay-actions"><button class="btn primary" id="mem-save">Save</button><button class="btn" id="mem-cancel">Cancel</button></div></div>`;
  el("mem-title").value=title||""; el("mem-body").value=body||"";
  el("mem-save").onclick=async()=>{ const t=(el("mem-title").value||"").trim(), b=(el("mem-body").value||"").trim();
    if(!t||!b){toast("Add a title and a note");return;}
    try{ await postJSON("/api/memory",{title:t,body:b,provenance:provenance||{type:"note"}}); toast("Saved to your memory."); ov.remove(); openMemory(); }
    catch(e){ toast(e.message); } };
  el("mem-cancel").onclick=()=>ov.remove();
}

/* ---------- nav ---------- */
el("new-btn").addEventListener("click",openPaste);
el("compare-btn").addEventListener("click",openCompare);
el("memory-btn").addEventListener("click",openMemory);
function setNav(open){ document.body.classList.toggle("nav-open",open); el("scrim").hidden=!open; }
el("menu-btn").addEventListener("click",()=>setNav(!document.body.classList.contains("nav-open")));
el("scrim").addEventListener("click",()=>setNav(false));

boot();

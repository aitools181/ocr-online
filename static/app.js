// SMVS OCR — frontend
const $ = (s) => document.querySelector(s);
let LANGS = [], DEFAULTS = [];
const bulkLangs = new Set();
const files = [];                 // input files
let results = [];                 // [{name,text,downloads,counts,error}]
let curIdx = 0;
let JOB = "";
const sessionJobs = new Set();    // server jobs created this session

const fileInput=$("#fileInput"), drop=$("#drop"), fileListEl=$("#fileList");
const bulkBar=$("#bulkBar"), bulkLangEl=$("#bulkLang"), applyAll=$("#applyAll"), fileHelp=$("#fileHelp");
const convertBtn=$("#convertBtn"), clearBtn=$("#clearBtn"), statusEl=$("#status");
const previewEl=$("#preview"), previewEmpty=$("#previewEmpty");
const downloadsEl=$("#downloads"), logEl=$("#log"), fileTabs=$("#fileTabs");
const copyBtn=$("#copyBtn"), viewBtn=$("#viewBtn"), zipBtn=$("#zipBtn");
const uploadProg=$("#uploadProg");
const modal=$("#viewModal"), modalList=$("#modalList"), modalText=$("#modalText"),
      modalTitle=$("#modalTitle"), modalDl=$("#modalDl"), modalClose=$("#modalClose");

const cap=(c)=> c?c[0].toUpperCase()+c.slice(1):c;
const esc=(s)=> String(s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const toastsEl=document.getElementById("toasts");
function toast(msg,type="ok"){
  if(!toastsEl) return;
  const t=document.createElement("div"); t.className="toast "+type;
  const ic=type==="err"?"✕":(type==="info"?"⋯":"✓");
  t.innerHTML=`<span class="ic">${ic}</span><span>${esc(msg)}</span>`;
  toastsEl.appendChild(t);
  requestAnimationFrame(()=>t.classList.add("show"));
  setTimeout(()=>{ t.classList.remove("show"); setTimeout(()=>t.remove(),300); },5000);
}
function setStatus(t,c=""){ toast(t, c==="err"?"err":(c==="busy"?"info":"ok")); }
function logLine(t){ logEl.hidden=false; logEl.textContent+=t+"\n"; logEl.scrollTop=logEl.scrollHeight; }
function langSummary(set){ return set.size?LANGS.filter(l=>set.has(l.code)).map(l=>cap(l.code)).join(", "):"none"; }
function pageSummary(e){ return e.pagesMode==="all"?"All Pages":(e.pages.size?`${e.pages.size} Pages`:"Specific"); }
function fmtSize(b){ return b<1048576?(b/1024).toFixed(0)+" KB":(b/1048576).toFixed(1)+" MB"; }
function closeAllDropdowns(except){ document.querySelectorAll(".dd.open").forEach(d=>{ if(d!==except) d.classList.remove("open"); }); }
document.addEventListener("click", ()=>closeAllDropdowns(null));

// reusable language multiselect dropdown
function makeLangDropdown(set, onChange){
  const dd=document.createElement("div"); dd.className="dd";
  const btn=document.createElement("button"); btn.className="dd-btn"; btn.type="button";
  btn.innerHTML=`<span class="dd-lbl">${langSummary(set)}</span> <span class="caret">▾</span>`;
  const pan=document.createElement("div"); pan.className="dd-panel";
  LANGS.forEach(l=>{
    const row=document.createElement("label"); row.className="dd-check";
    const cb=document.createElement("input"); cb.type="checkbox"; cb.checked=set.has(l.code);
    cb.onchange=()=>{ cb.checked?set.add(l.code):set.delete(l.code);
      btn.querySelector(".dd-lbl").textContent=langSummary(set); onChange&&onChange(); };
    row.appendChild(cb);
    row.insertAdjacentHTML("beforeend",`<span class="g">${l.glyph}</span><span>${l.name}</span>`);
    pan.appendChild(row);
  });
  btn.onclick=(ev)=>{ ev.stopPropagation(); const o=dd.classList.contains("open"); closeAllDropdowns(); if(!o) dd.classList.add("open"); };
  pan.onclick=(ev)=>ev.stopPropagation();
  dd.append(btn,pan); return dd;
}

// ---------- languages ----------
async function loadLanguages(){
  let all=[];
  try{ all=await (await fetch("/api/languages")).json(); }catch(e){ return; }
  LANGS=all.filter(l=>l.installed);
  DEFAULTS=["eng","guj"].filter(c=>LANGS.some(l=>l.code===c));
  DEFAULTS.forEach(c=>bulkLangs.add(c));
  bulkLangEl.appendChild(makeLangDropdown(bulkLangs,null));
}
applyAll.onclick=()=>{ files.forEach(f=>f.langs=new Set(bulkLangs)); renderFiles(); toast("Language applied to all files"); };

// ---------- files ----------
function addFiles(list){
  let added=0;
  for(const f of list){
    if(!files.some(x=>x.file.name===f.name && x.file.size===f.size)){
      files.push({file:f, langs:new Set(DEFAULTS), pagesMode:"all", pages:new Set(), count:null}); added++;
    }
  }
  renderFiles();
  if(added) toast(`Added ${added} file${added>1?"s":""}`);
}
async function fetchCount(e){
  if(e.count!=null) return e.count;
  const fd=new FormData(); fd.append("file", e.file, e.file.name);
  const r=await fetch("/api/pagecount",{method:"POST",body:fd}); const d=await r.json();
  e.count=d.pages||1; return e.count;
}
function parseRange(spec,maxp){
  const set=new Set();
  String(spec).replace(/\s/g,"").split(",").forEach(part=>{
    if(!part) return;
    if(part.includes("-")){ const [a,b]=part.split("-"); if(/^\d+$/.test(a)&&/^\d+$/.test(b)) for(let x=+a;x<=+b;x++) if(x>=1&&x<=maxp) set.add(x); }
    else if(/^\d+$/.test(part)){ const x=+part; if(x>=1&&x<=maxp) set.add(x); }
  });
  return [...set].sort((a,b)=>a-b);
}

function renderFiles(){
  fileListEl.innerHTML="";
  const has=files.length>0; fileHelp.hidden=!has; bulkBar.hidden=!has;
  files.forEach((e,i)=>{
    const li=document.createElement("li"); li.className="filerow";
    const col=document.createElement("div"); col.className="fcol";
    col.innerHTML=`<div class="fname" title="${esc(e.file.name)}">${esc(e.file.name)}</div><span class="fsize">${fmtSize(e.file.size)}</span>`;
    const ldd=makeLangDropdown(e.langs,null);

    const pdd=document.createElement("div"); pdd.className="dd";
    const pbtn=document.createElement("button"); pbtn.className="dd-btn"; pbtn.type="button";
    pbtn.innerHTML=`<span class="dd-lbl">${pageSummary(e)}</span> <span class="caret">▾</span>`;
    const ppan=document.createElement("div"); ppan.className="dd-panel pages";
    const body=document.createElement("div");
    ppan.innerHTML=
      `<label class="dd-radio"><input type="radio" name="pg${i}" value="all" ${e.pagesMode==="all"?"checked":""}><span>All Pages</span></label>`+
      `<label class="dd-radio"><input type="radio" name="pg${i}" value="specific" ${e.pagesMode==="specific"?"checked":""}><span>Specific Pages</span></label>`;
    ppan.appendChild(body);
    const syncBtn=()=>pbtn.querySelector(".dd-lbl").textContent=pageSummary(e);
    function buildChecks(){
      body.innerHTML="";
      if(e.pagesMode!=="specific") return;
      if(e.count==null){ body.innerHTML='<p class="dd-note">Loading Pages…</p>';
        fetchCount(e).then(()=>buildChecks()).catch(()=>{ body.innerHTML=''; addRange(); }); return; }
      const sa=document.createElement("label"); sa.className="dd-check sa";
      const sacb=document.createElement("input"); sacb.type="checkbox"; sacb.checked=(e.pages.size===e.count&&e.count>0);
      sa.appendChild(sacb); sa.insertAdjacentHTML("beforeend",`<span><b>Select All (${e.count})</b></span>`);
      const grid=document.createElement("div"); grid.className="pgrid";
      sacb.onchange=()=>{ e.pages.clear(); if(sacb.checked) for(let p=1;p<=e.count;p++) e.pages.add(p);
        grid.querySelectorAll("input").forEach(c=>c.checked=sacb.checked); syncBtn(); };
      body.appendChild(sa);
      for(let p=1;p<=e.count;p++){
        const lab=document.createElement("label"); lab.className="pchk";
        const cb=document.createElement("input"); cb.type="checkbox"; cb.checked=e.pages.has(p);
        cb.onchange=()=>{ cb.checked?e.pages.add(p):e.pages.delete(p); sacb.checked=(e.pages.size===e.count); syncBtn(); };
        lab.appendChild(cb); lab.insertAdjacentHTML("beforeend",`<span>${p}</span>`); grid.appendChild(lab);
      }
      body.appendChild(grid); addRange();
    }
    function addRange(){
      const wrap=document.createElement("div");
      wrap.innerHTML=`<input class="dd-range" type="text" placeholder="Or Type: 1-3,5,8" value="">`;
      const inp=wrap.querySelector(".dd-range");
      inp.oninput=()=>{ e.pages=new Set(parseRange(inp.value,e.count||9999));
        body.querySelectorAll(".pgrid input").forEach((c,ix)=>c.checked=e.pages.has(ix+1));
        const sa=body.querySelector(".sa input"); if(sa) sa.checked=(e.count&&e.pages.size===e.count); syncBtn(); };
      body.appendChild(wrap);
    }
    ppan.querySelectorAll(`input[name="pg${i}"]`).forEach(r=>r.onchange=()=>{ e.pagesMode=r.value; if(e.pagesMode==="all") e.pages.clear(); syncBtn(); buildChecks(); });
    if(e.pagesMode==="specific") buildChecks();
    pbtn.onclick=(ev)=>{ ev.stopPropagation(); const o=pdd.classList.contains("open"); closeAllDropdowns(); if(!o){ pdd.classList.add("open"); if(e.pagesMode==="specific"&&!body.childElementCount) buildChecks(); } };
    ppan.onclick=(ev)=>ev.stopPropagation();
    pdd.append(pbtn,ppan);

    const rm=document.createElement("button"); rm.className="rm"; rm.textContent="✕"; rm.title="Remove";
    rm.onclick=()=>{ files.splice(i,1); renderFiles(); toast("File removed"); };
    li.append(col,ldd,pdd,rm); fileListEl.appendChild(li);
  });
  refresh();
}
function refresh(){ convertBtn.disabled=!(files.length && files.every(f=>f.langs.size>0)); }

fileInput.onchange=()=>{ addFiles(fileInput.files); fileInput.value=""; };
drop.onclick=()=>fileInput.click();
drop.onkeydown=(e)=>{ if(e.key==="Enter"||e.key===" ") fileInput.click(); };
["dragover","dragenter"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.add("drag");}));
["dragleave","drop"].forEach(ev=>drop.addEventListener(ev,e=>{e.preventDefault();drop.classList.remove("drag");}));
drop.addEventListener("drop",e=>{ if(e.dataTransfer?.files) addFiles(e.dataTransfer.files); });

// ---------- output rendering (per-file) ----------
function dlLinks(r){ return r.downloads.map(d=>`<a href="/api/download/${JOB}/${encodeURIComponent(d.file)}" download>${d.label}</a>`).join(""); }
function renderResults(){
  const has=results.length>0;
  previewEmpty.style.display=has?"none":"flex";
  copyBtn.disabled=!has; viewBtn.disabled=!has;
  // tabs (only if >1 file)
  fileTabs.innerHTML="";
  if(results.length>1){
    results.forEach((r,i)=>{
      const t=document.createElement("button");
      t.className="ftab"+(i===curIdx?" on":"")+(r.error?" err":"");
      t.textContent=r.name; t.title=r.name;
      t.onclick=()=>{ curIdx=i; renderResults(); };
      fileTabs.appendChild(t);
    });
  }
  const r=results[curIdx];
  previewEl.value = r ? (r.error?("[ERROR] "+r.error):r.text) : "";
}
function currentText(){ return results[curIdx]?results[curIdx].text:""; }

copyBtn.onclick=async ()=>{ const t=previewEl.value; if(!t) return;
  try{ await navigator.clipboard.writeText(t); toast("Copied to clipboard"); }
  catch{ previewEl.select(); document.execCommand("copy"); toast("Copied to clipboard"); } };

// ---------- View modal ----------
function openModal(){
  if(!results.length) return;
  modal.hidden=false;
  modalList.innerHTML="";
  if(results.length>1){
    modalList.hidden=false;
    results.forEach((r,i)=>{
      const it=document.createElement("button");
      it.className="mitem"+(i===curIdx?" on":"")+(r.error?" err":"");
      it.textContent=r.name; it.title=r.name;
      it.onclick=()=>selectModal(i);
      modalList.appendChild(it);
    });
  }else modalList.hidden=true;
  selectModal(curIdx);
}
function selectModal(i){
  curIdx=i;
  modalList.querySelectorAll(".mitem").forEach((el,ix)=>el.classList.toggle("on",ix===i));
  const r=results[i];
  modalTitle.textContent=r?r.name:"Output";
  modalText.value=r?(r.error?("[ERROR] "+r.error):r.text):"";
  modalDl.innerHTML = r&&!r.error ? `<button class="m-copy" type="button">Copy</button>`+dlLinks(r) : "";
  const mc=modalDl.querySelector(".m-copy");
  if(mc) mc.onclick=async()=>{ try{ await navigator.clipboard.writeText(modalText.value); }catch{ modalText.select(); document.execCommand("copy"); } toast("Copied to clipboard"); };
  renderResults();
}
viewBtn.onclick=openModal;
modalClose.onclick=()=>modal.hidden=true;
modal.addEventListener("click",e=>{ if(e.target===modal) modal.hidden=true; });
document.addEventListener("keydown",e=>{ if(e.key==="Escape") modal.hidden=true; });

// ---------- clear all + auto cleanup ----------
function clearServer(){ for(const j of sessionJobs){ try{ navigator.sendBeacon(`/api/clear/${j}`); }catch(_){} } }
clearBtn.onclick=()=>{
  clearServer(); sessionJobs.clear(); JOB="";
  files.length=0; results=[]; curIdx=0;
  renderFiles(); renderResults();
  downloadsEl.innerHTML=""; fileTabs.innerHTML="";
  logEl.textContent=""; logEl.hidden=true; zipBtn.hidden=true;
  toast("Cleared — all data removed from server");
};
window.addEventListener("pagehide", clearServer);
window.addEventListener("beforeunload", clearServer);

// ---------- upload progress bars ----------
function buildUploadBars(){
  uploadProg.hidden=false;
  let html='<div class="up-title">Uploading…</div>';
  const rowHtml=(id,name)=>`<div class="up-row"><span class="up-name" title="${esc(name)}">${esc(name)}</span><div class="up-bar"><i id="${id}"></i></div><span class="up-pct" id="${id}p">0%</span></div>`;
  html+=rowHtml("uptotal","Total");
  files.forEach((f,i)=>{ html+=rowHtml("up"+i, f.file.name); });
  uploadProg.innerHTML=html;
}
function setBar(id,pct){ const b=document.getElementById(id), p=document.getElementById(id+"p");
  if(b) b.style.width=pct+"%"; if(p) p.textContent=Math.round(pct)+"%"; }
function updateUploadBars(loaded,total){
  setBar("uptotal", total?Math.min(100,loaded/total*100):0);
  const tot=files.reduce((a,f)=>a+f.file.size,0);
  let eff=Math.min(loaded,tot), acc=0;
  files.forEach((f,i)=>{ const s=f.file.size; let pct=0;
    if(eff>=acc+s) pct=100; else if(eff>acc) pct=(eff-acc)/s*100;
    setBar("up"+i,pct); acc+=s; });
}
function uploadBarsDone(){ setBar("uptotal",100); files.forEach((f,i)=>setBar("up"+i,100));
  const t=uploadProg.querySelector(".up-title"); if(t) t.textContent="Uploaded · Processing…"; }

// ---------- convert (streaming) ----------
convertBtn.onclick=async ()=>{
  if(!files.length) return;
  const formats=[]; if($("#fmtTxt").checked) formats.push("txt"); if($("#fmtDocx").checked) formats.push("docx");
  if(!formats.length){ setStatus("Pick At Least One Output Format.","err"); return; }
  for(const f of files){ if(!f.langs.size){ setStatus(`"${f.file.name}" mate language select karo.`,"err"); return; } }

  // purano session-job server par thi kaadi nakho (storage temporary)
  clearServer(); sessionJobs.clear();

  const options={
    dpi:parseInt($("#dpi").value)||300, force_ocr:$("#forceOcr").checked,
    layout:document.querySelector("input[name=layout]:checked").value,
    formats, font:$("#font").value.trim()||"Hind Vadodara", langs:[...bulkLangs],
    items:files.map(f=>({langs:[...f.langs], pages: f.pagesMode==="specific"?[...f.pages].sort((a,b)=>a-b).join(","):""})),
  };
  const fd=new FormData();
  files.forEach(f=>fd.append("files", f.file, f.file.name));
  fd.append("options", JSON.stringify(options));

  convertBtn.disabled=true; convertBtn.classList.add("busy");
  setStatus("Converting…","busy");
  downloadsEl.innerHTML=""; results=[]; curIdx=0; renderResults();
  zipBtn.hidden=true; logEl.textContent=""; logEl.hidden=false;

  buildUploadBars();
  let okCount=0, total=files.length, buf="", lastIdx=0;
  function drain(txt){ const chunk=txt.slice(lastIdx); lastIdx=txt.length; buf+=chunk;
    let nl; while((nl=buf.indexOf("\n"))>=0){ const line=buf.slice(0,nl); buf=buf.slice(nl+1);
      if(line.trim()){ try{ handle(JSON.parse(line)); }catch(_){} } } }
  try{
    await new Promise((resolve,reject)=>{
      const xhr=new XMLHttpRequest();
      xhr.open("POST","/api/convert");
      xhr.upload.onprogress=e=>{ if(e.lengthComputable) updateUploadBars(e.loaded,e.total); };
      xhr.upload.onload=()=>uploadBarsDone();
      xhr.onprogress=()=>drain(xhr.responseText);
      xhr.onload=()=>{ drain(xhr.responseText);
        if(xhr.status>=200 && xhr.status<300) resolve();
        else { let msg="HTTP "+xhr.status; try{ msg=JSON.parse(xhr.responseText).detail||msg; }catch(_){} reject(new Error(msg)); } };
      xhr.onerror=()=>reject(new Error("Network error"));
      xhr.send(fd);
    });
    setStatus(`Done — ${okCount}/${total} File(s) Converted.`);
  }catch(err){ setStatus("Failed: "+err.message,"err"); }
  finally{ convertBtn.disabled=false; convertBtn.classList.remove("busy"); uploadProg.hidden=true; }

  function handle(ev){
    if(ev.type==="start"){ JOB=ev.job; sessionJobs.add(ev.job); }
    else if(ev.type==="file_start"){ logLine(`▶ ${ev.name}  (${(ev.langs||[]).map(cap).join("+")})`); }
    else if(ev.type==="log"){ logLine(`    ${ev.msg}`); }
    else if(ev.type==="file_done"){
      results.push({name:ev.name, text:ev.text||"", downloads:ev.downloads||[], counts:ev.counts||{}, error:ev.error||null});
      const row=document.createElement("div"); row.className="dl";
      if(ev.error){ row.innerHTML=`<span class="dl-name">${esc(ev.name)}</span><span class="err">${esc(ev.error)}</span>`; logLine(`    [ERROR] ${ev.error}`); }
      else{ okCount++;
        const counts=Object.entries(ev.counts).map(([k,v])=>`${k} ${v}`).join(" · ");
        let html=`<span class="dl-name">${esc(ev.name)}</span>${dlLinks({downloads:ev.downloads})}`;
        if(counts) html+=`<span class="badge">${counts}</span>`;
        row.innerHTML=html; logLine(`    ✓ done`); }
      downloadsEl.appendChild(row);
      renderResults();
    }
    else if(ev.type==="done"){ uploadProg.hidden=true; if(ev.zip){ zipBtn.href=`/api/download/${ev.job}/${encodeURIComponent(ev.zip)}`; zipBtn.setAttribute("download",""); zipBtn.hidden=false; } }
  }
};

[downloadsEl, modalDl].forEach(el=>el.addEventListener("click",e=>{ const a=e.target.closest("a[download]"); if(a) toast("Downloading "+(a.textContent||"file")); }));
zipBtn.addEventListener("click",()=>toast("Downloading .zip"));

loadLanguages();

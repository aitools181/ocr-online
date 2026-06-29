const $ = (s) => document.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(msg, type="ok"){
  const w=$("#toasts"); if(!w) return;
  const t=document.createElement("div"); t.className="toast "+type;
  t.innerHTML=`<span class="ic">${type==="err"?"✕":"✓"}</span><span>${esc(msg)}</span>`;
  w.appendChild(t); requestAnimationFrame(()=>t.classList.add("show"));
  setTimeout(()=>{ t.classList.remove("show"); setTimeout(()=>t.remove(),250); },4000);
}
function fmtSize(b){ if(b<1024)return b+" B"; if(b<1048576)return (b/1024).toFixed(1)+" KB"; return (b/1048576).toFixed(1)+" MB"; }
function fmtDate(iso){ try{ return new Date(iso).toLocaleString(); }catch{ return iso; } }

// ---------- Users ----------
async function loadUsers(){
  const wrap=$("#usersWrap");
  let d; try{ d=await (await fetch("/api/admin/users")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  const us=d.users||[];
  let h='<table><thead><tr><th>Username</th><th>Role</th><th></th></tr></thead><tbody>';
  us.forEach(u=>{
    const role=`<span class="pill-role ${u.role==='admin'?'pill-admin':''}">${esc(u.role)}</span>`;
    const act=u.builtin?'<span class="muted">built-in</span>':`<button class="mini-danger" data-del-user="${esc(u.username)}">Delete</button>`;
    h+=`<tr><td>${esc(u.username)}</td><td>${role}</td><td style="text-align:right">${act}</td></tr>`;
  });
  h+='</tbody></table>';
  wrap.innerHTML=h;
  wrap.querySelectorAll("[data-del-user]").forEach(b=>b.onclick=()=>deleteUser(b.getAttribute("data-del-user")));
}
async function addUser(){
  const username=$("#nuUser").value.trim(), password=$("#nuPass").value;
  if(!username||!password){ toast("Enter username and password","err"); return; }
  try{
    const r=await fetch("/api/admin/users",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,password})});
    const d=await r.json();
    if(!r.ok||d.error){ toast(d.error||"Failed","err"); return; }
    $("#nuUser").value=""; $("#nuPass").value="";
    toast(`User "${username}" created`); loadUsers();
  }catch{ toast("Network error","err"); }
}
async function deleteUser(username){
  if(!confirm(`Delete user "${username}"?`)) return;
  try{
    const r=await fetch("/api/admin/users/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username})});
    const d=await r.json();
    if(!r.ok||d.error){ toast(d.error||"Failed","err"); return; }
    toast(`User "${username}" deleted`); loadUsers();
  }catch{ toast("Network error","err"); }
}

// ---------- Fonts ----------
async function loadFonts(){
  const wrap=$("#fontsWrap");
  let d; try{ d=await (await fetch("/api/admin/fonts")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  const fs=d.fonts||[];
  if(!fs.length){ wrap.innerHTML='<div class="empty">No uploaded fonts yet.</div>'; return; }
  let h='<table><thead><tr><th>Font Name</th><th>File</th><th></th></tr></thead><tbody>';
  fs.forEach(f=>{ h+=`<tr><td>${esc(f.name)}</td><td class="muted">${esc(f.file)}</td><td style="text-align:right"><button class="mini-danger" data-del-font="${esc(f.file)}">Delete</button></td></tr>`; });
  h+='</tbody></table>'; wrap.innerHTML=h;
  wrap.querySelectorAll("[data-del-font]").forEach(b=>b.onclick=()=>deleteFont(b.getAttribute("data-del-font")));
}
async function deleteFont(file){
  if(!confirm(`Delete font "${file}"?`)) return;
  try{
    const r=await fetch("/api/admin/fonts/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({file})});
    const d=await r.json();
    if(!r.ok||d.error){ toast(d.error||"Failed","err"); return; }
    toast("Font deleted"); loadFonts();
  }catch{ toast("Network error","err"); }
}

// ---------- Jobs ----------
let JOBS=[];
async function loadJobs(){
  const wrap=$("#tableWrap");
  let d; try{ d=await (await fetch("/api/admin/list")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  JOBS=d.jobs||[];
  $("#meta").textContent=`${JOBS.length} job(s) · output kept ${d.ttl_hours}h`;
  if(!JOBS.length){ wrap.innerHTML='<div class="empty">No stored jobs.</div>'; $("#selAll").checked=false; updateDelBtn(); return; }
  let h='<table><thead><tr><th></th><th>Completed</th><th>Files</th><th>Size</th><th>Job ID</th></tr></thead><tbody>';
  JOBS.forEach(j=>{
    const files=j.files.length?j.files.map(f=>`<span class="fn">${esc(f.name)}</span>`).join(""):'<span class="muted">—</span>';
    const act=j.active?'<span class="pill-active">active</span>':'';
    h+=`<tr><td><input type="checkbox" class="jchk" value="${esc(j.job)}" ${j.active?"disabled":""}/></td>`+
       `<td>${fmtDate(j.completed)}${act}</td><td>${files}</td><td>${fmtSize(j.total_size)}</td><td><span class="jid">${esc(j.job)}</span></td></tr>`;
  });
  h+='</tbody></table>'; wrap.innerHTML=h;
  wrap.querySelectorAll(".jchk").forEach(c=>c.onchange=updateDelBtn);
  $("#selAll").checked=false; updateDelBtn();
}
function selected(){ return [...document.querySelectorAll(".jchk:checked")].map(c=>c.value); }
function updateDelBtn(){ const n=selected().length; const b=$("#delBtn"); b.disabled=n===0; b.textContent=n?`Delete Selected (${n})`:"Delete Selected"; }
$("#selAll").onchange=(e)=>{ document.querySelectorAll(".jchk:not(:disabled)").forEach(c=>c.checked=e.target.checked); updateDelBtn(); };
$("#delBtn").onclick=async()=>{
  const jobs=selected(); if(!jobs.length) return;
  if(!confirm(`Delete ${jobs.length} job(s)? This removes their output permanently.`)) return;
  try{
    const r=await fetch("/api/admin/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({jobs})});
    const d=await r.json();
    toast(`Deleted ${d.deleted.length} job(s)`); loadJobs();
  }catch{ toast("Network error","err"); }
};
$("#refreshBtn").onclick=loadJobs;
$("#addUserBtn").onclick=addUser;
$("#logoutBtn").onclick=async()=>{ try{ await fetch("/api/logout",{method:"POST"}); }catch{} window.location.href="/login"; };

loadUsers(); loadFonts(); loadJobs();

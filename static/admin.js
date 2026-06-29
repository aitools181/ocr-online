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
  let h='<table><thead><tr><th>Username</th><th>Role</th><th style="text-align:right">Actions</th></tr></thead><tbody>';
  us.forEach(u=>{
    const role=`<span class="pill-role ${u.role==='admin'?'pill-admin':''}">${esc(u.role)}</span>`;
    let act;
    if(u.builtin){
      act='<span class="muted">built-in</span>';
    } else {
      act=`<button class="mini-reset" data-reset-user="${esc(u.username)}" title="Password Reset">🔑 Reset</button>`+
          `<button class="mini-danger" data-del-user="${esc(u.username)}">Delete</button>`;
    }
    h+=`<tr><td>${esc(u.username)}</td><td>${role}</td><td style="text-align:right">${act}</td></tr>`;
  });
  h+='</tbody></table>';
  wrap.innerHTML=h;
  wrap.querySelectorAll("[data-del-user]").forEach(b=>b.onclick=()=>deleteUser(b.getAttribute("data-del-user")));
  wrap.querySelectorAll("[data-reset-user]").forEach(b=>b.onclick=()=>openResetModal(b.getAttribute("data-reset-user")));
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

// ---------- Password Reset Modal ----------
function openResetModal(username){
  $("#resetUsername").textContent=username;
  $("#resetNewPass").value="";
  $("#resetConfirmPass").value="";
  $("#resetModal").classList.add("open");
  setTimeout(()=>$("#resetNewPass").focus(), 50);
}
function closeResetModal(){
  $("#resetModal").classList.remove("open");
}
async function saveResetPassword(){
  const username=$("#resetUsername").textContent;
  const newPass=$("#resetNewPass").value;
  const confirmPass=$("#resetConfirmPass").value;
  if(!newPass){ toast("New password enter karo","err"); return; }
  if(newPass.length<4){ toast("Password minimum 4 characters joiye","err"); return; }
  if(newPass!==confirmPass){ toast("Passwords match nathi karya","err"); return; }
  try{
    const r=await fetch("/api/admin/users/reset-password",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username,new_password:newPass})});
    const d=await r.json();
    if(!r.ok||d.error){ toast(d.error||"Failed","err"); return; }
    toast(`"${username}" no password reset thayo`);
    closeResetModal();
  }catch{ toast("Network error","err"); }
}
$("#resetCancelBtn").onclick=closeResetModal;
$("#resetSaveBtn").onclick=saveResetPassword;
$("#resetModal").onclick=(e)=>{ if(e.target===e.currentTarget) closeResetModal(); };
// Enter key support in modal
document.addEventListener("keydown",(e)=>{
  if(e.key==="Escape") closeResetModal();
  if(e.key==="Enter" && $("#resetModal").classList.contains("open")) saveResetPassword();
});

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

// ---------- Jobs with Pagination ----------
let JOBS=[];
let PAGE=1;
let PAGE_SIZE=25;

function renderJobsTable(){
  const wrap=$("#tableWrap");
  if(!JOBS.length){ wrap.innerHTML='<div class="empty">No stored jobs.</div>'; $("#selAll").checked=false; updateDelBtn(); renderPagination(); return; }

  const total=JOBS.length;
  const totalPages=Math.ceil(total/PAGE_SIZE);
  if(PAGE>totalPages) PAGE=totalPages;
  if(PAGE<1) PAGE=1;
  const start=(PAGE-1)*PAGE_SIZE;
  const end=Math.min(start+PAGE_SIZE, total);
  const pageJobs=JOBS.slice(start,end);

  let h='<table><thead><tr><th></th><th>Completed</th><th>User</th><th>Files</th><th>Size</th><th>Job ID</th></tr></thead><tbody>';
  pageJobs.forEach(j=>{
    const files=j.files.length?j.files.map(f=>`<span class="fn">${esc(f.name)}</span>`).join(""):'<span class="muted">—</span>';
    const act=j.active?'<span class="pill-active">active</span>':'';
    const userBadge=`<span style="font-size:12px;font-weight:600;color:var(--teal)">${esc(j.username||"—")}</span>`;
    h+=`<tr><td><input type="checkbox" class="jchk" value="${esc(j.job)}" ${j.active?"disabled":""}/></td>`+
       `<td>${fmtDate(j.completed)}${act}</td><td>${userBadge}</td><td>${files}</td><td>${fmtSize(j.total_size)}</td><td><span class="jid">${esc(j.job)}</span></td></tr>`;
  });
  h+='</tbody></table>';
  wrap.innerHTML=h;
  wrap.querySelectorAll(".jchk").forEach(c=>c.onchange=updateDelBtn);
  $("#selAll").checked=false;
  updateDelBtn();
  renderPagination();
}

function renderPagination(){
  let pWrap=$("#paginationWrap");
  if(!pWrap){
    pWrap=document.createElement("div");
    pWrap.id="paginationWrap";
    pWrap.style.cssText="display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-top:12px;font-size:13px";
    $("#tableWrap").after(pWrap);
  }
  if(!JOBS.length){ pWrap.innerHTML=""; return; }

  const total=JOBS.length;
  const totalPages=Math.ceil(total/PAGE_SIZE);
  const start=(PAGE-1)*PAGE_SIZE+1;
  const end=Math.min(PAGE*PAGE_SIZE, total);

  // Page size selector
  let html=`<span style="color:var(--muted)">Rows per page:</span>
  <select id="pageSizeSelect" style="padding:4px 8px;border:1px solid var(--line);border-radius:7px;font:inherit;font-size:13px">
    <option value="25" ${PAGE_SIZE===25?"selected":""}>25</option>
    <option value="50" ${PAGE_SIZE===50?"selected":""}>50</option>
    <option value="100" ${PAGE_SIZE===100?"selected":""}>100</option>
  </select>
  <span style="color:var(--muted);margin-left:6px">${start}–${end} of ${total}</span>
  <span style="flex:1"></span>`;

  // Prev button
  html+=`<button id="prevPage" style="padding:5px 12px;border:1px solid var(--line);border-radius:7px;font:inherit;font-size:13px;cursor:pointer;background:#fff" ${PAGE<=1?"disabled":""}>← Prev</button>`;

  // Page numbers (max 5 visible)
  const maxBtns=5;
  let pStart=Math.max(1,PAGE-Math.floor(maxBtns/2));
  let pEnd=Math.min(totalPages,pStart+maxBtns-1);
  if(pEnd-pStart<maxBtns-1) pStart=Math.max(1,pEnd-maxBtns+1);

  for(let i=pStart;i<=pEnd;i++){
    const active=i===PAGE;
    html+=`<button class="pg-btn" data-pg="${i}" style="padding:5px 10px;border:1px solid ${active?'var(--saffron)':'var(--line)'};border-radius:7px;font:inherit;font-size:13px;cursor:pointer;background:${active?'var(--saffron)':'#fff'};color:${active?'#fff':'inherit'};font-weight:${active?'600':'400'}">${i}</button>`;
  }

  // Next button
  html+=`<button id="nextPage" style="padding:5px 12px;border:1px solid var(--line);border-radius:7px;font:inherit;font-size:13px;cursor:pointer;background:#fff" ${PAGE>=totalPages?"disabled":""}>Next →</button>`;

  pWrap.innerHTML=html;

  // Event listeners
  $("#pageSizeSelect").onchange=(e)=>{ PAGE_SIZE=parseInt(e.target.value); PAGE=1; renderJobsTable(); };
  const prevBtn=$("#prevPage"); if(prevBtn) prevBtn.onclick=()=>{ if(PAGE>1){PAGE--;renderJobsTable();} };
  const nextBtn=$("#nextPage"); if(nextBtn) nextBtn.onclick=()=>{ if(PAGE<totalPages){PAGE++;renderJobsTable();} };
  pWrap.querySelectorAll(".pg-btn").forEach(b=>b.onclick=()=>{ PAGE=parseInt(b.getAttribute("data-pg")); renderJobsTable(); });
}

async function loadJobs(){
  const wrap=$("#tableWrap");
  let d; try{ d=await (await fetch("/api/admin/list")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  JOBS=d.jobs||[];
  $("#meta").textContent=`${JOBS.length} job(s) · output kept ${d.ttl_hours}h`;
  renderJobsTable();
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

// Version badge
(function(){
  const el = document.getElementById("versionBadge");
  if(!el) return;
  el.textContent = "v2.2  ·  29 Jun 2025";
})();

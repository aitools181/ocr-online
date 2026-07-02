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
// Date cell with machine-readable data-date (YYYY-MM-DD) for reliable filtering/sorting
function dateCell(tsSeconds, extraClass){
  if(!tsSeconds) return `<td class="${extraClass||'muted'}">—</td>`;
  const d=new Date(tsSeconds*1000);
  const iso=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  return `<td class="${extraClass||'muted'}" data-date="${iso}">${esc(d.toLocaleString())}</td>`;
}
// Get a cell's date value: prefer data-date attribute, else parse text
function _cellDate(rowHtml, colIdx){
  const tmp=document.createElement("tr");
  tmp.innerHTML=rowHtml.replace(/^<tr[^>]*>/,"").replace(/<\/tr>\s*$/,"");
  const tds=tmp.querySelectorAll("td");
  if(colIdx>=tds.length) return null;
  const dd=tds[colIdx].getAttribute("data-date");
  return dd || null;
}

// Close any open filter dropdown (column or value) when clicking outside
document.addEventListener("click",(e)=>{
  document.querySelectorAll("[data-msdd] .ms-panel:not([hidden]), [data-coldd] .ms-panel:not([hidden])").forEach(panel=>{
    const wrap=panel.closest("[data-msdd],[data-coldd]");
    if(wrap && !wrap.contains(e.target)){ panel.hidden=true; }
  });
});

// Version badge
fetch("/api/version").then(r=>r.json()).then(d=>{
  const el=$("#versionBadge"); if(el) el.textContent=`v${d.version} · ${d.date}`;
}).catch(()=>{});


// ---------- Users ----------
let _usersData=[], _rolesData=[], _userPage=1, _userPageSize=25, _editingUser=null;

async function loadUsers(){
  const wrap=$("#usersWrap");
  let d; try{ d=await (await fetch("/api/admin/users")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  _usersData=d.users||[]; _rolesData=d.roles||[];
  renderUsers();
}

function renderUsers(){
  const wrap=$("#usersWrap");
  const us=_usersData;
  if(!us.length){ wrap.innerHTML='<div class="empty">No users yet.</div>'; return; }
  wrap.innerHTML='<div id="usersTableWrap"></div>';
  const rows=us.map(u=>{
    const role=`<span class="pill-role ${u.role==='admin'?'pill-admin':''}">${esc(u.role)}</span>`;
    let statusPill, act;
    if(u.status==='pending'){
      statusPill=`<span class="status-pill status-queued">⏳ Pending</span>`;
      act=`<button class="add-btn" style="padding:5px 10px;font-size:12px" data-approve-user="${esc(u.username)}">✅ Approve</button>`+
          `<button class="mini-danger" data-reject-user="${esc(u.username)}">✗ Reject</button>`;
    } else if(u.status==='rejected'){
      statusPill=`<span class="status-pill status-error">🚫 Rejected</span>`;
      act=`<button class="mini-reset" data-reason-view="${esc(u.username)}" title="View rejection reason">📋 Reason</button>`+
          `<button class="mini-danger" data-delrej-user="${esc(u.username)}">Delete</button>`;
    } else {
      statusPill=u.status==='inactive'
        ? `<span class="status-pill status-error">Inactive</span>`
        : `<span class="status-pill status-completed">✓ Active</span>`;
      const toggleLbl=u.status==='inactive'?'Activate':'Deactivate';
      act=`<button class="mini-reset" data-edit-user="${esc(u.username)}">✏️ Edit</button>`+
          `<button class="mini-reset" data-toggle-user="${esc(u.username)}">${toggleLbl}</button>`+
          `<button class="mini-reset" data-reset-user="${esc(u.username)}" title="Password Reset">🔑</button>`+
          `<button class="mini-danger" data-del-user="${esc(u.username)}">Delete</button>`;
    }
    return `<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.first_name||'—')}</td><td>${esc(u.last_name||'—')}</td><td class="muted">${esc(u.email||'—')}</td><td>${role}</td><td>${statusPill}</td><td style="text-align:right;white-space:nowrap">${act}</td></tr>`;
  });
  const header=`<tr><th>Username</th><th>First Name</th><th>Last Name</th><th>Email</th><th>Role</th><th>Status</th><th style="text-align:right">Actions</th></tr>`;
  const bindUsers=(wrapEl)=>{
    wrapEl.querySelectorAll("[data-del-user]").forEach(b=>b.onclick=()=>deleteUser(b.getAttribute("data-del-user")));
    wrapEl.querySelectorAll("[data-reset-user]").forEach(b=>b.onclick=()=>openResetModal(b.getAttribute("data-reset-user")));
    wrapEl.querySelectorAll("[data-edit-user]").forEach(b=>b.onclick=()=>openUserModal(b.dataset.editUser));
    wrapEl.querySelectorAll("[data-toggle-user]").forEach(b=>b.onclick=async()=>{
      await fetch("/api/admin/users/toggle-active",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:b.dataset.toggleUser})});
      toast("User status updated"); loadUsers();
    });
    wrapEl.querySelectorAll("[data-approve-user]").forEach(b=>b.onclick=async()=>{
      b.disabled=true; b.textContent="…";
      const r=await fetch("/api/admin/users/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:b.dataset.approveUser})});
      const dd=await r.json();
      if(r.ok&&dd.ok){ toast("User approved & notified"); loadUsers(); }
      else { toast(dd.error||"Failed","err"); b.disabled=false; b.textContent="✅ Approve"; }
    });
    wrapEl.querySelectorAll("[data-reject-user]").forEach(b=>b.onclick=()=>openRejectModal(b.dataset.rejectUser));
    wrapEl.querySelectorAll("[data-reason-view]").forEach(b=>b.onclick=()=>{
      const u=_usersData.find(x=>x.username===b.dataset.reasonView);
      $("#reasonViewBody").innerHTML=`
        <div style="background:#faf7f1;border-radius:10px;padding:14px 16px;margin-bottom:12px">
          <div style="font-size:12px;color:#888">User</div>
          <div style="font-size:15px;font-weight:700;color:#2c2c4a">${esc(u.first_name||'')} ${esc(u.last_name||'')} (${esc(u.username)})</div>
        </div>
        <div style="font-size:12px;color:#888;margin-bottom:6px">REASON</div>
        <div style="background:#fff;border-left:3px solid #e74c3c;border-radius:8px;padding:12px 14px;font-size:14px;color:#333;line-height:1.5">${esc(u.reject_reason||'—')}</div>`;
      $("#reasonViewModal").classList.add("open");
    });
    wrapEl.querySelectorAll("[data-delrej-user]").forEach(b=>b.onclick=async()=>{
      if(!confirm(`Delete rejected record for "${b.dataset.delrejUser}"?`)) return;
      await fetch("/api/admin/users/delete-rejected",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:b.dataset.delrejUser})});
      toast("Record deleted"); loadUsers();
    });
  };
  renderPaginatedTable("usersTableWrap", rows, header, "user", {defaultSize:25, emptyMsg:"No users yet.", onBind:bindUsers, noSort:[6]});
}

// User create/edit modal
function openUserModal(username){
  _editingUser = username || null;
  const isEdit = !!username;
  $("#userModalTitle").textContent = isEdit ? "✏️ Edit User" : "👤 Create User";
  $("#userModalErr").style.display="none";
  // role dropdown
  const roleSel=$("#umRole");
  roleSel.innerHTML=_rolesData.map(r=>`<option value="${esc(r)}">${esc(r)}</option>`).join("");
  $("#umPassRow").style.display = isEdit ? "none" : "block";  // edit ma password alag reset flow
  $("#umSaveBtn").textContent = isEdit ? "Save Changes" : "Create User";
  $("#umUserHint").textContent = "";
  if(isEdit){
    const u=_usersData.find(x=>x.username===username);
    $("#umFname").value=u.first_name||""; $("#umLname").value=u.last_name||"";
    $("#umUser").value=u.username; $("#umUser").disabled=true;
    $("#umEmail").value=u.email||""; roleSel.value=u.role;
  } else {
    $("#umFname").value=""; $("#umLname").value=""; $("#umUser").value="";
    $("#umUser").disabled=false; $("#umEmail").value=""; $("#umPass").value="";
    if(_rolesData.includes("user")) roleSel.value="user";
  }
  $("#userModal").classList.add("open");
}

async function addUser(){
  // legacy caller — now opens modal
  openUserModal(null);
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
  wrap.innerHTML='<div id="fontsTableWrap"></div>';
  const rows=fs.map(f=>`<tr><td>${esc(f.name)}</td><td class="muted">${esc(f.file)}</td><td style="text-align:right"><button class="mini-danger" data-del-font="${esc(f.file)}">Delete</button></td></tr>`);
  const header=`<tr><th>Font Name</th><th>File</th><th style="text-align:right">Action</th></tr>`;
  renderPaginatedTable("fontsTableWrap", rows, header, "fonts", {defaultSize:10, emptyMsg:"No uploaded fonts yet.", noSort:[2],
    onBind:(el)=>{ el.querySelectorAll("[data-del-font]").forEach(b=>b.onclick=()=>deleteFont(b.getAttribute("data-del-font"))); }});
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
$("#refreshBtn") && ($("#refreshBtn").onclick=loadJobs);
$("#addUserBtn") && ($("#addUserBtn").onclick=addUser);
$("#logoutBtn") && ($("#logoutBtn").onclick=async()=>{ try{ await fetch("/api/logout",{method:"POST"}); }catch{} window.location.href="/login"; });

// Tab data loads lazily via the tab controller — no eager load here.


// ===================== Dashboard (Step 5) =====================
function fmtSecD(s){ s=Math.round(s||0); if(s<60) return s+"s"; const m=Math.floor(s/60); if(m<60) return m+"m "+(s%60)+"s"; const h=Math.floor(m/60); return h+"h "+(m%60)+"m"; }
function statusPill(st){ return `<span class="status-pill status-${esc(st)}">${esc(st)}</span>`; }

async function loadDashSummary(range){
  try{
    const d = await (await fetch(`/api/admin/dashboard/summary?range=${range}`)).json();
    const cards = [
      ["Total Jobs", d.total_jobs, ""], ["Completed", d.completed, "good"],
      ["Pending", d.pending, "warn"], ["Failed", d.failed, "bad"],
      ["Active Users", d.total_users, ""], ["Total Pages Converted", d.total_pages, ""],
      ["Avg Duration / File", fmtSecD(d.avg_duration_sec), ""], ["Queue Depth", d.queue_depth, ""],
      ["Avg Sec / Page", d.avg_sec_per_page, ""],
      ["Cloud Storage", d.storage_enabled ? "✅ Connected" : "⚠️ Not configured", d.storage_enabled?"good":"warn"],
    ];
    $("#dashSummary").innerHTML = cards.map(([l,v,cls])=>
      `<div class="dash-card ${cls}"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }catch{ $("#dashSummary").innerHTML = `<div class="empty">Could not load summary.</div>`; }
}

async function loadDashLive(){
  try{
    const d = await (await fetch("/api/admin/dashboard/live")).json();
    const stats = [
      [d.total_online, "Online Now"], [d.logged_in_online, "Logged In"],
      [d.pre_login_online, "On Login Page"], [d.total_views, "Total Page Views"],
      [d.pre_login_views, "Pre-Login Views"], [d.post_login_views, "Post-Login Views"],
    ];
    $("#dashLive").innerHTML = stats.map(([v,l])=>
      `<div class="live-stat"><div class="v">${esc(v)}</div><div class="l">${esc(l)}</div></div>`).join("");
  }catch{ $("#dashLive").innerHTML=""; }
}

async function loadDashUserwise(range){
  try{
    const rq = range ? `?range=${encodeURIComponent(range)}` : "";
    const d = await (await fetch("/api/admin/dashboard/userwise"+rq)).json();
    const rows = (d.users||[]).map((u,i)=>
      `<tr><td class="srno">${i+1}</td><td><b>${esc(u.username)}</b></td>
       <td class="muted">${esc(u.ip||"—")}</td><td class="muted">${esc(u.location||"—")}</td>
       <td>${u.total}</td><td>${u.pages_done||0}</td>
       <td>${u.failed>0?`<span class="status-pill status-error">${u.failed}</span>`:u.failed}</td>
       <td>${u.pages_failed>0?`<span class="status-pill status-error">${u.pages_failed}</span>`:(u.pages_failed||0)}</td></tr>`);
    const header=`<tr><th>Sr No.</th><th>User</th><th>IP</th><th>Location</th><th>Total Job Upload</th><th>Total Pages Converted</th><th>Total Job Failed</th><th>Total Pages Failed</th></tr>`;
    renderPaginatedTable("dashUserwise", rows, header, "userwise", {defaultSize:10, emptyMsg:"No job data yet.", tableClass:"tbl-center"});
  }catch{ $("#dashUserwise").innerHTML = `<div class="empty">Could not load.</div>`; }
}

async function loadDashFailed(){
  try{
    const d = await (await fetch("/api/admin/dashboard/failed-uploads")).json();
    const rows = (d.jobs||[]).map(j=>
      `<tr><td><span class="jid">${esc(j.job_id)}</span><span class="fn">${esc(j.original_filename||"")}</span></td>
       <td>${esc(j.username)}</td><td>${j.upload_attempts||0}/${d.max_attempts}</td>
       <td class="muted" style="max-width:160px">${esc((j.error_message||"").slice(0,80))}</td>
       <td><button class="mini-reset" data-jid="${esc(j.job_id)}">Retry now</button></td></tr>`).join("");
    $("#dashFailed").innerHTML = d.jobs && d.jobs.length
      ? `<table><thead><tr><th>File</th><th>User</th><th>Attempts</th><th>Last Error</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty">No pending/failed uploads. 🎉</div>`;
    $("#dashFailed").querySelectorAll("[data-jid]").forEach(btn=>{
      btn.onclick=async()=>{
        btn.disabled=true; btn.textContent="Retrying…";
        try{
          const r=await fetch("/api/admin/dashboard/retry-upload",{method:"POST",
            headers:{"Content-Type":"application/json"}, body:JSON.stringify({job_id:btn.dataset.jid})});
          const dd=await r.json();
          if(r.ok&&dd.ok){ toast("Upload retried successfully"); loadDashFailed(); }
          else { toast(dd.error||"Retry failed","err"); btn.disabled=false; btn.textContent="Retry now"; }
        }catch{ toast("Network error","err"); btn.disabled=false; btn.textContent="Retry now"; }
      };
    });
  }catch{ $("#dashFailed").innerHTML = `<div class="empty">Could not load.</div>`; }
}

async function loadDashLogins(range){
  try{
    const rq = range ? `&range=${encodeURIComponent(range)}` : "";
    const d = await (await fetch(`/api/admin/dashboard/logins?limit=500${rq}`)).json();
    const rows = (d.logins||[]).map(l=>
      `<tr><td>${esc(l.username||"—")}</td><td>${esc(l.ip||"—")}</td>
       <td class="muted" style="max-width:200px">${esc((l.device||"").slice(0,60))}</td>
       <td>${esc(l.location||"—")}</td>
       <td>${l.success?'<span class="status-pill status-completed">success</span>':'<span class="status-pill status-error">failed</span>'}</td>
       ${dateCell(l.timestamp)}</tr>`);
    const header=`<tr><th>User</th><th>IP</th><th>Device</th><th>Location</th><th>Status</th><th>Time</th></tr>`;
    renderPaginatedTable("dashLogins", rows, header, "logins", {defaultSize:10, emptyMsg:"No login history yet."});
  }catch{ $("#dashLogins").innerHTML = `<div class="empty">Could not load.</div>`; }
}

async function loadDashJobs(){
  const search = $("#jobSearch").value.trim();
  const status = $("#jobStatusFilter").value;
  const params = new URLSearchParams();
  if(search) params.set("search", search);
  if(status) params.set("status", status);
  try{
    const d = await (await fetch(`/api/admin/dashboard/jobs?${params.toString()}`)).json();
    _pgState["jobsearch"] = {page:1, size:(_pgState["jobsearch"]?_pgState["jobsearch"].size:10)};
    const rows = (d.jobs||[]).map(j=>
      `<tr><td><span class="jid">${esc(j.job_id)}</span><span class="fn">${esc(j.original_filename||"")}</span></td>
       <td>${esc(j.username)}</td><td>${statusPill(j.status)}</td>
       <td>${j.pages||0}</td><td>${j.duration_sec?fmtSecD(j.duration_sec):"—"}</td>
       <td class="muted">${esc(j.cloud_provider||"—")}</td>
       ${dateCell(j.created_at)}</tr>`);
    const header=`<tr><th>File</th><th>User</th><th>Status</th><th>Pages</th><th>Duration</th><th>Cloud</th><th>Created</th></tr>`;
    renderPaginatedTable("dashJobs", rows, header, "jobsearch", {defaultSize:10, emptyMsg:"No matching jobs."});
  }catch{ $("#dashJobs").innerHTML = `<div class="empty">Could not load.</div>`; }
}

function refreshDashboard(range){
  loadDashSummary(range); loadDashLive(); loadDashUserwise(range);
  loadDashFailed(); loadDashLogins(range); loadDashJobs();
}

let _dashRange = "month";
if($("#dashCard")){
  const rangeGroup = $("#dashRangeGroup");
  rangeGroup.querySelectorAll("button").forEach(btn=>{
    btn.onclick=()=>{
      rangeGroup.querySelectorAll("button").forEach(b=>b.classList.remove("active"));
      btn.classList.add("active");
      _dashRange = btn.dataset.range;
      refreshDashboard(_dashRange);
    };
  });
  $("#jobSearchBtn").onclick = loadDashJobs;
  $("#jobSearch").addEventListener("keydown", e=>{ if(e.key==="Enter") loadDashJobs(); });
  refreshDashboard(_dashRange);
  setInterval(loadDashLive, 20000);                          // live counter refresh
  setInterval(()=>loadDashSummary(_dashRange), 60000);     // periodic summary refresh
}

// ===================== Cloud Storage Admin Panel (Step 6) =====================
(function(){
  const panel=$("#cloudPanel"),
        saveBtn=$("#cloudSaveBtn"), testBtn=$("#cloudTestBtn"),
        providerSel=$("#cloudProvider"), gFields=$("#cloudFieldsGoogle"), oFields=$("#cloudFieldsOneDrive"),
        errEl=$("#cloudConfigErr"), okEl=$("#cloudConfigOk");
  if(!panel) return;

  function showProviderFields(p){
    gFields.hidden = p!=="google_drive";
    oFields.hidden = p!=="onedrive";
  }
  providerSel.onchange=()=>showProviderFields(providerSel.value);

  async function loadCloudStatus(){
    try{
      const d = await (await fetch("/api/admin/storage/status")).json();
      const hasProvider = d.provider && d.provider !== "none";
      const toggleBtn = $("#cloudToggleBtn");

      let dotCls, label;
      if(!hasProvider){
        dotCls = "dot";
        label = "Not configured (files stay on server only)";
        toggleBtn.hidden = true;
      } else if(!d.active){
        dotCls = "dot warn";
        label = `<b>Inactive</b> — ${esc(d.provider)} configured but uploads paused`;
        toggleBtn.hidden = false;
        toggleBtn.textContent = "⚡ Activate";
        toggleBtn.className = "cloud-toggle-btn activate";
      } else if(d.connected){
        dotCls = "dot on";
        label = `<b>Active</b> — Connected to <b>${esc(d.provider)}</b>`;
        toggleBtn.hidden = false;
        toggleBtn.textContent = "⏸ Deactivate";
        toggleBtn.className = "cloud-toggle-btn deactivate";
      } else {
        dotCls = "dot warn";
        label = `Configured (${esc(d.provider)}) but connection failed — check credentials`;
        toggleBtn.hidden = false;
        toggleBtn.textContent = "⏸ Deactivate";
        toggleBtn.className = "cloud-toggle-btn deactivate";
      }

      $("#cloudStatusBox").innerHTML =
        `<span class="${dotCls}"></span><span>${label}</span>` +
        (d.pending_count ? `<span class="status-pill status-error" style="margin-left:auto">${d.pending_count} pending</span>` : "");

      providerSel.value = d.provider || "none";
      showProviderFields(providerSel.value);
      if(d.provider==="google_drive" && d.google_drive){
        $("#gdRootFolderId").value = d.google_drive.root_folder_id||"";
        $("#gdClientEmail").value  = d.google_drive.client_email||"";
        $("#gdProjectId").value    = d.google_drive.project_id||"";
        $("#gdExistingNote").textContent = d.google_drive.private_key_configured
          ? "✓ Private key already saved — leave blank to keep it." : "";
      }
      if(d.provider==="onedrive" && d.onedrive){
        $("#odTenantId").value = d.onedrive.tenant_id||"";
        $("#odClientId").value = d.onedrive.client_id||"";
        $("#odDriveId").value = d.onedrive.drive_id||"";
        $("#odRootPath").value = d.onedrive.root_path||"/SMVS-OCR";
        $("#odClientSecret").placeholder = d.onedrive.client_secret_configured
          ? "•••• already set — leave blank to keep" : "Client secret";
      }
    }catch{ $("#cloudStatusBox").innerHTML = `<span class="dot"></span><span>Could not load status.</span>`; }
  }

  // Toggle active/inactive
  document.addEventListener("click", async (e)=>{
    if(e.target.id !== "cloudToggleBtn") return;
    const btn = e.target;
    btn.disabled = true;
    try{
      const r = await fetch("/api/admin/storage/toggle-active", {method:"POST"});
      const d = await r.json();
      if(r.ok && d.ok){
        toast(d.active ? "Cloud storage activated — uploads will resume." : "Cloud storage deactivated — credentials are safe, uploads paused.");
        loadCloudStatus();
      } else { toast(d.error||"Toggle failed","err"); }
    }catch{ toast("Network error","err"); }
    btn.disabled = false;
  });

  async function loadCloudPending(){
    try{
      // Pending/failed (retry button section)
      const df = await (await fetch("/api/admin/dashboard/failed-uploads")).json();
      const failRows = (df.jobs||[]).map(j=>
        `<tr><td><span class="jid">${esc(j.job_id)}</span><span class="fn">${esc(j.original_filename||"")}</span></td>
         <td>${esc(j.username)}</td><td>${j.upload_attempts||0}/${df.max_attempts}</td>
         <td class="muted">${esc((j.error_message||"").slice(0,60))}</td>
         <td><button class="mini-reset" data-jid="${esc(j.job_id)}">Retry</button></td></tr>`);
      const header=`<tr><th>File</th><th>User</th><th>Attempts</th><th>Error</th><th></th></tr>`;
      const bindRetry=(el)=>{
        el.querySelectorAll("[data-jid]").forEach(btn=>{
          btn.onclick=async()=>{
            btn.disabled=true; btn.textContent="…";
            try{
              const r=await fetch("/api/admin/dashboard/retry-upload",{method:"POST",
                headers:{"Content-Type":"application/json"}, body:JSON.stringify({job_id:btn.dataset.jid})});
              const dd=await r.json();
              if(r.ok&&dd.ok){ toast("Uploaded successfully"); loadCloudPending(); loadCloudStatus(); loadCloudAllJobs(); }
              else { toast(dd.error||"Retry failed","err"); btn.disabled=false; btn.textContent="Retry"; }
            }catch{ toast("Network error","err"); btn.disabled=false; btn.textContent="Retry"; }
          };
        });
      };
      renderPaginatedTable("cloudPendingWrap", failRows, header, "cloudpending", {defaultSize:10, emptyMsg:"No pending/failed uploads. 🎉", onBind:bindRetry, noSort:[4]});
    }catch{ $("#cloudPendingWrap").innerHTML = `<div class="empty">Could not load.</div>`; }
  }

  async function loadCloudAllJobs(){
    try{
      const d = await (await fetch("/api/admin/storage/jobs")).json();
      const rows=(d.jobs||[]).map((j,i)=>{
        const uploadStatus = j.cloud_provider
          ? `<span class="status-pill status-completed">✓ ${esc(j.cloud_provider)}</span>`
          : j.status==="upload_failed"
            ? `<span class="status-pill status-error">Failed</span>`
            : j.status==="uploading"
              ? `<span class="status-pill status-queued">Uploading…</span>`
              : `<span class="status-pill status-queued">${esc(j.status)}</span>`;
        const serverStatus = j.cloud_provider
          ? `<span class="status-pill status-completed">Removed</span>`
          : `<span class="status-pill status-queued">On Server</span>`;
        const link = j.cloud_folder_link
          ? `<a href="${esc(j.cloud_folder_link)}" target="_blank" style="font-size:12px;font-weight:600;color:var(--saffron2)">📂 Open &amp; Download ↗</a>` : "—";
        return `<tr>
          <td class="srno">${i+1}</td>
          <td>${esc(j.username||"—")}</td>
          <td><span class="jid">${esc((j.job_id||"").slice(0,16))}…</span></td>
          <td><span class="fn">${esc(j.original_filename||"—")}</span></td>
          <td><span class="fn" style="color:var(--muted)">${esc(j.output_filename||"—")}</span></td>
          <td>${uploadStatus}</td>
          <td>${serverStatus}</td>
          <td>${link}</td>
        </tr>`;
      });
      const header=`<tr><th>#</th><th>User</th><th>Job ID</th><th>Uploaded File</th><th>Output File</th><th>Upload Status</th><th>Server Status</th><th>Link</th></tr>`;
      renderPaginatedTable("cloudAllJobsWrap", rows, header, "cloudalljobs", {defaultSize:10, emptyMsg:"No jobs yet.", noSort:[7]});
    }catch{ $("#cloudAllJobsWrap").innerHTML=`<div class="empty">Could not load.</div>`; }
  }

  // Tab navigation calls this (window.loadCloudPanel) jyare "Cloud Management" tab khole tyare
  window.loadCloudPanel = function(){
    errEl.style.display="none"; okEl.style.display="none";
    loadCloudStatus(); loadCloudPending(); loadCloudAllJobs();
  };
  // Expose for sub-tab controller (lazy-load on sub-tab switch)
  window.loadCloudAllJobs = loadCloudAllJobs;
  window.loadCloudPending = loadCloudPending;

  saveBtn.onclick=async()=>{
    errEl.style.display="none"; okEl.style.display="none";
    const provider = providerSel.value;
    const payload = {provider};
    if(provider==="google_drive"){
      payload.root_folder_id = $("#gdRootFolderId").value.trim();
      payload.client_email   = $("#gdClientEmail").value.trim();
      payload.project_id     = $("#gdProjectId").value.trim();
      const pk = $("#gdPrivateKey").value.trim();
      if(pk) payload.private_key = pk;
    } else if(provider==="onedrive"){
      payload.tenant_id = $("#odTenantId").value.trim();
      payload.client_id = $("#odClientId").value.trim();
      payload.drive_id = $("#odDriveId").value.trim();
      payload.root_path = $("#odRootPath").value.trim() || "/SMVS-OCR";
      const secret = $("#odClientSecret").value.trim();
      if(secret) payload.client_secret = secret;
    }
    saveBtn.disabled=true; saveBtn.textContent="Saving…";
    try{
      const r = await fetch("/api/admin/storage/config",{method:"POST",
        headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
      const d = await r.json();
      if(r.ok&&d.ok){ okEl.textContent="Saved & connected successfully!"; okEl.style.display="block"; loadCloudStatus(); }
      else { errEl.textContent=d.error||"Could not save settings."; errEl.style.display="block"; }
    }catch{ errEl.textContent="Network error."; errEl.style.display="block"; }
    saveBtn.disabled=false; saveBtn.textContent="Save & Connect";
  };

  testBtn.onclick=async()=>{
    errEl.style.display="none"; okEl.style.display="none";
    testBtn.disabled=true; testBtn.textContent="Testing…";
    try{
      const r = await fetch("/api/admin/storage/test",{method:"POST"});
      const d = await r.json();
      if(r.ok&&d.ok){ okEl.textContent=`Connection OK (${d.provider}). Test folder created.`; okEl.style.display="block"; }
      else { errEl.textContent=d.error||"Connection test failed."; errEl.style.display="block"; }
    }catch{ errEl.textContent="Network error."; errEl.style.display="block"; }
    testBtn.disabled=false; testBtn.textContent="Test Connection";
  };
})();

// ===================== Feedback Tab =====================
let _fbFilter = "";
async function loadFeedback(){
  const wrap=$("#feedbackWrap");
  if(!wrap) return;
  try{
    const url = _fbFilter ? `/api/admin/feedback?type=${encodeURIComponent(_fbFilter)}` : "/api/admin/feedback";
    const d=await (await fetch(url)).json();
    const list=d.feedback||[];
    const types=d.types||[];
    // Filter dropdown
    let filterHtml=`<div style="margin-bottom:14px;display:flex;align-items:center;gap:10px">
      <span style="font-size:13px;font-weight:600;color:#666">Filter by type:</span>
      <select id="fbFilterSel" style="padding:8px 30px 8px 11px;border:1px solid var(--line);border-radius:9px;font:inherit;font-size:13px">
        <option value="">All Types</option>
        ${types.map(t=>`<option value="${esc(t)}" ${t===_fbFilter?'selected':''}>${esc(t)}</option>`).join("")}
      </select></div>`;
    if(!list.length){ wrap.innerHTML=filterHtml+'<div class="empty">No feedback yet.</div>';
      const fs=$("#fbFilterSel"); if(fs) fs.onchange=()=>{_fbFilter=fs.value;loadFeedback();};
      return; }
    const rowsArr=list.map(f=>{
      const typePill=`<span class="status-pill status-queued">${esc(f.type)}</span>`;
      const statusPill=f.status==='new'?`<span class="status-pill status-error">New</span>`:
        `<span class="status-pill" style="background:#eee;color:#888">Read</span>`;
      const stars=f.rating?'★'.repeat(f.rating)+'☆'.repeat(5-f.rating):'—';
      const userCol = f.username ? esc(f.username) : '<span class="muted">guest</span>';
      const actionBtn = f.action_done
        ? `<button class="mini-reset" style="background:#e3f6ea;color:#1e8449;border-color:#1e8449" data-fb-action="${f.id}">✓ Completed</button>`
        : `<button class="mini-reset" data-fb-action="${f.id}">Mark Done</button>`;
      return `<tr>
        <td>${esc(f.name)}<br><span class="muted" style="font-size:11px">${esc(f.email||'—')}</span></td>
        <td>${userCol}</td>
        <td>${typePill}</td>
        <td style="max-width:220px">${esc(f.message.slice(0,80))}${f.message.length>80?'…':''}</td>
        <td style="color:#e8a020;white-space:nowrap">${stars}</td>
        <td>${statusPill}</td>
        ${dateCell(f.created_at,"muted")}
        <td style="white-space:nowrap"><button class="mini-reset" data-fb-view="${f.id}">View</button>${actionBtn}</td>
      </tr>`;
    });
    // filter above, paginated table below in its own container
    wrap.innerHTML=filterHtml+`<div id="fbTableWrap"></div>`;
    const fs=$("#fbFilterSel"); if(fs) fs.onchange=()=>{_fbFilter=fs.value;_pgState["feedback"]={page:1,size:(_pgState["feedback"]?_pgState["feedback"].size:10)};loadFeedback();};
    const header=`<tr><th>From</th><th>User</th><th>Type</th><th>Message</th><th>Rating</th><th>Status</th><th>Date</th><th>Action</th></tr>`;
    const bindFb=(el)=>{
      el.querySelectorAll("[data-fb-view]").forEach(btn=>{
        btn.onclick=()=>{
          const fb=list.find(f=>f.id==btn.dataset.fbView); if(!fb) return;
          const stars=fb.rating?'★'.repeat(fb.rating)+'☆'.repeat(5-fb.rating):'—';
          $("#fbViewBody").innerHTML=`
            <div style="background:#faf7f1;border-radius:10px;padding:14px 16px;margin-bottom:14px">
              <div style="display:grid;grid-template-columns:90px 1fr;gap:8px 12px;font-size:13px">
                <span style="color:#888">From</span><b>${esc(fb.name)}</b>
                <span style="color:#888">Email</span><span>${esc(fb.email||'—')}</span>
                <span style="color:#888">User</span><span>${fb.username?esc(fb.username):'guest'}</span>
                <span style="color:#888">Type</span><span><span class="status-pill status-queued">${esc(fb.type)}</span></span>
                <span style="color:#888">Rating</span><span style="color:#e8a020">${stars}</span>
                <span style="color:#888">Date</span><span>${fmtDate(new Date(fb.created_at*1000).toISOString())}</span>
              </div>
            </div>
            <div style="font-size:12px;color:#888;margin-bottom:6px">MESSAGE</div>
            <div style="background:#fff;border-left:3px solid var(--saffron);border-radius:8px;padding:12px 14px;
              font-size:14px;color:#333;line-height:1.5">${esc(fb.message)}</div>`;
          $("#fbViewModal").classList.add("open");
          if(fb.status==='new') fetch("/api/admin/feedback/read",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:fb.id})}).then(()=>loadFeedback());
        };
      });
      el.querySelectorAll("[data-fb-action]").forEach(btn=>{
        btn.onclick=async()=>{
          await fetch("/api/admin/feedback/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:parseInt(btn.dataset.fbAction)})});
          loadFeedback();
        };
      });
    };
    renderPaginatedTable("fbTableWrap", rowsArr, header, "feedback", {defaultSize:10, emptyMsg:"No feedback yet.", onBind:bindFb, noSort:[7]});
  }catch{ wrap.innerHTML='<div class="empty">Could not load feedback.</div>'; }
}
// Feedback view modal close
document.addEventListener("click",(e)=>{
  if(e.target.id==="fbViewCloseBtn"||e.target.id==="fbViewModal") $("#fbViewModal").classList.remove("open");
});

// ===================== Pagination Helper =====================
function paginationBar(total, page, size, key){
  const pages=Math.max(1,Math.ceil(total/size));
  const from=total===0?0:(page-1)*size+1;
  const to=Math.min(page*size,total);
  return `<div class="pgbar" data-pg="${key}">
    <span class="pg-info">${from}–${to} of ${total}</span>
    <span class="pg-size">Per page:
      <select data-pgsize>
        <option value="10" ${size===10?'selected':''}>10</option>
        <option value="25" ${size===25?'selected':''}>25</option>
        <option value="50" ${size===50?'selected':''}>50</option>
        <option value="100" ${size===100?'selected':''}>100</option>
      </select></span>
    <span class="pg-nav">
      <button data-pgprev ${page<=1?'disabled':''}>‹ Prev</button>
      <span class="pg-page">${page} / ${pages}</span>
      <button data-pgnext ${page>=pages?'disabled':''}>Next ›</button>
    </span></div>`;
}
function bindPagination(key, cb){
  const bar=document.querySelector(`.pgbar[data-pg="${key}"]`);
  if(!bar) return;
  const sizeSel=bar.querySelector("[data-pgsize]");
  const prev=bar.querySelector("[data-pgprev]");
  const next=bar.querySelector("[data-pgnext]");
  const curPage=parseInt(bar.querySelector(".pg-page").textContent);
  sizeSel.onchange=()=>cb(1,parseInt(sizeSel.value));
  if(prev) prev.onclick=()=>cb(curPage-1,parseInt(sizeSel.value));
  if(next) next.onclick=()=>cb(curPage+1,parseInt(sizeSel.value));
}

// Generic client-side paginated table.
// state = {page, size}; rowsHtmlArr = array of <tr>...</tr> strings; headerHtml = <tr><th>...</th></tr>
// onBind(container) optional — re-attach row event handlers after each render.
const _pgState = {};
function _cellText(rowHtml, colIdx){
  // Extract text of the Nth <td> from a row HTML string (for sorting)
  const tmp=document.createElement("tr");
  tmp.innerHTML=rowHtml.replace(/^<tr[^>]*>/,"").replace(/<\/tr>\s*$/,"");
  const tds=tmp.querySelectorAll("td");
  if(colIdx>=tds.length) return "";
  return (tds[colIdx].textContent||"").trim().toLowerCase();
}
function renderPaginatedTable(containerId, rowsHtmlArr, headerHtml, key, opts){
  opts = opts || {};
  const defSize = opts.defaultSize || 10;
  const tableClass = opts.tableClass || "";
  if(!_pgState[key]) _pgState[key] = {page:1, size:defSize, sortCol:null, sortDir:1, search:"", colIdx:"", colVal:""};
  const st = _pgState[key];
  if(st.search===undefined) st.search="";
  if(st.colIdx===undefined) st.colIdx="";
  if(st.colVal===undefined) st.colVal="";
  const el = document.getElementById(containerId);
  if(!el) return;

  // Column names from header (for the filter dropdown)
  const tmpHdr=document.createElement("thead"); tmpHdr.innerHTML=headerHtml;
  const colNames=[...tmpHdr.querySelectorAll("th")].map(th=>(th.textContent||"").trim());
  const noSortSet = opts.noSort || [];

  // Apply global search (all cells)
  let rows = rowsHtmlArr.slice();
  if(st.search){
    const q=st.search.toLowerCase();
    rows = rows.filter(r=>{
      const tmp=document.createElement("tr");
      tmp.innerHTML=r.replace(/^<tr[^>]*>/,"").replace(/<\/tr>\s*$/,"");
      return (tmp.textContent||"").toLowerCase().includes(q);
    });
  }
  // Apply column filter — multi-select (colVals), single value (colVal), or date
  if(st.colIdx!==""){
    const ci=parseInt(st.colIdx);
    if(st.colVals && st.colVals.length){
      // Multi-select: match any selected value (exact, case-insensitive)
      const set=new Set(st.colVals.map(v=>v.toLowerCase()));
      rows = rows.filter(r=> set.has(_cellText(r,ci)));
    } else if(st.colVal){
      const isDateVal = /^\d{4}-\d{2}-\d{2}$/.test(st.colVal);
      if(isDateVal){
        rows = rows.filter(r=>{
          const dd=_cellDate(r,ci);
          if(dd) return dd===st.colVal;
          const d=new Date(_cellText(r,ci));
          if(isNaN(d.getTime())) return false;
          const iso=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
          return iso===st.colVal;
        });
      } else {
        const q=st.colVal.toLowerCase();
        rows = rows.filter(r=> _cellText(r,ci).includes(q));
      }
    }
  }

  // Apply sort if a column is selected
  if(st.sortCol!=null){
    rows.sort((a,b)=>{
      // Date columns → chronological sort via data-date
      const ad=_cellDate(a,st.sortCol), bd=_cellDate(b,st.sortCol);
      if(ad!==null || bd!==null){
        return ((ad||"").localeCompare(bd||""))*st.sortDir;
      }
      const av=_cellText(a,st.sortCol), bv=_cellText(b,st.sortCol);
      const an=parseFloat(av.replace(/[^0-9.\-]/g,"")), bn=parseFloat(bv.replace(/[^0-9.\-]/g,""));
      const bothNum = !isNaN(an) && !isNaN(bn) && av.match(/[0-9]/) && bv.match(/[0-9]/);
      if(bothNum) return (an-bn)*st.sortDir;
      return av.localeCompare(bv)*st.sortDir;
    });
  }

  if(rowsHtmlArr.length===0){ el.innerHTML = `<div class="empty">${opts.emptyMsg||"No records."}</div>`; return; }

  const total = rows.length;
  const pages = Math.max(1, Math.ceil(total/st.size));
  if(st.page>pages) st.page=pages;
  if(st.page<1) st.page=1;
  const startIdx = (st.page-1)*st.size;
  const pageRows = rows.slice(startIdx, startIdx+st.size).join("");

  // Controls bar: global search + column filter (skip if noFilter)
  let controls="";
  if(!opts.noFilter){
    // Column selector — searchable single-select dropdown (saffron UI)
    const selColName = st.colIdx==="" ? "— Column —" : (colNames[parseInt(st.colIdx)]||"— Column —");
    const colItems = colNames.map((n,i)=> noSortSet.includes(i) ? "" :
      `<label class="ms-item ms-item-single" data-colpick="${i}">
         <span>${esc(n)}</span>${String(st.colIdx)===String(i)?'<span class="ms-check">✓</span>':''}
       </label>`).join("");
    const colDropdown=`<div class="ms-wrap" data-coldd>
      <button type="button" class="ms-toggle ms-col-toggle" data-coltoggle>
        <span class="ms-label ${st.colIdx===""?"ms-placeholder":""}">${esc(selColName)}</span><span class="ms-caret">▾</span>
      </button>
      <div class="ms-panel" hidden>
        <div class="ms-search-wrap"><input type="text" class="ms-search" placeholder="🔍 Search column…" data-colsearch></div>
        <div class="ms-list" data-collist>
          <label class="ms-item ms-item-single" data-colpick=""><span>— Column —</span>${st.colIdx===""?'<span class="ms-check">✓</span>':''}</label>
          ${colItems}
        </div>
      </div>
    </div>`;
    // Value control: date column → date picker; fixed-value → multi-select; else text box
    let valControl;
    if(st.colIdx===""){
      valControl=`<input type="text" data-tblcolval placeholder="value…" class="tbl-colval" disabled />`;
    } else {
      const ci=parseInt(st.colIdx);
      const cellVals=rowsHtmlArr.map(r=>_cellText(r,ci)).filter(v=>v!=="");
      const distinct=[...new Set(cellVals)];
      // Date column detection: any row has data-date attribute for this column, OR most cells parse as dates
      const hasDataDate = rowsHtmlArr.some(r=>_cellDate(r,ci)!==null);
      const dateParsed=cellVals.filter(v=>!isNaN(Date.parse(v))).length;
      const isDate = hasDataDate || (cellVals.length>0 && dateParsed >= Math.ceil(cellVals.length*0.7));
      const isFixed = !isDate && distinct.length>0 && distinct.length<=15;
      if(isDate){
        valControl=`<input type="date" data-tblcolval data-datefilter="1" value="${esc(st.colVal||"")}" class="tbl-colval" style="width:auto" />`;
      } else if(isFixed){
        distinct.sort();
        const sel = st.colVals || [];
        let labelHtml;
        if(sel.length===0){
          labelHtml=`<span class="ms-placeholder">— All —</span>`;
        } else {
          const shown = sel.slice(0,4).map(v=>`<span class="ms-tag">${esc(v)}</span>`).join("");
          const more = sel.length>4 ? `<span class="ms-tag ms-more">+${sel.length-4} more</span>` : "";
          labelHtml = shown + more;
        }
        const items = distinct.map(v=>{
          const checked = sel.includes(v) ? "checked" : "";
          return `<label class="ms-item"><input type="checkbox" value="${esc(v)}" ${checked}><span>${esc(v)}</span></label>`;
        }).join("");
        valControl=`<div class="ms-wrap" data-msdd>
          <button type="button" class="ms-toggle ms-toggle-tags" data-mstoggle>
            <span class="ms-label">${labelHtml}</span><span class="ms-caret">▾</span>
          </button>
          <div class="ms-panel" hidden>
            <div class="ms-search-wrap"><input type="text" class="ms-search" placeholder="🔍 Search…" data-mssearch></div>
            <div class="ms-list" data-mslist>${items}</div>
          </div>
        </div>`;
      } else {
        valControl=`<input type="text" data-tblcolval placeholder="value…" value="${esc(st.colVal||"")}" class="tbl-colval" />`;
      }
    }
    controls=`<div class="tbl-controls">
      <input type="text" data-tblsearch placeholder="🔍 Search all…" value="${esc(st.search||"")}" class="tbl-search" />
      <span class="tbl-filter-group">
        <span class="muted" style="font-size:12px">Filter:</span>
        ${colDropdown}
        ${valControl}
        ${(st.search||st.colVal||(st.colVals&&st.colVals.length))?`<button data-tblclear class="tbl-clear">✕ Clear Filter</button>`:""}
      </span>
    </div>`;
  }

  // Sortable headers
  const tmpH=document.createElement("thead"); tmpH.innerHTML=headerHtml;
  tmpH.querySelectorAll("th").forEach((th,i)=>{
    if(noSortSet.includes(i)) return;
    th.style.cursor="pointer"; th.style.userSelect="none";
    const arrow = st.sortCol===i ? (st.sortDir===1?" ▲":" ▼") : " ⇅";
    th.innerHTML=th.innerHTML+`<span style="opacity:.4;font-size:10px">${arrow}</span>`;
    th.setAttribute("data-sortcol", i);
  });
  const headerFinal=tmpH.innerHTML;

  const tableBody = total===0
    ? `<div class="empty">No rows match your search/filter.</div>`
    : `<div style="overflow-x:auto"><table class="${tableClass}"><thead>${headerFinal}</thead><tbody>${pageRows}</tbody></table></div>`
      + paginationBar(total, st.page, st.size, key);

  el.innerHTML = controls + tableBody;

  // Handlers
  const rerender=()=>renderPaginatedTable(containerId, rowsHtmlArr, headerHtml, key, opts);
  const searchEl=el.querySelector("[data-tblsearch]");
  if(searchEl){
    searchEl.oninput=()=>{ st.search=searchEl.value; st.page=1; rerender();
      const nf=document.getElementById(containerId).querySelector("[data-tblsearch]");
      if(nf){ nf.focus(); nf.setSelectionRange(nf.value.length,nf.value.length); } };
  }
  // Column dropdown (searchable single-select)
  const colWrap=el.querySelector("[data-coldd]");
  if(colWrap){
    const cToggle=colWrap.querySelector("[data-coltoggle]");
    const cPanel=colWrap.querySelector(".ms-panel");
    const cSearch=colWrap.querySelector("[data-colsearch]");
    const cList=colWrap.querySelector("[data-collist]");
    if(st._colOpen){ cPanel.hidden=false; }
    cToggle.onclick=(e)=>{ e.stopPropagation(); cPanel.hidden=!cPanel.hidden; st._colOpen=!cPanel.hidden;
      if(!cPanel.hidden && cSearch){ cSearch.focus(); } };
    cPanel.onclick=(e)=>e.stopPropagation();
    if(cSearch){
      cSearch.oninput=()=>{
        const q=cSearch.value.toLowerCase();
        cList.querySelectorAll(".ms-item").forEach(it=>{
          it.style.display=(it.textContent||"").toLowerCase().includes(q)?"":"none";
        });
      };
    }
    cList.querySelectorAll("[data-colpick]").forEach(it=>{
      it.onclick=()=>{ st.colIdx=it.getAttribute("data-colpick"); st.colVal=""; st.colVals=[];
        st._colOpen=false; st.page=1; rerender(); };
    });
  }
  const colValEl=el.querySelector("[data-tblcolval]");
  if(colValEl){
    if(colValEl.getAttribute("data-datefilter")==="1"){
      colValEl.onchange=()=>{ st.colVal=colValEl.value; st.page=1; rerender(); };
    } else {
      colValEl.oninput=()=>{ st.colVal=colValEl.value; st.page=1; rerender();
        const nf=document.getElementById(containerId).querySelector("[data-tblcolval]");
        if(nf && nf.type!=="date"){ nf.focus(); nf.setSelectionRange(nf.value.length,nf.value.length); } };
    }
  }
  // Multi-select dropdown wiring
  const msWrap=el.querySelector("[data-msdd]");
  if(msWrap){
    const toggle=msWrap.querySelector("[data-mstoggle]");
    const panel=msWrap.querySelector(".ms-panel");
    const searchInp=msWrap.querySelector("[data-mssearch]");
    const list=msWrap.querySelector("[data-mslist]");
    // Keep panel open if it was open before rerender
    if(st._msOpen){ panel.hidden=false; }
    toggle.onclick=(e)=>{ e.stopPropagation(); panel.hidden=!panel.hidden; st._msOpen=!panel.hidden;
      if(!panel.hidden && searchInp){ searchInp.focus(); } };
    // prevent closing when clicking inside panel
    panel.onclick=(e)=>e.stopPropagation();
    if(searchInp){
      searchInp.oninput=()=>{
        const q=searchInp.value.toLowerCase();
        list.querySelectorAll(".ms-item").forEach(it=>{
          const txt=(it.textContent||"").toLowerCase();
          it.style.display = txt.includes(q) ? "" : "none";
        });
      };
    }
    list.querySelectorAll("input[type=checkbox]").forEach(cb=>{
      cb.onchange=()=>{
        const vals=[...list.querySelectorAll("input:checked")].map(x=>x.value);
        st.colVals=vals; st.colVal=""; st.page=1; st._msOpen=true; rerender();
      };
    });
  } else {
    st._msOpen=false;
  }
  const clearBtn=el.querySelector("[data-tblclear]");
  if(clearBtn){ clearBtn.onclick=()=>{ st.search=""; st.colVal=""; st.colVals=[]; st._msOpen=false; st.page=1; rerender(); }; }
  // Sort click handlers
  el.querySelectorAll("th[data-sortcol]").forEach(th=>{
    th.onclick=()=>{
      const col=parseInt(th.getAttribute("data-sortcol"));
      if(st.sortCol===col){ st.sortDir=-st.sortDir; } else { st.sortCol=col; st.sortDir=1; }
      rerender();
    };
  });
  bindPagination(key, (p,s)=>{ st.page=p; st.size=s; renderPaginatedTable(containerId, rowsHtmlArr, headerHtml, key, opts); });
  if(opts.onBind) opts.onBind(el);
}

// ===================== Reject Modal =====================
let _rejectUsername=null;
function openRejectModal(username){
  _rejectUsername=username;
  $("#rejectModalErr").style.display="none";
  $("#rejectUserName").textContent=username;
  $("#rejectReason").value="";
  $("#rejectModal").classList.add("open");
}
(function(){
  const modal=$("#rejectModal");
  if(!modal) return;
  $("#rejectCancelBtn").onclick=()=>modal.classList.remove("open");
  modal.addEventListener("click",e=>{ if(e.target===modal) modal.classList.remove("open"); });
  $("#rejectConfirmBtn").onclick=async()=>{
    const err=$("#rejectModalErr");
    const reason=$("#rejectReason").value.trim();
    if(!reason){ err.textContent="Reason required."; err.style.display="block"; return; }
    $("#rejectConfirmBtn").disabled=true;
    try{
      const r=await fetch("/api/admin/users/reject",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({username:_rejectUsername,reason})});
      const d=await r.json();
      if(r.ok&&d.ok){
        err.style.display="block"; err.className="modal-ok";
        err.textContent="✓ User rejected & notified. Closing in 5 seconds…";
        loadUsers();
        setTimeout(()=>{
          modal.classList.remove("open");
          err.className="modal-err"; err.style.display="none";
          $("#rejectConfirmBtn").disabled=false;
        },5000);
      } else {
        err.className="modal-err"; err.textContent=d.error||"Failed."; err.style.display="block";
        $("#rejectConfirmBtn").disabled=false;
      }
    }catch{ err.className="modal-err"; err.textContent="Network error."; err.style.display="block"; $("#rejectConfirmBtn").disabled=false; }
  };
})();
// Reason view modal close
document.addEventListener("click",(e)=>{
  if(e.target.id==="reasonViewCloseBtn"||e.target.id==="reasonViewModal") $("#reasonViewModal").classList.remove("open");
});

// ===================== User Modal Handlers =====================
(function(){
  const modal=$("#userModal");
  if(!modal) return;
  $("#openCreateUserBtn") && ($("#openCreateUserBtn").onclick=()=>openUserModal(null));
  $("#umCancelBtn").onclick=()=>modal.classList.remove("open");
  modal.addEventListener("click",e=>{ if(e.target===modal) modal.classList.remove("open"); });
  // live username availability in create mode
  let ut=null;
  $("#umUser").addEventListener("input",function(){
    if(_editingUser) return;
    const hint=$("#umUserHint"); const v=this.value.trim();
    clearTimeout(ut); hint.textContent="";
    if(v.length<3) return;
    ut=setTimeout(async()=>{
      try{ const d=await(await fetch(`/api/check-username?username=${encodeURIComponent(v)}`)).json();
        hint.textContent=d.available?(d.reason+" ✓"):(d.reason+" ✗");
        hint.style.color=d.available?"#1e8449":"#e74c3c";
      }catch{}
    },400);
  });
  $("#umSaveBtn").onclick=async()=>{
    const err=$("#userModalErr"); err.style.display="none";
    const fn=$("#umFname").value.trim(), ln=$("#umLname").value.trim();
    const un=$("#umUser").value.trim(), em=$("#umEmail").value.trim();
    const role=$("#umRole").value, pass=$("#umPass").value;
    function e(t){ err.textContent=t; err.style.display="block"; }
    if(!fn) return e("First name required.");
    if(!ln) return e("Last name required.");
    if(!em||!em.includes("@")) return e("Valid email required.");
    $("#umSaveBtn").disabled=true;
    try{
      let r,d;
      if(_editingUser){
        r=await fetch("/api/admin/users/edit",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({username:_editingUser,first_name:fn,last_name:ln,email:em,role})});
      } else {
        if(un.length<5) { $("#umSaveBtn").disabled=false; return e("Username min 5 chars."); }
        if(pass.length<4){ $("#umSaveBtn").disabled=false; return e("Password min 4 chars."); }
        r=await fetch("/api/admin/users",{method:"POST",headers:{"Content-Type":"application/json"},
          body:JSON.stringify({username:un,password:pass,email:em,first_name:fn,last_name:ln,role})});
      }
      d=await r.json();
      if(r.ok&&d.ok){ toast(_editingUser?"User updated":"User created"); modal.classList.remove("open"); loadUsers(); }
      else e(d.error||"Failed.");
    }catch{ e("Network error."); }
    $("#umSaveBtn").disabled=false;
  };
})();

// ===================== Role Management =====================
let _permCatalog={}, _editingRole=null;

async function loadRoles(){
  const wrap=$("#rolesWrap");
  try{
    const d=await (await fetch("/api/admin/roles")).json();
    _permCatalog=d.catalog||{};
    const roles=d.roles||[];
    if(!roles.length){ wrap.innerHTML='<div class="empty">No custom roles yet. Click "Create Role".</div>'; return; }
    const rows=roles.map(r=>{
      const permCount=r.permissions.length;
      const isBuiltin=(r.name==='admin'||r.name==='user');
      return `<tr>
        <td><b>${esc(r.name)}</b>${isBuiltin?' <span class="muted" style="font-size:11px">(built-in)</span>':''}</td>
        <td>${permCount} permission${permCount!==1?'s':''}</td>
        <td class="muted" style="max-width:340px;font-size:12px">${r.permissions.map(esc).join(', ')||'—'}</td>
        <td style="text-align:right;white-space:nowrap">
          <button class="mini-reset" data-edit-role="${esc(r.name)}">✏️ Edit</button>
          ${isBuiltin?'':`<button class="mini-danger" data-del-role="${esc(r.name)}">Delete</button>`}
        </td></tr>`;
    }).join("");
    wrap.innerHTML=`<div style="overflow-x:auto"><table><thead><tr><th>Role</th><th>Access</th><th>Permissions</th><th style="text-align:right">Actions</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    wrap.querySelectorAll("[data-edit-role]").forEach(b=>b.onclick=()=>openRoleModal(b.dataset.editRole,roles));
    wrap.querySelectorAll("[data-del-role]").forEach(b=>b.onclick=async()=>{
      if(!confirm(`Delete role "${b.dataset.delRole}"? Users with this role become 'user'.`)) return;
      const r=await fetch("/api/admin/roles/delete",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:b.dataset.delRole})});
      const d=await r.json();
      if(r.ok&&d.ok){ toast("Role deleted"); loadRoles(); } else toast(d.error||"Failed","err");
    });
  }catch{ wrap.innerHTML='<div class="empty">Could not load roles.</div>'; }
}

function renderPermCheckboxes(selected){
  selected=selected||[];
  let h="";
  for(const [group,items] of Object.entries(_permCatalog)){
    h+=`<div style="margin-bottom:14px"><div style="font-size:11.5px;font-weight:700;color:#5b4326;margin-bottom:6px;text-transform:uppercase">${esc(group)}</div>`;
    items.forEach(it=>{
      const chk=selected.includes(it.key)?"checked":"";
      h+=`<label style="display:flex;align-items:center;gap:8px;padding:6px 10px;border-radius:8px;cursor:pointer;font-size:13px" class="perm-row">
        <input type="checkbox" value="${esc(it.key)}" ${chk} style="width:16px;height:16px;accent-color:var(--saffron)"> ${esc(it.label)}</label>`;
    });
    h+=`</div>`;
  }
  return h;
}

function openRoleModal(name, roles){
  _editingRole=name||null;
  $("#roleModalErr").style.display="none";
  $("#roleModalTitle").textContent=name?"✏️ Edit Role":"🛡️ Create Role";
  $("#rmName").value=name||""; $("#rmName").disabled=!!name;
  const selected=name&&roles?(roles.find(r=>r.name===name)||{}).permissions||[]:[];
  $("#rmPermsWrap").innerHTML=renderPermCheckboxes(selected);
  $("#roleModal").classList.add("open");
}

(function(){
  const modal=$("#roleModal");
  if(!modal) return;
  $("#openCreateRoleBtn") && ($("#openCreateRoleBtn").onclick=()=>{
    // ensure catalog loaded
    if(Object.keys(_permCatalog).length) openRoleModal(null,null);
    else fetch("/api/admin/roles").then(r=>r.json()).then(d=>{_permCatalog=d.catalog||{};openRoleModal(null,null);});
  });
  $("#rmCancelBtn").onclick=()=>modal.classList.remove("open");
  modal.addEventListener("click",e=>{ if(e.target===modal) modal.classList.remove("open"); });
  $("#rmSaveBtn").onclick=async()=>{
    const err=$("#roleModalErr"); err.style.display="none";
    const name=$("#rmName").value.trim().toLowerCase();
    if(!name){ err.textContent="Role name required."; err.style.display="block"; return; }
    const perms=[...modal.querySelectorAll("#rmPermsWrap input:checked")].map(c=>c.value);
    $("#rmSaveBtn").disabled=true;
    try{
      const r=await fetch("/api/admin/roles",{method:"POST",headers:{"Content-Type":"application/json"},
        body:JSON.stringify({name,permissions:perms})});
      const d=await r.json();
      if(r.ok&&d.ok){ toast("Role saved"); modal.classList.remove("open"); loadRoles(); }
      else { err.textContent=d.error||"Failed."; err.style.display="block"; }
    }catch{ err.textContent="Network error."; err.style.display="block"; }
    $("#rmSaveBtn").disabled=false;
  };
})();

// ===================== Sub-Tab Navigation (generic) =====================
(function(){
  document.querySelectorAll(".subtab-nav").forEach(nav=>{
    const group=nav.dataset.subnav;
    const btns=[...nav.querySelectorAll("button")];
    const panels=[...document.querySelectorAll(`.subtab-panel[data-subpanel]`)]
      .filter(p=>{ // only panels that belong to this nav's parent card
        return nav.parentElement.contains(p);
      });
    btns.forEach(b=>b.onclick=()=>{
      const st=b.dataset.subtab;
      btns.forEach(x=>x.classList.toggle("active",x===b));
      panels.forEach(p=>{ p.hidden = p.dataset.subpanel!==st; });
      // Lazy-load cloud sub-tab data
      if(group==="cloud"){
        if(st==="alljobs" && typeof window.loadCloudAllJobs==="function") window.loadCloudAllJobs();
        if(st==="pending" && typeof window.loadCloudPending==="function") window.loadCloudPending();
      }
    });
  });
})();

// ===================== Tab Navigation =====================
(function(){
  const nav = $("#adminTabNav");
  if(!nav) return;
  const buttons = [...nav.querySelectorAll("button")];
  const panels = [...document.querySelectorAll(".tab-panel")];
  const loaded = new Set();   // lazy-load each tab's data only once on first visit

  function activate(tab){
    buttons.forEach(b=>b.classList.toggle("active", b.dataset.tab===tab));
    panels.forEach(p=>{ p.hidden = p.dataset.panel!==tab; });
    if(!loaded.has(tab)){
      loaded.add(tab);
      if(tab==="dashboard" && typeof refreshDashboard==="function") refreshDashboard(_dashRange);
      if(tab==="users" && typeof loadUsers==="function") loadUsers();
      if(tab==="roles" && typeof loadRoles==="function") loadRoles();
      if(tab==="fonts" && typeof loadFonts==="function") loadFonts();
      if(tab==="jobs" && typeof loadJobs==="function") loadJobs();
      if(tab==="cloud" && typeof window.loadCloudPanel==="function") window.loadCloudPanel();
      if(tab==="feedback" && typeof loadFeedback==="function") loadFeedback();
      if(tab==="email"    && typeof loadEmailSettings==="function") loadEmailSettings();
    } else if(tab==="cloud" && typeof window.loadCloudPanel==="function"){
      window.loadCloudPanel();
    } else if(tab==="feedback" && typeof loadFeedback==="function"){
      loadFeedback();
    } else if(tab==="email" && typeof loadEmailSettings==="function"){
      loadEmailSettings();
    }
  }

  buttons.forEach(b=> b.onclick = () => activate(b.dataset.tab));

  // Permission-based tab visibility — fetch /api/me, hide tabs user can't access.
  // Roles tab only for superadmin.
  fetch("/api/me").then(r=>r.json()).then(me=>{
    const isSuper = me.role === "superadmin";
    const allowed = me.allowed_tabs || [];
    let firstVisible = null;
    buttons.forEach(b=>{
      const tab=b.dataset.tab;
      const permKey="admin."+tab;
      let show = isSuper || allowed.includes(permKey);
      if(tab==="roles" && !isSuper) show=false;   // role mgmt superadmin-only
      b.style.display = show ? "" : "none";
      if(show && !firstVisible) firstVisible=tab;
    });
    // activate dashboard if allowed, else first visible tab
    const startTab = (isSuper || allowed.includes("admin.dashboard")) ? "dashboard" : (firstVisible||"dashboard");
    activate(startTab);
  }).catch(()=>activate("dashboard"));
})();

// ===================== Email Settings Tab =====================
async function loadEmailSettings(){
  try{
    const d=await (await fetch("/api/admin/email-status")).json();
    const dot=d.enabled?"dot on":"dot";
    const label=d.enabled
      ? `<b>Configured</b> — Sending as <b>${esc(d.from_address)}</b>`
      : "Not configured — signup / feedback emails will not be sent";
    $("#emailStatusBox").innerHTML=`<span class="${dot}"></span><span>${label}</span>`;
    if(d.from_address) $("#emFromAddress").value=d.from_address;
    if(d.from_name)    $("#emFromName").value=d.from_name;
    if(d.admin_email)  $("#emAdminEmail").value=d.admin_email;
    $("#emAppPassword").placeholder=d.app_password_configured
      ? "•••• already set — leave blank to keep"
      : "xxxx xxxx xxxx xxxx";
  }catch{ $("#emailStatusBox").innerHTML=`<span class="dot"></span><span>Could not load.</span>`; }
}

(function(){
  const saveBtn=$("#emailSaveBtn"), testBtn=$("#emailTestBtn"),
        errEl=$("#emailConfigErr"), okEl=$("#emailConfigOk"),
        eyeBtn=$("#emEyeBtn");
  if(!saveBtn) return;

  // Eye toggle for app password
  let pwVisible=false;
  if(eyeBtn) eyeBtn.onclick=()=>{
    pwVisible=!pwVisible;
    $("#emAppPassword").type=pwVisible?"text":"password";
    eyeBtn.textContent=pwVisible?"🙈":"👁";
  };

  saveBtn.onclick=async()=>{
    errEl.style.display="none"; okEl.style.display="none";
    saveBtn.disabled=true; saveBtn.textContent="Saving…";
    try{
      const r=await fetch("/api/admin/email-config",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          from_address:$("#emFromAddress").value.trim(),
          app_password:$("#emAppPassword").value.trim(),
          from_name:$("#emFromName").value.trim()||"SMVS OCR System",
          admin_email:$("#emAdminEmail").value.trim()
        })});
      const d=await r.json();
      if(r.ok&&d.ok){
        okEl.textContent="Email settings saved successfully!";
        okEl.style.display="block";
        $("#emAppPassword").value="";
        loadEmailSettings();
      } else {
        errEl.textContent=d.error||"Could not save.";
        errEl.style.display="block";
      }
    }catch{ errEl.textContent="Network error."; errEl.style.display="block"; }
    saveBtn.disabled=false; saveBtn.textContent="Save Settings";
  };

  testBtn.onclick=async()=>{
    errEl.style.display="none"; okEl.style.display="none";
    testBtn.disabled=true; testBtn.textContent="Sending…";
    try{
      const r=await fetch("/api/admin/email-test",{method:"POST"});
      const d=await r.json();
      if(r.ok&&d.ok){
        okEl.textContent=`✅ Test email sent to ${d.sent_to} — inbox check karo!`;
        okEl.style.display="block";
      } else {
        errEl.textContent=d.error||"Test failed.";
        errEl.style.display="block";
      }
    }catch{ errEl.textContent="Network error."; errEl.style.display="block"; }
    testBtn.disabled=false; testBtn.textContent="📨 Send Test Email";
  };
})();

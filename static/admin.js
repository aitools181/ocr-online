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

// Version badge
fetch("/api/version").then(r=>r.json()).then(d=>{
  const el=$("#versionBadge"); if(el) el.textContent=`v${d.version} · ${d.date}`;
}).catch(()=>{});


// ---------- Users ----------
async function loadUsers(){
  const wrap=$("#usersWrap");
  let d; try{ d=await (await fetch("/api/admin/users")).json(); }catch{ wrap.innerHTML='<div class="empty">Failed to load.</div>'; return; }
  const us=d.users||[];
  let h='<table><thead><tr><th>Username</th><th>First Name</th><th>Last Name</th><th>Email</th><th>Role</th><th>Status</th><th style="text-align:right">Actions</th></tr></thead><tbody>';
  us.forEach(u=>{
    const role=`<span class="pill-role ${u.role==='admin'?'pill-admin':''}">${esc(u.role)}</span>`;
    const statusPill = u.status==='pending'
      ? `<span class="status-pill status-queued">⏳ Pending</span>`
      : `<span class="status-pill status-completed">✓ Active</span>`;
    let act;
    if(u.builtin){
      act='<span class="muted">built-in</span>';
    } else if(u.status==='pending'){
      act=`<button class="add-btn" style="padding:5px 10px;font-size:12px" data-approve-user="${esc(u.username)}">✅ Approve</button>`+
          `<button class="mini-danger" data-reject-user="${esc(u.username)}">✗ Reject</button>`;
    } else {
      act=`<button class="mini-reset" data-reset-user="${esc(u.username)}" title="Password Reset">🔑 Reset</button>`+
          `<button class="mini-danger" data-del-user="${esc(u.username)}">Delete</button>`;
    }
    h+=`<tr><td><b>${esc(u.username)}</b></td><td>${esc(u.first_name||'—')}</td><td>${esc(u.last_name||'—')}</td><td class="muted">${esc(u.email||'—')}</td><td>${role}</td><td>${statusPill}</td><td style="text-align:right">${act}</td></tr>`;
  });
  h+='</tbody></table>';
  wrap.innerHTML=h;
  wrap.querySelectorAll("[data-del-user]").forEach(b=>b.onclick=()=>deleteUser(b.getAttribute("data-del-user")));
  wrap.querySelectorAll("[data-reset-user]").forEach(b=>b.onclick=()=>openResetModal(b.getAttribute("data-reset-user")));
  wrap.querySelectorAll("[data-approve-user]").forEach(b=>b.onclick=async()=>{
    b.disabled=true; b.textContent="…";
    const r=await fetch("/api/admin/users/approve",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:b.dataset.approveUser})});
    const dd=await r.json();
    if(r.ok&&dd.ok){ toast("User approved & notified via email"); loadUsers(); }
    else { toast(dd.error||"Failed","err"); b.disabled=false; b.textContent="✅ Approve"; }
  });
  wrap.querySelectorAll("[data-reject-user]").forEach(b=>b.onclick=async()=>{
    if(!confirm(`Reject and delete signup request for "${b.dataset.rejectUser}"?`)) return;
    await fetch("/api/admin/users/reject",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({username:b.dataset.rejectUser})});
    toast("Request rejected"); loadUsers();
  });
}
async function addUser(){
  const username=$("#nuUser").value.trim(), password=$("#nuPass").value;
  const email=$("#nuEmail").value.trim(), fname=$("#nuFname").value.trim(), lname=$("#nuLname").value.trim();
  if(!username||!password){ toast("Enter username and password","err"); return; }
  try{
    const r=await fetch("/api/admin/users",{method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username,password,email,first_name:fname,last_name:lname})});
    const d=await r.json();
    if(!r.ok||d.error){ toast(d.error||"Failed","err"); return; }
    $("#nuUser").value=""; $("#nuPass").value=""; $("#nuEmail").value=""; $("#nuFname").value=""; $("#nuLname").value="";
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
  el.textContent = "v2.3  ·  30 Jun 2026";
})();

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

async function loadDashUserwise(){
  try{
    const d = await (await fetch("/api/admin/dashboard/userwise")).json();
    const rows = (d.users||[]).map((u,i)=>
      `<tr><td class="srno">${i+1}</td><td><b>${esc(u.username)}</b></td>
       <td class="muted">${esc(u.ip||"—")}</td><td class="muted">${esc(u.location||"—")}</td>
       <td>${u.total}</td><td>${u.pages_done||0}</td>
       <td>${u.failed>0?`<span class="status-pill status-error">${u.failed}</span>`:u.failed}</td>
       <td>${u.pages_failed>0?`<span class="status-pill status-error">${u.pages_failed}</span>`:(u.pages_failed||0)}</td></tr>`).join("");
    $("#dashUserwise").innerHTML = d.users && d.users.length
      ? `<div style="overflow-x:auto"><table class="tbl-center"><thead><tr><th>Sr No.</th><th>User</th><th>IP</th><th>Location</th><th>Total Job Upload</th><th>Total Pages Converted</th><th>Total Job Failed</th><th>Total Pages Failed</th></tr></thead><tbody>${rows}</tbody></table></div>`
      : `<div class="empty">No job data yet.</div>`;
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

async function loadDashLogins(){
  try{
    const d = await (await fetch("/api/admin/dashboard/logins?limit=50")).json();
    const rows = (d.logins||[]).map(l=>
      `<tr><td>${esc(l.username||"—")}</td><td>${esc(l.ip||"—")}</td>
       <td class="muted" style="max-width:200px">${esc((l.device||"").slice(0,60))}</td>
       <td>${esc(l.location||"—")}</td>
       <td>${l.success?'<span class="status-pill status-completed">success</span>':'<span class="status-pill status-error">failed</span>'}</td>
       <td class="muted">${fmtDate(new Date(l.timestamp*1000).toISOString())}</td></tr>`).join("");
    $("#dashLogins").innerHTML = d.logins && d.logins.length
      ? `<table><thead><tr><th>User</th><th>IP</th><th>Device</th><th>Location</th><th>Status</th><th>Time</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty">No login history yet.</div>`;
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
    const rows = (d.jobs||[]).map(j=>
      `<tr><td><span class="jid">${esc(j.job_id)}</span><span class="fn">${esc(j.original_filename||"")}</span></td>
       <td>${esc(j.username)}</td><td>${statusPill(j.status)}</td>
       <td>${j.pages||0}</td><td>${j.duration_sec?fmtSecD(j.duration_sec):"—"}</td>
       <td class="muted">${esc(j.cloud_provider||"—")}</td>
       <td class="muted">${fmtDate(new Date(j.created_at*1000).toISOString())}</td></tr>`).join("");
    $("#dashJobs").innerHTML = d.jobs && d.jobs.length
      ? `<table><thead><tr><th>File</th><th>User</th><th>Status</th><th>Pages</th><th>Duration</th><th>Cloud</th><th>Created</th></tr></thead><tbody>${rows}</tbody></table>`
      : `<div class="empty">No matching jobs.</div>`;
  }catch{ $("#dashJobs").innerHTML = `<div class="empty">Could not load.</div>`; }
}

function refreshDashboard(range){
  loadDashSummary(range); loadDashLive(); loadDashUserwise();
  loadDashFailed(); loadDashLogins(); loadDashJobs();
}

if($("#dashCard")){
  let currentRange = "month";
  const rangeGroup = $("#dashRangeGroup");
  rangeGroup.querySelectorAll("button").forEach(btn=>{
    btn.onclick=()=>{
      rangeGroup.querySelectorAll("button").forEach(b=>b.classList.remove("active"));
      btn.classList.add("active");
      currentRange = btn.dataset.range;
      refreshDashboard(currentRange);
    };
  });
  $("#jobSearchBtn").onclick = loadDashJobs;
  $("#jobSearch").addEventListener("keydown", e=>{ if(e.key==="Enter") loadDashJobs(); });
  refreshDashboard(currentRange);
  setInterval(loadDashLive, 20000);                          // live counter refresh
  setInterval(()=>loadDashSummary(currentRange), 60000);     // periodic summary refresh
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
         <td><button class="mini-reset" data-jid="${esc(j.job_id)}">Retry</button></td></tr>`).join("");
      $("#cloudPendingWrap").innerHTML = df.jobs && df.jobs.length
        ? `<table><thead><tr><th>File</th><th>User</th><th>Attempts</th><th>Error</th><th></th></tr></thead><tbody>${failRows}</tbody></table>`
        : `<div class="empty">No pending/failed uploads. 🎉</div>`;
      $("#cloudPendingWrap").querySelectorAll("[data-jid]").forEach(btn=>{
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
      }).join("");
      $("#cloudAllJobsWrap").innerHTML = d.jobs && d.jobs.length
        ? `<div style="overflow-x:auto"><table><thead><tr>
            <th>#</th><th>User</th><th>Job ID</th><th>Uploaded File</th>
            <th>Output File</th><th>Upload Status</th><th>Server Status</th><th>Link</th>
          </tr></thead><tbody>${rows}</tbody></table></div>`
        : `<div class="empty">No jobs yet.</div>`;
    }catch{ $("#cloudAllJobsWrap").innerHTML=`<div class="empty">Could not load.</div>`; }
  }

  // Tab navigation calls this (window.loadCloudPanel) jyare "Cloud Management" tab khole tyare
  window.loadCloudPanel = function(){
    errEl.style.display="none"; okEl.style.display="none";
    loadCloudStatus(); loadCloudPending(); loadCloudAllJobs();
  };

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
    const rows=list.map(f=>{
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
        <td class="muted" style="white-space:nowrap">${fmtDate(new Date(f.created_at*1000).toISOString())}</td>
        <td style="white-space:nowrap"><button class="mini-reset" data-fb-view="${f.id}">View</button>${actionBtn}</td>
      </tr>`;
    }).join("");
    wrap.innerHTML=filterHtml+`<div style="overflow-x:auto"><table><thead><tr><th>From</th><th>User</th><th>Type</th><th>Message</th><th>Rating</th><th>Status</th><th>Date</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`;
    // Filter change
    const fs=$("#fbFilterSel"); if(fs) fs.onchange=()=>{_fbFilter=fs.value;loadFeedback();};
    // Themed view popup
    wrap.querySelectorAll("[data-fb-view]").forEach(btn=>{
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
    // Action toggle
    wrap.querySelectorAll("[data-fb-action]").forEach(btn=>{
      btn.onclick=async()=>{
        await fetch("/api/admin/feedback/action",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({id:parseInt(btn.dataset.fbAction)})});
        loadFeedback();
      };
    });
  }catch{ wrap.innerHTML='<div class="empty">Could not load feedback.</div>'; }
}
// Feedback view modal close
document.addEventListener("click",(e)=>{
  if(e.target.id==="fbViewCloseBtn"||e.target.id==="fbViewModal") $("#fbViewModal").classList.remove("open");
});

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
      if(tab==="dashboard" && typeof refreshDashboard==="function") refreshDashboard("month");
      if(tab==="users" && typeof loadUsers==="function") loadUsers();
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

  // Default: Dashboard open thay (jevu requested chhe) — last-used tab yaad nathi rakhvanu,
  // hamesha Dashboard j default rahe.
  activate("dashboard");
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

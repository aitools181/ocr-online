const $=(s)=>document.querySelector(s);
let PW="", JOBS=[];
const loginCard=$("#loginCard"), listCard=$("#listCard"), pw=$("#pw"),
      loginBtn=$("#loginBtn"), loginErr=$("#loginErr"),
      tableWrap=$("#tableWrap"), selAll=$("#selAll"), delBtn=$("#delBtn"),
      refreshBtn=$("#refreshBtn"), meta=$("#meta"), toastsEl=$("#toasts");

const esc=(s)=>String(s).replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
function toast(msg,type="ok"){ if(!toastsEl)return; const t=document.createElement("div");
  t.className="toast "+type; t.innerHTML=`<span class="ic">${type==="err"?"✕":"✓"}</span><span>${esc(msg)}</span>`;
  toastsEl.appendChild(t); requestAnimationFrame(()=>t.classList.add("show"));
  setTimeout(()=>{t.classList.remove("show");setTimeout(()=>t.remove(),300);},5000); }
function fmtSize(b){ return b<1024?b+" B":b<1048576?(b/1024).toFixed(0)+" KB":(b/1048576).toFixed(1)+" MB"; }
function fmtDate(iso){ const d=new Date(iso); return d.toLocaleString(); }

async function api(path,body){
  const r=await fetch(path,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!r.ok){ const e=await r.json().catch(()=>({detail:r.statusText})); throw new Error(e.detail||r.statusText); }
  return r.json();
}

async function login(){
  PW=pw.value;
  try{ const d=await api("/api/admin/list",{password:PW});
    loginCard.hidden=true; listCard.hidden=false; render(d);
  }catch(err){ loginErr.textContent=err.message; }
}
loginBtn.onclick=login;
pw.addEventListener("keydown",e=>{ if(e.key==="Enter") login(); });

async function refresh(){ try{ render(await api("/api/admin/list",{password:PW})); }catch(err){ toast(err.message,"err"); } }
refreshBtn.onclick=refresh;

function render(d){
  JOBS=d.jobs||[];
  meta.textContent=`${JOBS.length} job(s) · auto-delete after ${d.ttl_hours}h`;
  if(!JOBS.length){ tableWrap.innerHTML='<div class="empty">Koi stored job nathi.</div>'; selAll.checked=false; updateDel(); return; }
  let h='<table><thead><tr><th></th><th>Completed</th><th>Files</th><th>Size</th><th>Job ID</th></tr></thead><tbody>';
  JOBS.forEach((j,i)=>{
    const fnames=j.files.length?j.files.map(f=>`<span class="fn">${esc(f.name)} <span class="muted">(${fmtSize(f.size)})</span></span>`).join(""):'<span class="muted">— no output —</span>';
    h+=`<tr>
      <td><input type="checkbox" class="rowcb" data-i="${i}" ${j.active?"disabled":""}></td>
      <td>${esc(fmtDate(j.completed))}${j.active?'<span class="pill-active">processing</span>':''}</td>
      <td>${fnames}</td>
      <td>${fmtSize(j.total_size)}</td>
      <td><span class="jid">${esc(j.job)}</span></td>
    </tr>`;
  });
  h+='</tbody></table>';
  tableWrap.innerHTML=h;
  tableWrap.querySelectorAll(".rowcb").forEach(cb=>cb.onchange=updateDel);
  selAll.checked=false; updateDel();
}
selAll.onchange=()=>{ tableWrap.querySelectorAll(".rowcb:not(:disabled)").forEach(cb=>cb.checked=selAll.checked); updateDel(); };
function selected(){ return [...tableWrap.querySelectorAll(".rowcb:checked")].map(cb=>JOBS[+cb.dataset.i].job); }
function updateDel(){ const n=selected().length; delBtn.disabled=!n; delBtn.textContent=n?`Delete Selected (${n})`:"Delete Selected"; }

delBtn.onclick=async ()=>{
  const jobs=selected(); if(!jobs.length) return;
  if(!confirm(`Delete ${jobs.length} job(s)? Aa permanent chhe.`)) return;
  try{ const d=await api("/api/admin/delete",{password:PW,jobs});
    toast(`Deleted ${d.deleted.length} job(s)`); refresh();
  }catch(err){ toast(err.message,"err"); }
};

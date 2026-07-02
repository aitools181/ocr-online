"""
app.py — FastAPI backend for SMVS OCR.

Endpoints:
  GET  /                      -> web UI
  GET  /api/languages         -> available languages (installed flag)
  POST /api/convert           -> multipart files + options JSON -> results
  GET  /api/download/{job}/{f}-> generated .txt/.docx/.zip
"""

import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               RedirectResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles

import engine
import db
import storage
import emailer
import permissions

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
os.makedirs(JOBS, exist_ok=True)
# Uploaded fonts: persistent (JOBS volume ni andar, cleanup aane skip kare)
FONTS_DIR = os.environ.get("FONTS_DIR", os.path.join(JOBS, "_fonts"))
os.makedirs(FONTS_DIR, exist_ok=True)


def _load_config():
    """config.yaml (YAML) thi settings vaancho. admin_password ahiya set karo."""
    cfg = {}
    cfg_path = os.path.join(BASE, "config.yaml")
    if os.path.isfile(cfg_path):
        try:
            import yaml
            with open(cfg_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            cfg = {}
    return cfg


_CFG = _load_config()
# Output convert-complete thaya pachhi ketla kalak rahe (default 24)
JOB_TTL = int(_CFG.get("output_retention_hours", 24)) * 60 * 60
# Admin login password: config.yaml > env > "admin" (fresh deploy default - badlo!)
ADMIN_PASSWORD = str(_CFG.get("admin_password") or os.environ.get("ADMIN_PASSWORD", "") or "admin").strip()
MAX_FILES = int(_CFG.get("max_files", 50))
ACTIVE_JOBS = set()        # atyare process thati jobs - cleanup aane skip kare

APP_VERSION = "4.0"
APP_DATE    = "02-07-2026"

storage.configure(storage.load_runtime_config(JOBS) or _CFG.get("storage", {}))
storage.start_retry_worker(db, JOBS)
emailer.configure(storage.load_email_config(JOBS) or _CFG.get("email", {}))

# Bootstrap default roles if none exist (admin = all tabs, user = app only)
def _bootstrap_roles():
    existing = {r["name"] for r in db.role_list()}
    if "admin" not in existing:
        db.role_upsert("admin", permissions.all_keys())   # full admin (all tabs + app)
    if "user" not in existing:
        db.role_upsert("user", ["app.ocr", "app.feedback"])
_bootstrap_roles()

# ------------------------------------------------------------------ AUTH
USERS_DIR = os.path.join(JOBS, "_users")
os.makedirs(USERS_DIR, exist_ok=True)
USERS_FILE = os.path.join(USERS_DIR, "users.json")
SECRET_FILE = os.path.join(USERS_DIR, "secret")
COOKIE = "smvs_session"
SESSION_DAYS = 7
ADMIN_USERNAME = str(_CFG.get("admin_username") or os.environ.get("ADMIN_USERNAME", "admin")).strip()

if os.path.isfile(SECRET_FILE):
    with open(SECRET_FILE, "rb") as f:
        SECRET = f.read()
else:
    SECRET = os.urandom(32)
    try:
        with open(SECRET_FILE, "wb") as f:
            f.write(SECRET)
    except OSError:
        pass

_UNAME_RE = re.compile(r"^[A-Za-z0-9._-]{2,40}$")
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")

VISITOR_COOKIE = "smvs_vid"


def _client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _device_label(request: Request):
    ua = request.headers.get("user-agent", "") or ""
    return ua[:180]  # raw UA, truncated — lightweight, no extra parsing dependency


_geo_cache = {}


def _geo_lookup(ip):
    """Free IP geolocation (ip-api.com). Private/LAN IPs → 'Local Network'.
    Cached in-memory to avoid repeat lookups."""
    if not ip:
        return None
    if ip in _geo_cache:
        return _geo_cache[ip]
    # Private ranges
    if ip.startswith(("10.", "192.168.", "127.")) or ip == "localhost" or \
       any(ip.startswith(f"172.{i}.") for i in range(16, 32)):
        _geo_cache[ip] = "Local Network"
        return "Local Network"
    loc = None
    try:
        import urllib.request, json as _json
        with urllib.request.urlopen(
                f"http://ip-api.com/json/{ip}?fields=status,city,regionName,country", timeout=3) as r:
            d = _json.loads(r.read().decode())
            if d.get("status") == "success":
                parts = [d.get("city"), d.get("regionName"), d.get("country")]
                loc = ", ".join(p for p in parts if p)
    except Exception:
        loc = None
    _geo_cache[ip] = loc
    return loc


def _client_meta(request: Request):
    """IP + device + location for tracking."""
    ip = _client_ip(request)
    return ip, _device_label(request), _geo_lookup(ip)


def _hash_pw(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000).hex()


def _verify_pw(password, salt_hex, hash_hex):
    try:
        return hmac.compare_digest(_hash_pw(password, bytes.fromhex(salt_hex)), hash_hex)
    except Exception:
        return False


def _load_users():
    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_users(users):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f)
    os.replace(tmp, USERS_FILE)


def verify_credentials(username, password):
    """superadmin = config; baki users = users.json. Match thay to user dict, nahi to None."""
    if username == ADMIN_USERNAME and ADMIN_PASSWORD and \
            hmac.compare_digest(str(password), ADMIN_PASSWORD):
        return {"username": username, "role": "superadmin"}
    u = _load_users().get(username)
    if u and _verify_pw(password, u.get("salt", ""), u.get("hash", "")):
        if not u.get("active", True):
            return "inactive"   # sentinel — user exists but deactivated
        return {"username": username, "role": u.get("role", "user")}
    return None


def _role_perms(role_name):
    """Lookup a role's permission list from DB."""
    r = db.role_get(role_name)
    return r["permissions"] if r else None


def _has_perm(user, permission):
    """Check if a logged-in user dict has a permission."""
    if not user:
        return False
    return permissions.has_permission(user.get("role", "user"), permission, _role_perms)


def _user_allowed_tabs(user):
    """List of admin.* tab keys this user can access."""
    if not user:
        return []
    if user.get("role") == "superadmin":
        return [t["key"] for t in permissions.admin_tab_permissions()]
    perms = _role_perms(user.get("role", "user")) or []
    return [k for k in perms if k.startswith("admin.")]


def _endpoint_permission(path):
    """Map an /api/admin/* path to the admin.* permission it requires. None = no specific gate."""
    mapping = [
        ("/api/admin/dashboard", "admin.dashboard"),
        ("/api/admin/users",     "admin.users"),
        ("/api/admin/roles",     "admin.roles"),
        ("/api/admin/permissions-catalog", "admin.roles"),
        ("/api/admin/fonts",     "admin.fonts"),
        ("/api/admin/list",      "admin.jobs"),   # stored jobs listing
        ("/api/admin/delete",    "admin.jobs"),
        ("/api/admin/storage",   "admin.cloud"),
        ("/api/admin/feedback",  "admin.feedback"),
        ("/api/admin/email",     "admin.email"),
    ]
    for prefix, perm in mapping:
        if path.startswith(prefix):
            return perm
    return None


def _make_token(username, role):
    exp = int(time.time()) + SESSION_DAYS * 86400
    payload = f"{username}|{role}|{exp}"
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}|{sig}".encode()).decode()


def _read_token(token):
    if not token:
        return None
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        username, role, exp, sig = raw.rsplit("|", 3)
        payload = f"{username}|{role}|{exp}"
        good = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good) or int(exp) < time.time():
            return None
        return {"username": username, "role": role}
    except Exception:
        return None
# --------------------------------------------------------------- END AUTH

# Static files: normally BASE/static, pan jo files repo root ma (static/ vagar)
# hoy to e pan support karo, jethi deploy crash na thay.
STATIC = os.path.join(BASE, "static")
if not os.path.isdir(STATIC) and os.path.isfile(os.path.join(BASE, "index.html")):
    STATIC = BASE
os.makedirs(STATIC, exist_ok=True)

app = FastAPI(title="SMVS OCR")

_PUBLIC = {"/login", "/api/login", "/health", "/favicon.ico", "/api/visitor-count",
           "/api/signup", "/api/check-username", "/api/approve-user",
           "/reset-password", "/api/forgot-password", "/api/reset-password",
           "/api/feedback", "/api/ping", "/api/track-view",
           "/reject-user", "/api/reject-user"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _PUBLIC or path.startswith("/static/"):
        return await call_next(request)
    user = _read_token(request.cookies.get(COOKIE))
    if not user:
        if path.startswith("/api/"):
            return JSONResponse({"error": "Login required"}, status_code=401)
        return RedirectResponse("/login")
    # Admin area access: superadmin, or any role that has at least one admin.* permission
    if path == "/admin" or path.startswith("/api/admin"):
        allowed_tabs = _user_allowed_tabs(user)
        if user.get("role") != "superadmin" and not allowed_tabs:
            if path.startswith("/api/"):
                return JSONResponse({"error": "Admin access only"}, status_code=403)
            return RedirectResponse("/")
        # Per-endpoint permission: map API path prefix → required admin tab permission
        if path.startswith("/api/admin") and user.get("role") != "superadmin":
            required = _endpoint_permission(path)
            if required and required not in allowed_tabs:
                return JSONResponse({"error": "You don't have permission for this action."}, status_code=403)
    request.state.user = user
    return await call_next(request)


def _track_page_view(request: Request, response, page: str, logged_in: bool):
    """Visitor session cookie set kare. View count HAVE frontend /api/track-view thi thay chhe
    (sessionStorage guard sathe) jethi refresh par count na vadhe (point 10)."""
    vid = request.cookies.get(VISITOR_COOKIE)
    if not vid:
        vid = db.new_session_id()
        response.set_cookie(VISITOR_COOKIE, vid, max_age=30 * 86400, httponly=True, samesite="lax")


def _cleanup():
    now = time.time()
    for d in os.listdir(JOBS):
        p = os.path.join(JOBS, d)
        try:
            if d in ACTIVE_JOBS or d.startswith("_"):   # _fonts vagere skip
                continue
            if not os.path.isdir(p) or now - os.path.getmtime(p) <= JOB_TTL:
                continue
            if storage.is_enabled():
                # Cloud configured chhe: upload_failed batch ne skip karo (retry worker
                # mate local copy joiye chhe), baki TTL expire thaya pachi normal delete.
                if db.batch_has_pending_upload(d):
                    continue
            shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


def _safe(name):
    name = os.path.basename(name)
    return re.sub(r"[^A-Za-z0-9._-]", "_", name) or "file"


@app.get("/api/languages")
def languages():
    installed = engine.installed_languages()
    return [{"code": c, "name": n, "glyph": g, "installed": c in installed}
            for (n, c, g) in engine.LANGUAGES]


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    path = os.path.join(STATIC, "login.html")
    if not os.path.isfile(path):
        return HTMLResponse("<h2>Login page not found (static/login.html).</h2>")
    with open(path, encoding="utf-8") as f:
        html = f.read()

    def ver(name):
        p = os.path.join(STATIC, name)
        return str(int(os.path.getmtime(p))) if os.path.isfile(p) else "1"
    html = html.replace("/static/style.css", f"/static/style.css?v={ver('style.css')}")
    resp = HTMLResponse(html)
    _track_page_view(request, resp, "login", logged_in=False)
    return resp


@app.post("/api/login")
async def api_login(request: Request, username: str = Form(...), password: str = Form(...)):
    ip, device, location = _client_meta(request)
    username = username.strip()
    user = verify_credentials(username, password)
    if user == "inactive":
        try: db.login_record(username, ip, device, location, success=False)
        except Exception: pass
        return JSONResponse({"error": "Your account is deactivated. Contact administrator."}, status_code=403)
    if not user:
        try:
            db.login_record(username, ip, device, location, success=False)
        except Exception:
            pass
        return JSONResponse({"error": "Wrong username or password."}, status_code=401)
    try:
        db.login_record(user["username"], ip, device, location, success=True)
    except Exception:
        pass
    has_admin = bool(_user_allowed_tabs(user)) or user["role"] == "superadmin"
    resp = JSONResponse({"ok": True, "username": user["username"], "role": user["role"],
                         "has_admin": has_admin})
    resp.set_cookie(COOKIE, _make_token(user["username"], user["role"]),
                    max_age=SESSION_DAYS * 86400, httponly=True, samesite="lax")
    return resp


@app.post("/api/logout")
async def api_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE)
    return resp


@app.get("/api/me")
async def api_me(request: Request):
    u = getattr(request.state, "user", None)
    if not u:
        return JSONResponse({"error": "Login required"}, status_code=401)
    allowed_tabs = _user_allowed_tabs(u)
    return {"username": u["username"], "role": u["role"],
            "allowed_tabs": allowed_tabs,
            "has_admin": bool(allowed_tabs) or u["role"] == "superadmin",
            "can_ocr": u["role"] == "superadmin" or _has_perm(u, "app.ocr"),
            "can_feedback": u["role"] == "superadmin" or _has_perm(u, "app.feedback")}


@app.post("/api/me/change-password")
async def api_change_password(request: Request, payload: dict):
    """Logged-in user pote j password change kare — current password verify karine.
    Admin user (config-based password) aa thi change nathi kari shakto — admin password
    config.yaml/env ma j chhe, e alag flow chhe (reset to admin's job)."""
    u = getattr(request.state, "user", None)
    if not u:
        return JSONResponse({"error": "Login required"}, status_code=401)
    username = u["username"]
    current_password = str(payload.get("current_password", ""))
    new_password = str(payload.get("new_password", ""))
    if len(new_password) < 6:
        return JSONResponse({"error": "New password must be at least 6 characters."}, status_code=400)
    if username == ADMIN_USERNAME:
        return JSONResponse(
            {"error": "Admin password is set via config.yaml/environment, not changeable here."},
            status_code=400)
    users = _load_users()
    urec = users.get(username)
    if not urec or not _verify_pw(current_password, urec.get("salt", ""), urec.get("hash", "")):
        return JSONResponse({"error": "Current password is incorrect."}, status_code=401)
    salt = os.urandom(16)
    urec["salt"] = salt.hex()
    urec["hash"] = _hash_pw(new_password, salt)
    users[username] = urec
    _save_users(users)
    return {"ok": True}


@app.get("/api/fonts")
def fonts():
    groups = []
    order = []
    bucket = {}
    for name, grp in engine.BUILTIN_FONTS:
        if grp not in bucket:
            bucket[grp] = []
            order.append(grp)
        bucket[grp].append(name)
    for grp in order:
        groups.append({"label": grp, "fonts": bucket[grp]})
    uploaded = [f["name"] for f in engine.list_uploaded_fonts(FONTS_DIR)]
    if uploaded:
        groups.append({"label": "Uploaded Fonts", "fonts": uploaded})
    return {"default": engine.DEFAULT_DOCX_FONT, "groups": groups}


@app.post("/api/fonts/upload")
async def upload_font(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in (".ttf", ".otf"):
        return JSONResponse({"error": "Only .ttf or .otf font files are allowed."}, status_code=400)
    data = await file.read()
    if len(data) > 12 * 1024 * 1024:                 # 12 MB cap
        return JSONResponse({"error": "Font file too large (max 12 MB)."}, status_code=400)
    safe = _safe(file.filename)
    dest = os.path.join(FONTS_DIR, safe)
    with open(dest, "wb") as f:
        f.write(data)
    try:
        name = engine.font_family_name(dest)        # validate it's a real font
    except Exception:
        os.remove(dest)
        return JSONResponse({"error": "Could not read this font file."}, status_code=400)
    return {"name": name, "file": safe}


@app.post("/api/convert")
async def convert(request: Request, files: list[UploadFile] = File(...), options: str = Form(...)):
    # Permission gate: user must have app.ocr (superadmin always allowed)
    _u = getattr(request.state, "user", None)
    if not (_u and (_u.get("role") == "superadmin" or _has_perm(_u, "app.ocr"))):
        raise HTTPException(403, "You do not have permission to use OCR conversion.")
    _cleanup()
    try:
        opts = json.loads(options)
    except json.JSONDecodeError:
        raise HTTPException(400, "Invalid options JSON")
    if not files:
        raise HTTPException(400, "No files uploaded")
    if len(files) > MAX_FILES:
        raise HTTPException(400, f"Too many files (max {MAX_FILES})")

    dpi = int(opts.get("dpi", 300))
    force_ocr = bool(opts.get("force_ocr", False))
    pagewise = opts.get("layout", "pagewise") == "pagewise"
    formats = opts.get("formats") or ["txt", "docx"]
    want_txt = "txt" in formats
    want_docx = "docx" in formats
    font = opts.get("font") or engine.DEFAULT_DOCX_FONT
    style = "text" if opts.get("convert_style") == "text" else "full"
    psm = 6 if str(opts.get("psm")) == "6" else 3
    line_mode = bool(opts.get("line_mode", False))
    default_pdf = bool(opts.get("searchable_pdf", False))   # fallback if per-file absent
    default_langs = opts.get("langs") or ["eng"]
    items_opt = opts.get("items") or []      # per-file: [{langs:[], pages:"", searchable_pdf:bool}]

    job = uuid.uuid4().hex
    job_dir = os.path.join(JOBS, job)
    in_dir = os.path.join(job_dir, "in")
    out_dir = os.path.join(job_dir, "out")
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    # Job nu username metadata save karo
    current_user = getattr(request.state, "user", None)
    job_username = current_user.get("username", "unknown") if current_user else "unknown"
    meta_path = os.path.join(job_dir, "meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"username": job_username}, f)
    except OSError:
        pass

    # Files ne pehla disk par save karo (async), pachhi stream ma process.
    saved = []
    used = set()
    for idx, uf in enumerate(files):
        safe = _safe(uf.filename)
        src = os.path.join(in_dir, f"{idx:02d}_{safe}")
        with open(src, "wb") as f:
            f.write(await uf.read())
        it = items_opt[idx] if idx < len(items_opt) else {}
        langs = it.get("langs") or default_langs
        pages = it.get("pages") or ""
        stem = os.path.splitext(safe)[0]
        while stem in used:                 # duplicate output names avoid
            stem += "_"
        used.add(stem)
        # Auto language: PDF nu script detect karine languages nakki karo
        if [str(x).lower() for x in langs] == ["auto"]:
            try:
                langs = engine.detect_languages(src)
            except Exception:
                langs = ["guj", "eng"]
        # selected pages + total (queue/progress bars mate)
        sel = None
        total = 0
        try:
            pc = engine.page_count(src)
            if pages:
                sel = engine.parse_range(pages, pc) or None
            total = len(sel) if sel else pc
        except Exception:
            total = 0
        wpdf = bool(it.get("searchable_pdf", default_pdf))   # per-file searchable PDF
        saved.append((uf.filename, stem, src, langs, sel, total, wpdf))

    # --- DB: queue position (before adding ours) + per-file time estimate (step 2/3) ---
    queue_ahead = db.jobs_pending_count()
    sec_per_page = db.avg_seconds_per_page()
    sub_job_ids = []
    ip, device, location = _client_meta(request)
    for (orig, stem, src, langs, sel, total, wpdf) in saved:
        sub_id = f"{job}_{len(sub_job_ids):02d}"
        sub_job_ids.append(sub_id)
        db.job_create(sub_id, job_username, orig, language="+".join(langs) if langs else None,
                      mode=("line" if line_mode else "paragraph"), ip=ip, location=location,
                      device=device)
        db.job_update(sub_id, pages=total * (2 if wpdf else 1))

    def gen():
        import queue as _q
        import threading
        q = _q.Queue()
        produced = []

        def worker():
            ACTIVE_JOBS.add(job)
            q.put({"type": "start", "job": job})
            # Plan: badhi files na page totals + estimated seconds (queue/progress bars mate)
            q.put({"type": "plan", "queue_ahead": queue_ahead,
                   "files": [{"name": o, "pages_total": t * (2 if wp else 1),
                              "estimated_sec": round(t * (2 if wp else 1) * sec_per_page, 1)}
                             for (o, _s, _src, _l, _sel, t, wp) in saved],
                   "total_estimated_sec": round(
                       sum(t * (2 if wp else 1) for (_o, _s, _src, _l, _sel, t, wp) in saved)
                       * sec_per_page, 1)})
            try:
                for fidx, (orig, stem, src, langs, sel, total, want_pdf) in enumerate(saved):
                    sub_id = sub_job_ids[fidx]
                    db.job_update(sub_id, status="processing", start_time=time.time())
                    lang_str = "+".join(langs) if langs else "eng"
                    units = total * (2 if want_pdf else 1)   # structured + pdf pass
                    q.put({"type": "file_start", "name": orig, "langs": langs,
                           "pages_total": units})
                    q.put({"type": "log", "name": orig,
                           "msg": f"Output Mode: {'Line by Line' if line_mode else 'Paragraph'}"})
                    t0 = time.time()
                    try:
                        done = [0]

                        def prog(_n=orig, _t=units, _d=done):
                            _d[0] += 1
                            q.put({"type": "progress", "name": _n,
                                   "done": _d[0], "total": _t})

                        items = engine.build_document(
                            src, lang_str, dpi, force_ocr, sel, style=style, psm=psm,
                            line_mode=line_mode,
                            progress=prog,
                            log=lambda m, _n=orig: q.put({"type": "log", "name": _n, "msg": m}))
                        text = engine.render_text(items, pagewise, line_mode=line_mode)
                        counts = engine.count_scripts(items, langs)
                        downloads = []
                        if want_txt:
                            tp = os.path.join(out_dir, stem + ".txt")
                            with open(tp, "w", encoding="utf-8") as f:
                                f.write(text)
                            downloads.append({"label": "TXT", "file": stem + ".txt"})
                            produced.append(tp)
                        if want_docx:
                            dp = os.path.join(out_dir, stem + ".docx")
                            engine.write_docx(items, dp, font, pagewise, line_mode=line_mode)
                            downloads.append({"label": "Word", "file": stem + ".docx"})
                            produced.append(dp)
                        if want_pdf:
                            pp = os.path.join(out_dir, stem + "_searchable.pdf")
                            engine.build_searchable_pdf(
                                src, lang_str, dpi, sel, pp, progress=prog,
                                log=lambda m, _n=orig: q.put({"type": "log", "name": _n, "msg": m}))
                            downloads.append({"label": "PDF", "file": stem + "_searchable.pdf"})
                            produced.append(pp)
                        q.put({"type": "file_done", "name": orig, "text": text,
                               "counts": counts, "downloads": downloads, "error": None,
                               "seconds": round(time.time() - t0, 1)})

                        # --- Cloud upload: sirf original + TXT j upload karvu (point 3)
                        file_paths = [src]
                        if want_txt and 'tp' in dir():
                            if os.path.isfile(tp): file_paths.append(tp)
                        file_paths = [p for p in file_paths if p and os.path.isfile(p)]
                        dur = round(time.time() - t0, 1)
                        primary_out = (downloads[0]["file"] if downloads else None)
                        if storage.is_enabled():
                            try:
                                provider, link = storage.upload_job_files(
                                    job_username, sub_id, stem, file_paths)
                                db.job_update(sub_id, status="completed", end_time=time.time(),
                                              duration_sec=dur, output_filename=primary_out,
                                              cloud_provider=provider, cloud_folder_link=link)
                            except Exception as ue:
                                db.job_update(sub_id, status="upload_failed", end_time=time.time(),
                                              duration_sec=dur, output_filename=primary_out,
                                              error_message=str(ue)[:300])
                                q.put({"type": "log", "name": orig,
                                       "msg": f"Cloud upload pending/retry: {ue}"})
                        else:
                            db.job_update(sub_id, status="completed", end_time=time.time(),
                                          duration_sec=dur, output_filename=primary_out)
                    except Exception as e:
                        db.job_update(sub_id, status="error", end_time=time.time(),
                                      error_message=str(e)[:300])
                        q.put({"type": "file_done", "name": orig, "text": "", "counts": {},
                               "downloads": [], "error": str(e),
                               "seconds": round(time.time() - t0, 1)})

                zip_name = None
                if len(produced) > 1:
                    zip_name = "smvs_output.zip"
                    zp = os.path.join(out_dir, zip_name)
                    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
                        for p in produced:
                            z.write(p, os.path.basename(p))
                q.put({"type": "done", "job": job, "zip": zip_name})
            finally:
                # uploaded input files turant delete (server par fakt output 24h rahe)
                shutil.rmtree(in_dir, ignore_errors=True)
                # TTL output complete thaya pachhi shuru thay + active set mathi kaadho
                try:
                    os.utime(job_dir, None)
                except OSError:
                    pass
                ACTIVE_JOBS.discard(job)
                q.put(None)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            ev = q.get()
            if ev is None:
                break
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/pagecount")
async def pagecount(file: UploadFile = File(...)):
    """File na page count return kare (PDF/multipage image) - checkboxes mate."""
    tmp = os.path.join(JOBS, "_count_" + uuid.uuid4().hex + os.path.splitext(_safe(file.filename))[1])
    try:
        with open(tmp, "wb") as f:
            f.write(await file.read())
        n = engine.page_count(tmp)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return {"pages": n}


@app.get("/api/admin/list")
async def admin_list():
    jobs = []
    for d in sorted(os.listdir(JOBS)):
        if d.startswith("_"):                 # _fonts/_users skip
            continue
        p = os.path.join(JOBS, d)
        if not os.path.isdir(p):
            continue
        out_dir = os.path.join(p, "out")
        files, total = [], 0
        if os.path.isdir(out_dir):
            for fn in os.listdir(out_dir):
                fp = os.path.join(out_dir, fn)
                if os.path.isfile(fp):
                    sz = os.path.getsize(fp)
                    files.append({"name": fn, "size": sz})
                    total += sz
        mt = os.path.getmtime(p)
        # Job username meta.json mathi vaancho
        job_user = "—"
        meta_path = os.path.join(p, "meta.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, encoding="utf-8") as f:
                    meta = json.load(f)
                    job_user = meta.get("username", "—")
            except Exception:
                pass
        jobs.append({
            "job": d,
            "username": job_user,
            "completed": datetime.fromtimestamp(mt, timezone.utc).isoformat(),
            "completed_epoch": mt,
            "active": d in ACTIVE_JOBS,
            "files": files,
            "total_size": total,
        })
    jobs.sort(key=lambda j: j["completed_epoch"], reverse=True)
    return {"jobs": jobs, "ttl_hours": JOB_TTL // 3600}



@app.post("/api/admin/delete")
async def admin_delete(payload: dict):
    deleted = []
    for j in payload.get("jobs", []):
        d = os.path.join(JOBS, _safe(j))
        if os.path.isdir(d) and _safe(j) not in ACTIVE_JOBS and not _safe(j).startswith("_"):
            shutil.rmtree(d, ignore_errors=True)
            deleted.append(j)
    return {"ok": True, "deleted": deleted}


# ---- User management (admin only via middleware) ----
@app.get("/api/admin/users")
async def admin_users(request: Request):
    """superadmin ne list ma kadi na batavvu (point 5)."""
    viewer = getattr(request.state, "user", None)
    users = _load_users()
    out = []
    for un, u in sorted(users.items()):
        out.append({"username": un, "role": u.get("role", "user"), "builtin": False,
                    "email": u.get("email", ""), "emails": u.get("emails", []),
                    "first_name": u.get("first_name", ""),
                    "last_name": u.get("last_name", ""),
                    "status": "active" if u.get("active", True) else "inactive"})
    pending = db.pending_user_get_all()
    for p in pending:
        st = p.get("status", "pending")
        out.append({"username": p["username"], "role": "user", "builtin": False,
                    "email": p["email"], "emails": [], "first_name": p["first_name"],
                    "last_name": p["last_name"], "status": st,
                    "reject_reason": p.get("reject_reason", "") if st == "rejected" else ""})
    # roles list for the role-assign dropdown (superadmin excluded)
    roles = [r["name"] for r in db.role_list()]
    return {"users": out, "roles": roles}


@app.post("/api/admin/users")
async def admin_create_user(payload: dict):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    email    = str(payload.get("email", "")).strip()
    fname    = str(payload.get("first_name", "")).strip()
    lname    = str(payload.get("last_name", "")).strip()
    role     = str(payload.get("role", "user")).strip() or "user"
    if not _UNAME_RE.match(username):
        return JSONResponse({"error": "Username: 2-40 chars, letters/digits/._- only."}, status_code=400)
    if len(password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters."}, status_code=400)
    if username == ADMIN_USERNAME:
        return JSONResponse({"error": "That username is reserved."}, status_code=400)
    if role == "superadmin":
        return JSONResponse({"error": "Cannot assign superadmin role."}, status_code=400)
    users = _load_users()
    if db.username_taken(username, users):
        return JSONResponse({"error": "User already exists."}, status_code=400)
    salt = os.urandom(16)
    emails = [email] if email else []
    users[username] = {"salt": salt.hex(), "hash": _hash_pw(password, salt), "role": role,
                       "email": email, "emails": emails,
                       "first_name": fname, "last_name": lname, "active": True}
    _save_users(users)
    return {"ok": True, "username": username}


@app.post("/api/admin/users/edit")
async def admin_edit_user(payload: dict):
    """Edit user details — name, email(s), role, active. Password alag reset flow thi."""
    username = str(payload.get("username", "")).strip()
    if username == ADMIN_USERNAME:
        return JSONResponse({"error": "Built-in account cannot be edited."}, status_code=400)
    users = _load_users()
    if username not in users:
        return JSONResponse({"error": "User not found."}, status_code=404)
    u = users[username]
    if "first_name" in payload: u["first_name"] = str(payload["first_name"]).strip()
    if "last_name" in payload:  u["last_name"]  = str(payload["last_name"]).strip()
    if "email" in payload:      u["email"]      = str(payload["email"]).strip()
    if "emails" in payload and isinstance(payload["emails"], list):
        clean = [e.strip() for e in payload["emails"] if e.strip() and _EMAIL_RE.match(e.strip())]
        u["emails"] = clean
        if clean and not u.get("email"): u["email"] = clean[0]
    if "role" in payload:
        new_role = str(payload["role"]).strip()
        if new_role == "superadmin":
            return JSONResponse({"error": "Cannot assign superadmin role."}, status_code=400)
        u["role"] = new_role or "user"
    if "active" in payload:      u["active"]     = bool(payload["active"])
    users[username] = u
    _save_users(users)
    return {"ok": True}


@app.post("/api/admin/users/toggle-active")
async def admin_toggle_user_active(payload: dict):
    username = str(payload.get("username", "")).strip()
    users = _load_users()
    if username not in users:
        return JSONResponse({"error": "User not found."}, status_code=404)
    users[username]["active"] = not users[username].get("active", True)
    _save_users(users)
    return {"ok": True, "active": users[username]["active"]}


@app.post("/api/admin/users/delete")
async def admin_delete_user(payload: dict):
    username = str(payload.get("username", "")).strip()
    users = _load_users()
    if username in users:
        del users[username]
        _save_users(users)
        return {"ok": True}
    return JSONResponse({"error": "User not found (built-in admin can't be deleted)."}, status_code=400)


@app.post("/api/admin/users/reset-password")
async def admin_reset_password(payload: dict):
    """Admin user no password reset kare."""
    username = str(payload.get("username", "")).strip()
    new_password = str(payload.get("new_password", ""))
    if len(new_password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters."}, status_code=400)
    if username == ADMIN_USERNAME:
        return JSONResponse({"error": "Built-in admin password config.yaml ma badlo."}, status_code=400)
    users = _load_users()
    if username not in users:
        return JSONResponse({"error": "User not found."}, status_code=404)
    salt = os.urandom(16)
    users[username]["salt"] = salt.hex()
    users[username]["hash"] = _hash_pw(new_password, salt)
    _save_users(users)
    return {"ok": True, "username": username}


# ---- Font management (admin only via middleware) ----
@app.get("/api/admin/fonts")
async def admin_fonts():
    return {"fonts": engine.list_uploaded_fonts(FONTS_DIR)}


@app.post("/api/admin/fonts/delete")
async def admin_delete_font(payload: dict):
    fn = _safe(str(payload.get("file", "")))
    p = os.path.join(FONTS_DIR, fn)
    if fn.lower().endswith((".ttf", ".otf")) and os.path.isfile(p):
        os.remove(p)
        return {"ok": True}
    return JSONResponse({"error": "Font not found."}, status_code=400)


# --------------------------------------------------------- ADMIN DASHBOARD (Step 5)

_RANGE_DAYS = {"today": 1, "15d": 15, "month": 30, "6m": 182, "all": None}


def _range_since(range_key):
    """Return the start-timestamp for a range. 'today' = aaj ni midnight thi (calendar day),
    biji ranges = etla days pehla thi. 'all' = None (no limit)."""
    import datetime as _dt
    now = _dt.datetime.now()
    if range_key == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()
    if range_key == "15d":
        start = (now - _dt.timedelta(days=14)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()
    if range_key == "month":
        start = (now - _dt.timedelta(days=29)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()
    if range_key == "6m":
        start = (now - _dt.timedelta(days=181)).replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()
    return None  # all


@app.get("/api/admin/dashboard/summary")
async def admin_dashboard_summary(range: str = "all"):
    since = _range_since(range)
    summary = db.dashboard_summary(since)
    summary["queue_depth"] = db.jobs_pending_count()
    summary["avg_sec_per_page"] = round(db.avg_seconds_per_page(), 2)
    summary["storage_enabled"] = storage.is_enabled()
    return summary


@app.get("/api/admin/dashboard/timeseries")
async def admin_dashboard_timeseries(range: str = "month"):
    days = _RANGE_DAYS.get(range, 30) or 365
    return {"days": days, "data": db.dashboard_timeseries(days)}


@app.get("/api/admin/dashboard/userwise")
async def admin_dashboard_userwise(range: str = "all"):
    since = _range_since(range)
    return {"users": db.dashboard_userwise(since)}


@app.get("/api/admin/dashboard/live")
async def admin_dashboard_live():
    live = db.live_counts()
    live.update(db.page_view_totals())
    return live


@app.get("/api/admin/dashboard/logins")
async def admin_dashboard_logins(limit: int = 500, range: str = "all"):
    since = _range_since(range)
    return {"logins": db.login_history_recent(limit, since)}


@app.get("/api/admin/dashboard/failed-uploads")
async def admin_dashboard_failed_uploads():
    return {"jobs": db.jobs_failed_uploads(), "max_attempts": storage.max_retry_attempts()}


@app.post("/api/admin/dashboard/retry-upload")
async def admin_retry_upload(payload: dict):
    """Admin manually triggers a single retry for one failed job (instead of waiting
    for the periodic background retry cycle)."""
    job_id = str(payload.get("job_id", ""))
    job = db.job_get(job_id)
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    out_dir = os.path.join(JOBS, job_id.rsplit("_", 1)[0], "out")
    if not os.path.isdir(out_dir):
        return JSONResponse({"error": "Local files no longer available"}, status_code=400)
    file_paths = [os.path.join(out_dir, f) for f in os.listdir(out_dir)]
    try:
        stem = os.path.splitext(job["original_filename"] or "file")[0]
        provider, link = storage.upload_job_files(job["username"], job_id, stem, file_paths)
        db.job_update(job_id, status="completed", cloud_provider=provider, cloud_folder_link=link,
                      upload_attempts=(job.get("upload_attempts") or 0) + 1)
        return {"ok": True, "provider": provider, "link": link}
    except Exception as e:
        db.job_update(job_id, upload_attempts=(job.get("upload_attempts") or 0) + 1,
                      error_message=str(e)[:300])
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/api/admin/dashboard/jobs")
async def admin_dashboard_jobs(username: str = None, status: str = None, search: str = None,
                                 limit: int = 200):
    return {"jobs": db.jobs_query(username=username, status=status, search=search, limit=limit)}


# --------------------------------------------------------- CLOUD STORAGE ADMIN (Step 6 UI)

@app.post("/api/admin/storage/toggle-active")
async def admin_storage_toggle():
    """Credentials delete nathi thata — sirf connection deactivate/activate thay chhe."""
    cfg = storage.load_runtime_config(JOBS)
    if not cfg or cfg.get("provider", "none") == "none":
        return JSONResponse({"error": "No provider configured yet."}, status_code=400)
    cfg["active"] = not cfg.get("active", True)
    storage.save_runtime_config(JOBS, cfg)
    storage.configure(cfg)
    return {"ok": True, "active": cfg["active"]}


@app.get("/api/admin/storage/status")
async def admin_storage_status():
    s = storage.masked_status()
    s["pending_count"] = len(db.jobs_failed_uploads())
    return s


@app.post("/api/admin/storage/config")
async def admin_storage_config(payload: dict):
    """Admin panel thi cloud storage connect/update — config.yaml touch karva ni jarur nathi,
    runtime ma j save thay chhe ane immediately apply (no restart needed)."""
    provider = str(payload.get("provider", "none")).strip().lower()
    cfg = {
        "provider": provider,
        "max_retry_attempts": int(payload.get("max_retry_attempts", 8)),
        "retry_interval_sec": int(payload.get("retry_interval_sec", 180)),
    }
    try:
        if provider == "google_drive":
            existing = storage.load_runtime_config(JOBS) or {}
            ex_gd = existing.get("google_drive", {})
            cfg["google_drive"] = {
                "root_folder_id": str(payload.get("root_folder_id", "")).strip(),
                "client_email":   str(payload.get("client_email", "") or ex_gd.get("client_email", "")).strip(),
                "project_id":     str(payload.get("project_id", "") or ex_gd.get("project_id", "")).strip(),
                "private_key":    str(payload.get("private_key", "") or ex_gd.get("private_key", "")).strip(),
            }
            if not cfg["google_drive"]["client_email"] or not cfg["google_drive"]["private_key"]:
                return JSONResponse({"error": "Client Email and Private Key are required."}, status_code=400)
        elif provider == "onedrive":
            existing = storage.load_runtime_config(JOBS) or {}
            existing_secret = existing.get("onedrive", {}).get("client_secret", "")
            cfg["onedrive"] = {
                "tenant_id": str(payload.get("tenant_id", "")).strip(),
                "client_id": str(payload.get("client_id", "")).strip(),
                "client_secret": str(payload.get("client_secret") or existing_secret).strip(),
                "drive_id": str(payload.get("drive_id", "")).strip(),
                "root_path": str(payload.get("root_path", "/SMVS-OCR")).strip(),
            }
        storage.save_runtime_config(JOBS, cfg)
        storage.configure(cfg)
        if provider != "none" and not storage.is_enabled():
            return JSONResponse(
                {"error": "Settings saved, but backend failed to initialize — check credentials."},
                status_code=400)
        return {"ok": True}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/admin/storage/jobs")
async def admin_storage_jobs():
    return {"jobs": db.cloud_jobs_all()}


@app.post("/api/admin/storage/test")
async def admin_storage_test():
    try:
        result = storage.test_connection()
        return result
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=400)


@app.get("/api/admin/storage/jobs")
async def admin_storage_jobs():
    """Cloud Management tab — badha jobs (completed + failed) with server-remove status."""
    jobs = db.cloud_jobs_all()
    for j in jobs:
        job_dir = os.path.join(JOBS, j["job_id"].rsplit("_", 1)[0])
        j["server_files_exist"] = os.path.isdir(job_dir)
    return {"jobs": jobs, "max_attempts": storage.max_retry_attempts()}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    path = os.path.join(STATIC, "admin.html")
    if not os.path.isfile(path):
        return HTMLResponse("<h2>Admin page nathi mali (static/admin.html).</h2>", status_code=200)
    with open(path, encoding="utf-8") as f:
        html = f.read()

    def ver(name):
        p = os.path.join(STATIC, name)
        return str(int(os.path.getmtime(p))) if os.path.isfile(p) else "1"
    html = html.replace("/static/style.css", f"/static/style.css?v={ver('style.css')}")
    html = html.replace("/static/admin.js", f"/static/admin.js?v={ver('admin.js')}")
    return HTMLResponse(html)


@app.post("/api/clear/{job}")
async def clear(job):
    """Job na server-side data (uploads + outputs) kaadi nakho.
    Clear All button ane tab-close (sendBeacon) banne aano upyog kare."""
    d = os.path.join(JOBS, _safe(job))
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    return {"ok": True}


@app.get("/api/download/{job}/{fname}")
def download(job, fname):
    safe = _safe(fname)
    path = os.path.join(JOBS, _safe(job), "out", safe)
    if not os.path.isfile(path):
        raise HTTPException(404, "File not found or expired")
    return FileResponse(path, filename=safe)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    path = os.path.join(STATIC, "index.html")
    if not os.path.isfile(path):
        return HTMLResponse(
            "<h2>SMVS OCR</h2><p>UI files (index.html, style.css, app.js) "
            "nathi malya. Repo ma e files <code>static/</code> folder ma honi joiye. "
            "API kaam kare chhe: <a href='/health'>/health</a></p>", status_code=200)
    with open(path, encoding="utf-8") as f:
        html = f.read()

    # Auto cache-bust: file badle etle browser navu version laave (cache problem solve)
    def ver(name):
        p = os.path.join(STATIC, name)
        return str(int(os.path.getmtime(p))) if os.path.isfile(p) else "1"
    html = html.replace("/static/style.css", f"/static/style.css?v={ver('style.css')}")
    html = html.replace("/static/app.js", f"/static/app.js?v={ver('app.js')}")

    # Server-side role injection — admin user devtools/inspect restriction thi free rahe,
    # ane delay vagar j (page load thatani sathe j role set thai jaay, race-condition nahi).
    u = _read_token(request.cookies.get(COOKIE))
    role = (u or {}).get("role", "guest")
    role_script = f'<script>window.__SMVS_ROLE__={json.dumps(role)};</script>'
    html = html.replace("<head>", "<head>\n" + role_script, 1)

    resp = HTMLResponse(html)
    _track_page_view(request, resp, "app", logged_in=bool(u))
    return resp


@app.get("/health")
def health():
    return {"ok": True, "langs": sorted(engine.installed_languages()),
            "version": APP_VERSION, "date": APP_DATE}


@app.get("/api/version")
def api_version():
    return {"version": APP_VERSION, "date": APP_DATE,
            "email_enabled": emailer.is_enabled()}


# --------------------------------------------------------- ROLE MANAGEMENT
@app.get("/api/admin/permissions-catalog")
async def admin_permissions_catalog():
    """All available permissions grouped — auto-includes any future feature."""
    return {"catalog": permissions.catalog()}


@app.get("/api/admin/roles")
async def admin_roles_list():
    return {"roles": db.role_list(), "catalog": permissions.catalog()}


@app.post("/api/admin/roles")
async def admin_role_save(request: Request, payload: dict):
    """superadmin only — create/update a role with permissions."""
    viewer = getattr(request.state, "user", None)
    if not viewer or viewer.get("role") != "superadmin":
        return JSONResponse({"error": "Only superadmin can manage roles."}, status_code=403)
    name = str(payload.get("name", "")).strip().lower()
    perms = payload.get("permissions", [])
    if not name or not re.match(r"^[a-z0-9_-]{2,30}$", name):
        return JSONResponse({"error": "Role name: 2-30 chars, lowercase letters/digits/_-."}, status_code=400)
    if name == "superadmin":
        return JSONResponse({"error": "'superadmin' is reserved."}, status_code=400)
    if not isinstance(perms, list):
        return JSONResponse({"error": "Invalid permissions."}, status_code=400)
    valid = set(permissions.all_keys())
    perms = [p for p in perms if p in valid]
    db.role_upsert(name, perms)
    return {"ok": True}


@app.post("/api/admin/roles/delete")
async def admin_role_delete(request: Request, payload: dict):
    viewer = getattr(request.state, "user", None)
    if not viewer or viewer.get("role") != "superadmin":
        return JSONResponse({"error": "Only superadmin can manage roles."}, status_code=403)
    name = str(payload.get("name", "")).strip().lower()
    if name == "superadmin":
        return JSONResponse({"error": "Cannot delete superadmin."}, status_code=400)
    # reassign any users with this role back to 'user'
    users = _load_users()
    changed = False
    for un, u in users.items():
        if u.get("role") == name:
            u["role"] = "user"; changed = True
    if changed:
        _save_users(users)
    db.role_delete(name)
    return {"ok": True}


# --------------------------------------------------------- USERNAME CHECK
@app.get("/api/check-username")
async def check_username(username: str = ""):
    username = username.strip()
    if not username:
        return {"available": False, "reason": ""}
    if len(username) < 5:
        return {"available": False, "reason": "Min 5 characters required"}
    if not _UNAME_RE.match(username):
        return {"available": False, "reason": "Letters, digits, . _ - only"}
    if username == ADMIN_USERNAME:
        return {"available": False, "reason": "Username not available"}
    users = _load_users()
    if db.username_taken(username, users):
        return {"available": False, "reason": "Username already taken"}
    return {"available": True, "reason": "Username available"}


# --------------------------------------------------------- SIGNUP
@app.post("/api/signup")
async def api_signup(request: Request, payload: dict):
    username   = str(payload.get("username", "")).strip()
    email      = str(payload.get("email", "")).strip()
    first_name = str(payload.get("first_name", "")).strip()
    last_name  = str(payload.get("last_name", "")).strip()
    password   = str(payload.get("password", ""))
    if len(username) < 5 or not _UNAME_RE.match(username):
        return JSONResponse({"error": "Username min 5 chars, letters/digits/._- only."}, status_code=400)
    if not email or not _EMAIL_RE.match(email):
        return JSONResponse({"error": "Valid email required."}, status_code=400)
    if not first_name:
        return JSONResponse({"error": "First name required."}, status_code=400)
    if not last_name:
        return JSONResponse({"error": "Last name required."}, status_code=400)
    if len(password) < 6:
        return JSONResponse({"error": "Password min 6 characters."}, status_code=400)
    users = _load_users()
    if db.username_taken(username, users):
        return JSONResponse({"error": "Username already taken."}, status_code=409)
    salt   = os.urandom(16)
    pw_hash = _hash_pw(password, salt)
    token  = os.urandom(32).hex()
    db.pending_user_create(username, email, first_name, last_name, salt.hex(), pw_hash, token)
    base = str(request.base_url).rstrip("/")
    approve_link = f"{base}/api/approve-user?token={token}"
    reject_link  = f"{base}/reject-user?token={token}"
    emailer.send_signup_verification(email, first_name, username, approve_link)
    admin_email = emailer._CFG.get("admin_email", "")
    if admin_email:
        emailer.send_admin_approval_request(admin_email, first_name, last_name,
                                             username, email, approve_link, reject_link)
    return {"ok": True, "message": "Signup successful! Check your email. Awaiting admin approval."}


# --------------------------------------------------------- APPROVE USER (email link + admin UI)
def _link_result_page(title, message, success):
    color = "#1e8449" if success else "#c0392b"
    return f"""<html><head><title>{title}</title>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <style>body{{font-family:Inter,Arial,sans-serif;text-align:center;padding:60px 20px;background:#f5f0e8}}
    .box{{background:#fff;border-radius:16px;padding:40px;display:inline-block;box-shadow:0 4px 24px rgba(0,0,0,.1);max-width:400px}}
    h2{{color:{color};margin:0 0 10px}}a{{color:#c97e1a;text-decoration:none;font-weight:600}}
    p{{color:#666}}</style></head>
    <body><div class="box"><h2>{title}</h2>
    <p>{message}</p>
    <a href="/admin">← Go to Admin Panel</a></div></body></html>"""


@app.get("/api/approve-user")
async def api_approve_user(request: Request, token: str = ""):
    pending = db.pending_user_get(token)
    if not pending:
        return HTMLResponse(_link_result_page("Invalid Link", "This approval link is invalid.", False), status_code=400)
    if pending.get("token_used"):
        return HTMLResponse(_link_result_page("Link Already Used",
            "This link has already been used. The request was already processed.", False), status_code=400)
    if pending.get("status") == "rejected":
        return HTMLResponse(_link_result_page("Already Rejected",
            "This request was already rejected and cannot be approved.", False), status_code=400)
    users = _load_users()
    if pending["username"] not in users:
        users[pending["username"]] = {
            "salt": pending["salt"], "hash": pending["hash"], "role": "user",
            "email": pending["email"], "first_name": pending["first_name"],
            "last_name": pending["last_name"], "active": True,
        }
        _save_users(users)
    db.pending_user_delete(pending["username"])   # approved → moves to real users, pending record removed
    login_url = str(request.base_url).rstrip("/") + "/login"
    emailer.send_approval_notification(pending["email"], pending["first_name"], pending["username"], login_url)
    return HTMLResponse(_link_result_page("✅ User Approved!",
        "The user has been notified via email.", True))


@app.get("/reject-user", response_class=HTMLResponse)
async def reject_user_page(token: str = ""):
    """Email thi reject — reason puchhta page batave."""
    pending = db.pending_user_get(token)
    if not pending:
        return HTMLResponse(_link_result_page("Invalid Link", "This link is invalid.", False), status_code=400)
    if pending.get("token_used"):
        return HTMLResponse(_link_result_page("Link Already Used",
            "This link has already been used.", False), status_code=400)
    html = f"""<!DOCTYPE html><html><head><title>Reject User · SMVS OCR</title>
    <meta name="viewport" content="width=device-width,initial-scale=1"/>
    <style>body{{font-family:Inter,Arial,sans-serif;background:#f5f0e8;display:flex;align-items:center;
      justify-content:center;min-height:100vh;margin:0}}
    .card{{background:#fff;border-radius:16px;padding:34px;width:min(420px,92vw);box-shadow:0 8px 32px rgba(0,0,0,.12)}}
    h2{{font-size:19px;margin:0 0 6px;color:#2c2c4a}}
    .u{{background:#faf7f1;border-radius:10px;padding:12px 16px;margin:14px 0}}
    label{{font-size:12px;font-weight:600;color:#777;display:block;margin-bottom:6px}}
    textarea{{width:100%;box-sizing:border-box;padding:10px 12px;border:1.5px solid #e8dfc8;border-radius:9px;
      font:inherit;font-size:14px;resize:vertical;min-height:90px}}
    textarea:focus{{outline:none;border-color:#e74c3c;box-shadow:0 0 0 3px rgba(231,76,60,.12)}}
    .btn{{width:100%;padding:12px;background:#e74c3c;color:#fff;border:none;border-radius:10px;
      font:inherit;font-size:15px;font-weight:700;cursor:pointer;margin-top:14px}}
    .msg{{font-size:13px;margin-top:10px;padding:10px;border-radius:8px;text-align:center;display:none}}</style></head>
    <body><div class="card">
    <h2>✗ Reject User Request</h2>
    <div class="u"><div style="font-size:12px;color:#888">User</div>
      <div style="font-size:16px;font-weight:700;color:#2c2c4a">{pending['first_name']} {pending['last_name']} ({pending['username']})</div></div>
    <label>Reason for rejection (admin record only — NOT sent to user)</label>
    <textarea id="reason" placeholder="e.g. Not a recognized member, duplicate account..."></textarea>
    <div id="msg" class="msg"></div>
    <button class="btn" id="btn">Confirm Reject</button>
    </div>
    <script>
    document.getElementById("btn").onclick=async()=>{{
      const reason=document.getElementById("reason").value.trim();
      const msg=document.getElementById("msg");
      if(!reason){{msg.style.display="block";msg.style.background="#fbe1de";msg.style.color="#c0392b";msg.textContent="Please enter a reason.";return;}}
      const r=await fetch("/api/reject-user",{{method:"POST",headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{token:"{token}",reason}})}});
      const d=await r.json();
      msg.style.display="block";
      if(r.ok&&d.ok){{msg.style.background="#e3f6ea";msg.style.color="#1e8449";
        msg.textContent="User rejected. Notification sent. This window will close in 5 seconds…";
        document.getElementById("btn").disabled=true;
        setTimeout(()=>{{ window.open('','_self'); window.close(); location.href='about:blank'; }},5000);}}
      else{{msg.style.background="#fbe1de";msg.style.color="#c0392b";msg.textContent=d.error||"Error";}}
    }};
    </script></body></html>"""
    return HTMLResponse(html)


@app.post("/api/reject-user")
async def api_reject_user_email(payload: dict):
    """Email-link reject submit (public, token-gated)."""
    token  = str(payload.get("token", ""))
    reason = str(payload.get("reason", "")).strip()
    pending = db.pending_user_get(token)
    if not pending:
        return JSONResponse({"error": "Invalid link."}, status_code=400)
    if pending.get("token_used"):
        return JSONResponse({"error": "This link has already been used."}, status_code=400)
    if not reason:
        return JSONResponse({"error": "Reason required."}, status_code=400)
    db.pending_user_mark_rejected(pending["username"], reason)
    emailer.send_rejection_notification(pending["email"], pending["first_name"], pending["username"])
    return {"ok": True}


@app.post("/api/admin/users/approve")
async def admin_approve_user(request: Request, payload: dict):
    username = str(payload.get("username", "")).strip()
    pending = db.pending_user_get_by_name(username)
    if not pending or pending.get("status") != "pending":
        return JSONResponse({"error": "Pending user not found."}, status_code=404)
    users = _load_users()
    users[username] = {
        "salt": pending["salt"], "hash": pending["hash"], "role": "user",
        "email": pending["email"], "first_name": pending["first_name"],
        "last_name": pending["last_name"], "active": True,
    }
    _save_users(users)
    db.pending_user_delete(username)
    login_url = str(request.base_url).rstrip("/") + "/login"
    emailer.send_approval_notification(pending["email"], pending["first_name"], username, login_url)
    return {"ok": True}


@app.post("/api/admin/users/reject")
async def admin_reject_user(payload: dict):
    """Admin UI reject — reason store thay, user ne notification jaay (reason vagar)."""
    username = str(payload.get("username", "")).strip()
    reason   = str(payload.get("reason", "")).strip()
    if not reason:
        return JSONResponse({"error": "Rejection reason required."}, status_code=400)
    pending = db.pending_user_get_by_name(username)
    if not pending:
        return JSONResponse({"error": "Pending user not found."}, status_code=404)
    db.pending_user_mark_rejected(username, reason)
    emailer.send_rejection_notification(pending["email"], pending["first_name"], username)
    return {"ok": True}


@app.post("/api/admin/users/delete-rejected")
async def admin_delete_rejected(payload: dict):
    """Rejected record ne kaadhi nakhvu (cleanup)."""
    username = str(payload.get("username", "")).strip()
    db.pending_user_delete(username)
    return {"ok": True}


# ------------------------------------------------- FORGOT / RESET PASSWORD
@app.post("/api/forgot-password")
async def api_forgot_password(request: Request, payload: dict):
    username = str(payload.get("username", "")).strip()
    if not username:
        return JSONResponse({"error": "Username required."}, status_code=400)
    users = _load_users()
    urec = users.get(username)
    # Always return ok-ish (don't reveal if user exists) — but if found, send + mask
    if urec and urec.get("email"):
        email = urec["email"]
        token = db.reset_token_create(username, expires_minutes=15)
        base  = str(request.base_url).rstrip("/")
        link  = f"{base}/reset-password?token={token}"
        # Synchronous send so user knows immediately it went out
        sent = emailer.send_password_reset_sync(email, urec.get("first_name", username), link, username=username)
        masked = _mask_email(email)
        if sent:
            return {"ok": True, "message": f"✅ Reset link sent to <b>{masked}</b> — check your inbox (expires in 15 min)."}
        return JSONResponse({"error": "Email could not be sent. Contact admin."}, status_code=500)
    return {"ok": True, "message": "If that username exists, a reset link has been sent to the registered email."}


def _mask_email(email):
    """abc12345@xyz.com → abc*****45@xyz.com"""
    try:
        local, domain = email.split("@", 1)
        if len(local) <= 4:
            masked = local[0] + "*" * (len(local) - 1)
        else:
            masked = local[:3] + "*" * (len(local) - 5) + local[-2:]
        return f"{masked}@{domain}"
    except Exception:
        return "your registered email"


@app.get("/reset-password", response_class=HTMLResponse)
async def reset_password_page(token: str = ""):
    html = f"""<!DOCTYPE html><html><head><title>Reset Password · SMVS OCR</title>
    <link rel="stylesheet" href="/static/style.css"/>
    <style>body{{display:flex;align-items:center;justify-content:center;min-height:100vh;background:#f5f0e8}}
    .rp-card{{background:#fff;border-radius:16px;padding:36px;width:min(380px,90vw);
      box-shadow:0 8px 32px rgba(0,0,0,.12)}}
    h2{{font-family:Sora,sans-serif;font-size:20px;margin:0 0 20px;color:#2c2c4a}}
    label{{display:block;margin-bottom:14px;font-size:13px;font-weight:600;color:#666}}
    input{{width:100%;padding:10px 12px;border:1px solid #e0d8c8;border-radius:9px;font:inherit;
      font-size:14px;box-sizing:border-box;margin-top:4px}}
    input:focus{{outline:2px solid #e8a020;border-color:#e8a020}}
    .btn{{width:100%;padding:12px;background:linear-gradient(135deg,#c97e1a,#e8a020);color:#fff;
      border:none;border-radius:10px;font:inherit;font-size:15px;font-weight:700;cursor:pointer;margin-top:8px}}
    .msg{{font-size:13px;margin-top:10px;padding:10px;border-radius:8px;text-align:center}}
    .err{{background:#fbe1de;color:#c0392b}}.ok{{background:#e3f6ea;color:#1e8449}}</style></head>
    <body><div class="rp-card">
    <img src="/static/logo.png" style="width:48px;margin-bottom:16px" />
    <h2>🔑 Reset Password</h2>
    <div id="msg"></div>
    <label>New Password<input id="np" type="password" placeholder="Min 6 characters" /></label>
    <label>Confirm Password<input id="cp" type="password" placeholder="Repeat new password" /></label>
    <button class="btn" id="saveBtn">Reset Password</button>
    </div>
    <script>
    document.getElementById("saveBtn").onclick=async()=>{{
      const np=document.getElementById("np").value;
      const cp=document.getElementById("cp").value;
      const msg=document.getElementById("msg");
      if(np.length<6){{msg.className="msg err";msg.textContent="Min 6 characters";return;}}
      if(np!==cp){{msg.className="msg err";msg.textContent="Passwords don't match";return;}}
      const r=await fetch("/api/reset-password",{{method:"POST",
        headers:{{"Content-Type":"application/json"}},
        body:JSON.stringify({{token:"{token}",new_password:np}})}});
      const d=await r.json();
      if(r.ok&&d.ok){{msg.className="msg ok";msg.textContent="Password reset! Redirecting…";
        setTimeout(()=>window.location.href="/login",1500);}}
      else{{msg.className="msg err";msg.textContent=d.error||"Error";}}
    }};
    </script></body></html>"""
    return HTMLResponse(html)


@app.post("/api/reset-password")
async def api_reset_password(payload: dict):
    token    = str(payload.get("token", ""))
    new_pass = str(payload.get("new_password", ""))
    if len(new_pass) < 6:
        return JSONResponse({"error": "Password min 6 characters."}, status_code=400)
    username = db.reset_token_consume(token)
    if not username:
        return JSONResponse({"error": "Link expired or invalid. Request a new one."}, status_code=400)
    users = _load_users()
    if username not in users:
        return JSONResponse({"error": "User not found."}, status_code=404)
    salt = os.urandom(16)
    users[username]["salt"] = salt.hex()
    users[username]["hash"] = _hash_pw(new_pass, salt)
    _save_users(users)
    return {"ok": True}


# --------------------------------------------------------- FEEDBACK (public)
@app.post("/api/feedback")
async def api_feedback(request: Request, payload: dict):
    name    = str(payload.get("name", "")).strip()
    email   = str(payload.get("email", "")).strip()
    fb_type = str(payload.get("type", "General")).strip()
    message = str(payload.get("message", "")).strip()
    rating  = payload.get("rating")
    if not name or not message:
        return JSONResponse({"error": "Name and message are required."}, status_code=400)
    if not email or not _EMAIL_RE.match(email):
        return JSONResponse({"error": "Valid email is required."}, status_code=400)
    if len(message) < 10:
        return JSONResponse({"error": "Message too short."}, status_code=400)
    # logged-in user hoy to username capture karo (public endpoint, so read token directly)
    u = _read_token(request.cookies.get(COOKIE))
    username = u["username"] if u else ""
    fb_id = db.feedback_create(name, email, fb_type, message, rating, username=username)
    admin_email = emailer._CFG.get("admin_email", "")
    if admin_email:
        emailer.send_feedback_notification(admin_email, name, email, fb_type, message, fb_id, fb_username=username)
    return {"ok": True, "message": "Thank you for your feedback!"}


# --------------------------------------------------------- ADMIN: FEEDBACK TAB
@app.get("/api/admin/feedback")
async def admin_feedback(type: str = None):
    return {"feedback": db.feedback_list(fb_type=type),
            "types": db.feedback_types()}


@app.post("/api/admin/feedback/read")
async def admin_feedback_read(payload: dict):
    db.feedback_mark_read(int(payload.get("id", 0)))
    return {"ok": True}


@app.post("/api/admin/feedback/action")
async def admin_feedback_action(payload: dict):
    new_val = db.feedback_toggle_action(int(payload.get("id", 0)))
    return {"ok": True, "action_done": new_val}


# --------------------------------------------------------- ADMIN: EMAIL CONFIG
@app.get("/api/admin/email-status")
async def admin_email_status():
    cfg = emailer._CFG  # live config (runtime save karyela)
    return {
        "enabled": emailer.is_enabled(),
        "from_address": cfg.get("from_address", ""),
        "admin_email": cfg.get("admin_email", ""),
        "from_name": cfg.get("from_name", ""),
        "app_password_configured": bool(cfg.get("app_password")),
    }


@app.post("/api/admin/email-config")
async def admin_email_config(payload: dict):
    """Admin panel thi Gmail SMTP config save kare — config.yaml touch karva ni jarur nathi."""
    from_address = str(payload.get("from_address", "")).strip()
    app_password = str(payload.get("app_password", "")).strip()
    admin_email  = str(payload.get("admin_email", "")).strip()
    from_name    = str(payload.get("from_name", "SMVS OCR System")).strip()
    if not from_address or "@" not in from_address:
        return JSONResponse({"error": "Valid Gmail address required."}, status_code=400)
    # Multiple admin emails support — comma/semicolon separated. Validate each, normalize to comma-separated.
    if admin_email:
        parts = [e.strip() for e in admin_email.replace(";", ",").split(",") if e.strip()]
        bad = [e for e in parts if not _EMAIL_RE.match(e)]
        if bad:
            return JSONResponse({"error": f"Invalid email(s): {', '.join(bad)}"}, status_code=400)
        admin_email = ", ".join(parts)
    existing = storage.load_email_config(JOBS) or {}
    cfg = {
        "from_address": from_address,
        "app_password": app_password if app_password else existing.get("app_password", ""),
        "admin_email": admin_email,
        "from_name": from_name or "SMVS OCR System",
    }
    if not cfg["app_password"]:
        return JSONResponse({"error": "App Password required."}, status_code=400)
    storage.save_email_config(JOBS, cfg)
    emailer.configure(cfg)
    return {"ok": True}


@app.post("/api/admin/email-test")
async def admin_email_test():
    """Admin ne j test email moklayo che — connection verify karva mate."""
    if not emailer.is_enabled():
        return JSONResponse({"error": "Email not configured yet."}, status_code=400)
    admin_email = emailer._CFG.get("admin_email", "") or emailer._CFG.get("from_address", "")
    if not admin_email:
        return JSONResponse({"error": "No admin email set."}, status_code=400)
    try:
        from emailer import _send
        ok = _send(admin_email, "SMVS OCR — Test Email ✓",
                   "<h2>Email connection is working! 🎉</h2><p>SMVS OCR email system is configured correctly.</p>",
                   "Email connection is working! SMVS OCR email system is configured correctly.")
        if ok:
            return {"ok": True, "sent_to": admin_email}
        return JSONResponse({"error": "Send failed — check Gmail address and App Password."}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=400)





@app.post("/api/ping")
async def api_ping(request: Request):
    """Heartbeat — live presence update only, NO view count (point 10)."""
    vid = request.cookies.get(VISITOR_COOKIE)
    u = _read_token(request.cookies.get(COOKIE))
    resp = JSONResponse({"ok": True})
    if not vid:
        vid = db.new_session_id()
        resp.set_cookie(VISITOR_COOKIE, vid, max_age=30 * 86400, httponly=True, samesite="lax")
    try:
        db.live_touch(vid, "ping", logged_in=bool(u))
    except Exception:
        pass
    return resp


@app.post("/api/track-view")
async def api_track_view(request: Request):
    """Frontend e ek j vaar per browser-tab-session call kare (sessionStorage guard).
    Refresh par frontend call nથi karto etle count nથi vadhto. Fresh URL open par j count thay."""
    vid = request.cookies.get(VISITOR_COOKIE)
    u = _read_token(request.cookies.get(COOKIE))
    page = "app" if u else "login"
    resp = JSONResponse({"ok": True})
    if not vid:
        vid = db.new_session_id()
        resp.set_cookie(VISITOR_COOKIE, vid, max_age=30 * 86400, httponly=True, samesite="lax")
    try:
        db.page_view_record(vid, page, logged_in=bool(u), ip=_client_ip(request), count_view=True)
    except Exception:
        pass
    return resp


@app.get("/api/visitor-count")
async def api_visitor_count():
    """Login page mate public endpoint — total site visits batave (no auth needed)."""
    totals = db.page_view_totals()
    live = db.live_counts()
    return {
        "total_visits": totals["total_views"],
        "online_now": live["total_online"],
    }


app.mount("/static", StaticFiles(directory=STATIC), name="static")

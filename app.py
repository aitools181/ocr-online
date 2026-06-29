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
    """Admin = config; baki users = users.json. Match thay to user dict, nahi to None."""
    if username == ADMIN_USERNAME and ADMIN_PASSWORD and \
            hmac.compare_digest(str(password), ADMIN_PASSWORD):
        return {"username": username, "role": "admin"}
    u = _load_users().get(username)
    if u and _verify_pw(password, u.get("salt", ""), u.get("hash", "")):
        return {"username": username, "role": u.get("role", "user")}
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

_PUBLIC = {"/login", "/api/login", "/health", "/favicon.ico"}


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
    if (path == "/admin" or path.startswith("/api/admin")) and user.get("role") != "admin":
        if path.startswith("/api/"):
            return JSONResponse({"error": "Admin access only"}, status_code=403)
        return RedirectResponse("/")
    request.state.user = user
    return await call_next(request)


def _cleanup():
    now = time.time()
    for d in os.listdir(JOBS):
        p = os.path.join(JOBS, d)
        try:
            if d in ACTIVE_JOBS or d.startswith("_"):   # _fonts vagere skip
                continue
            if os.path.isdir(p) and now - os.path.getmtime(p) > JOB_TTL:
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
def login_page():
    path = os.path.join(STATIC, "login.html")
    if not os.path.isfile(path):
        return HTMLResponse("<h2>Login page not found (static/login.html).</h2>")
    with open(path, encoding="utf-8") as f:
        html = f.read()

    def ver(name):
        p = os.path.join(STATIC, name)
        return str(int(os.path.getmtime(p))) if os.path.isfile(p) else "1"
    html = html.replace("/static/style.css", f"/static/style.css?v={ver('style.css')}")
    return HTMLResponse(html)


@app.post("/api/login")
async def api_login(username: str = Form(...), password: str = Form(...)):
    user = verify_credentials(username.strip(), password)
    if not user:
        return JSONResponse({"error": "Wrong username or password."}, status_code=401)
    resp = JSONResponse({"ok": True, "username": user["username"], "role": user["role"]})
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
    return {"username": u["username"], "role": u["role"]}


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
async def convert(files: list[UploadFile] = File(...), options: str = Form(...)):
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
    default_pdf = bool(opts.get("searchable_pdf", False))   # fallback if per-file absent
    default_langs = opts.get("langs") or ["eng"]
    items_opt = opts.get("items") or []      # per-file: [{langs:[], pages:"", searchable_pdf:bool}]

    job = uuid.uuid4().hex
    job_dir = os.path.join(JOBS, job)
    in_dir = os.path.join(job_dir, "in")
    out_dir = os.path.join(job_dir, "out")
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

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

    def gen():
        import queue as _q
        import threading
        q = _q.Queue()
        produced = []

        def worker():
            ACTIVE_JOBS.add(job)
            q.put({"type": "start", "job": job})
            # Plan: badhi files na page totals (queue + progress bars mate)
            q.put({"type": "plan",
                   "files": [{"name": o, "pages_total": t * (2 if wp else 1)}
                             for (o, _s, _src, _l, _sel, t, wp) in saved]})
            try:
                for (orig, stem, src, langs, sel, total, want_pdf) in saved:
                    lang_str = "+".join(langs) if langs else "eng"
                    units = total * (2 if want_pdf else 1)   # structured + pdf pass
                    q.put({"type": "file_start", "name": orig, "langs": langs,
                           "pages_total": units})
                    t0 = time.time()
                    try:
                        done = [0]

                        def prog(_n=orig, _t=units, _d=done):
                            _d[0] += 1
                            q.put({"type": "progress", "name": _n,
                                   "done": _d[0], "total": _t})

                        items = engine.build_document(
                            src, lang_str, dpi, force_ocr, sel, style=style, psm=psm,
                            progress=prog,
                            log=lambda m, _n=orig: q.put({"type": "log", "name": _n, "msg": m}))
                        text = engine.render_text(items, pagewise)
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
                            engine.write_docx(items, dp, font, pagewise)
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
                    except Exception as e:
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
        jobs.append({
            "job": d,
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
async def admin_users():
    users = _load_users()
    out = [{"username": ADMIN_USERNAME, "role": "admin", "builtin": True}]
    for un, u in sorted(users.items()):
        out.append({"username": un, "role": u.get("role", "user"), "builtin": False})
    return {"users": out}


@app.post("/api/admin/users")
async def admin_create_user(payload: dict):
    username = str(payload.get("username", "")).strip()
    password = str(payload.get("password", ""))
    if not _UNAME_RE.match(username):
        return JSONResponse({"error": "Username: 2-40 chars, letters/digits/._- only."}, status_code=400)
    if len(password) < 4:
        return JSONResponse({"error": "Password must be at least 4 characters."}, status_code=400)
    if username == ADMIN_USERNAME:
        return JSONResponse({"error": "That username is reserved."}, status_code=400)
    users = _load_users()
    if username in users:
        return JSONResponse({"error": "User already exists."}, status_code=400)
    salt = os.urandom(16)
    users[username] = {"salt": salt.hex(), "hash": _hash_pw(password, salt), "role": "user"}
    _save_users(users)
    return {"ok": True, "username": username}


@app.post("/api/admin/users/delete")
async def admin_delete_user(payload: dict):
    username = str(payload.get("username", "")).strip()
    users = _load_users()
    if username in users:
        del users[username]
        _save_users(users)
        return {"ok": True}
    return JSONResponse({"error": "User not found (built-in admin can't be deleted)."}, status_code=400)


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
def index():
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
    return HTMLResponse(html)


@app.get("/health")
def health():
    return {"ok": True, "langs": sorted(engine.installed_languages())}


app.mount("/static", StaticFiles(directory=STATIC), name="static")

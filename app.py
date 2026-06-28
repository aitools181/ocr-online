"""
app.py — FastAPI backend for SMVS OCR.

Endpoints:
  GET  /                      -> web UI
  GET  /api/languages         -> available languages (installed flag)
  POST /api/convert           -> multipart files + options JSON -> results
  GET  /api/download/{job}/{f}-> generated .txt/.docx/.zip
"""

import hmac
import json
import os
import re
import shutil
import time
import uuid
import zipfile
from datetime import datetime, timezone

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import engine

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
os.makedirs(JOBS, exist_ok=True)


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
# Admin page password: config.yaml > env var > (khali = admin band)
ADMIN_PASSWORD = str(_CFG.get("admin_password") or os.environ.get("ADMIN_PASSWORD", "")).strip()
MAX_FILES = int(_CFG.get("max_files", 50))
ACTIVE_JOBS = set()        # atyare process thati jobs - cleanup aane skip kare

# Static files: normally BASE/static, pan jo files repo root ma (static/ vagar)
# hoy to e pan support karo, jethi deploy crash na thay.
STATIC = os.path.join(BASE, "static")
if not os.path.isdir(STATIC) and os.path.isfile(os.path.join(BASE, "index.html")):
    STATIC = BASE
os.makedirs(STATIC, exist_ok=True)

app = FastAPI(title="SMVS OCR")


def _cleanup():
    now = time.time()
    for d in os.listdir(JOBS):
        p = os.path.join(JOBS, d)
        try:
            if d in ACTIVE_JOBS:
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
    default_langs = opts.get("langs") or ["eng"]
    items_opt = opts.get("items") or []      # per-file: [{langs:[], pages:""}]

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
        saved.append((uf.filename, stem, src, langs, pages))

    def gen():
        import queue as _q
        import threading
        q = _q.Queue()
        produced = []

        def worker():
            ACTIVE_JOBS.add(job)
            q.put({"type": "start", "job": job})
            try:
                for (orig, stem, src, langs, pages) in saved:
                    lang_str = "+".join(langs) if langs else "eng"
                    q.put({"type": "file_start", "name": orig, "langs": langs})
                    try:
                        sel = None
                        if pages:
                            sel = engine.parse_range(pages, engine.page_count(src)) or None
                        items = engine.build_document(
                            src, lang_str, dpi, force_ocr, sel,
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
                        q.put({"type": "file_done", "name": orig, "text": text,
                               "counts": counts, "downloads": downloads, "error": None})
                    except Exception as e:
                        q.put({"type": "file_done", "name": orig, "text": "", "counts": {},
                               "downloads": [], "error": str(e)})

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


def _check_admin(pw):
    if not ADMIN_PASSWORD:
        raise HTTPException(503, "Admin password set nathi (ADMIN_PASSWORD env joiye).")
    if not pw or not hmac.compare_digest(str(pw), ADMIN_PASSWORD):
        raise HTTPException(401, "Wrong password.")


@app.post("/api/admin/list")
async def admin_list(payload: dict):
    _check_admin(payload.get("password"))
    jobs = []
    for d in sorted(os.listdir(JOBS)):
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
    _check_admin(payload.get("password"))
    deleted = []
    for j in payload.get("jobs", []):
        d = os.path.join(JOBS, _safe(j))
        if os.path.isdir(d) and _safe(j) not in ACTIVE_JOBS:
            shutil.rmtree(d, ignore_errors=True)
            deleted.append(j)
    return {"ok": True, "deleted": deleted}


@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    path = os.path.join(STATIC, "admin.html")
    if not os.path.isfile(path):
        return HTMLResponse("<h2>Admin page nathi mali (static/admin.html).</h2>", status_code=200)
    with open(path, encoding="utf-8") as f:
        html = f.read()
    p = os.path.join(STATIC, "admin.js")
    ver = str(int(os.path.getmtime(p))) if os.path.isfile(p) else "1"
    return HTMLResponse(html.replace("/static/admin.js", f"/static/admin.js?v={ver}"))


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

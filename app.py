"""
app.py — FastAPI backend for Akshar OCR.

Endpoints:
  GET  /                      -> web UI
  GET  /api/languages         -> available languages (installed flag)
  POST /api/convert           -> multipart files + options JSON -> results
  GET  /api/download/{job}/{f}-> generated .txt/.docx/.zip
"""

import json
import os
import re
import shutil
import time
import uuid
import zipfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

import engine

BASE = os.path.dirname(os.path.abspath(__file__))
JOBS = os.path.join(BASE, "jobs")
os.makedirs(JOBS, exist_ok=True)
JOB_TTL = 60 * 60          # 1 hour
MAX_FILES = 50

# Static files: normally BASE/static, pan jo files repo root ma (static/ vagar)
# hoy to e pan support karo, jethi deploy crash na thay.
STATIC = os.path.join(BASE, "static")
if not os.path.isdir(STATIC) and os.path.isfile(os.path.join(BASE, "index.html")):
    STATIC = BASE
os.makedirs(STATIC, exist_ok=True)

app = FastAPI(title="Akshar OCR")


def _cleanup():
    now = time.time()
    for d in os.listdir(JOBS):
        p = os.path.join(JOBS, d)
        try:
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

    langs = opts.get("langs") or ["eng"]
    lang_str = "+".join(langs)
    dpi = int(opts.get("dpi", 300))
    force_ocr = bool(opts.get("force_ocr", False))
    pagewise = opts.get("layout", "pagewise") == "pagewise"
    want_txt = "txt" in (opts.get("formats") or ["txt", "docx"])
    want_docx = "docx" in (opts.get("formats") or ["txt", "docx"])
    font = opts.get("font") or engine.DEFAULT_DOCX_FONT
    page_specs = opts.get("pages") or {}     # {filename: "1-3,5"}

    job = uuid.uuid4().hex
    job_dir = os.path.join(JOBS, job)
    in_dir = os.path.join(job_dir, "in")
    out_dir = os.path.join(job_dir, "out")
    os.makedirs(in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    results = []
    produced = []
    for uf in files:
        safe = _safe(uf.filename)
        src = os.path.join(in_dir, safe)
        with open(src, "wb") as f:
            f.write(await uf.read())

        stem = os.path.splitext(safe)[0]
        try:
            sel = None
            spec = page_specs.get(uf.filename) or page_specs.get(safe)
            if spec:
                sel = engine.parse_range(spec, engine.page_count(src)) or None

            items = engine.build_document(src, lang_str, dpi, force_ocr, sel)
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

            results.append({"name": uf.filename, "text": text,
                            "counts": counts, "downloads": downloads, "error": None})
        except Exception as e:
            results.append({"name": uf.filename, "text": "", "counts": {},
                            "downloads": [], "error": str(e)})

    zip_name = None
    if len(produced) > 1:
        zip_name = "akshar_output.zip"
        zp = os.path.join(out_dir, zip_name)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            for p in produced:
                z.write(p, os.path.basename(p))

    return {"job": job, "results": results, "zip": zip_name}


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
            "<h2>Akshar OCR</h2><p>UI files (index.html, style.css, app.js) "
            "nathi malya. Repo ma e files <code>static/</code> folder ma honi joiye. "
            "API kaam kare chhe: <a href='/health'>/health</a></p>", status_code=200)
    with open(path, encoding="utf-8") as f:
        return f.read()


@app.get("/health")
def health():
    return {"ok": True, "langs": sorted(engine.installed_languages())}


app.mount("/static", StaticFiles(directory=STATIC), name="static")

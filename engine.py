"""
engine.py — Indian-language OCR / document extraction engine (no GUI).

Handles: PDF (text + scanned), images, docx/doc/odt/rtf, txt.
Produces a structured document model and renders to plain text + .docx
(Hind Vadodara font, complex-script aware). Shared by the web app.
"""

import io
import os
import shutil
import subprocess
import sys

import fitz  # PyMuPDF
import pytesseract
from pytesseract import Output
from PIL import Image, ImageSequence

DEFAULT_DOCX_FONT = "Hind Vadodara"


def _auto_tesseract():
    """Windows par PATH ma tesseract na hoy to default install path try karo.
    Docker/Linux par (jya tesseract PATH ma chhe) aano koi asar nathi."""
    if shutil.which("tesseract"):
        return
    if sys.platform.startswith("win"):
        for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                  r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"):
            if os.path.isfile(p):
                pytesseract.pytesseract.tesseract_cmd = p
                td = os.path.join(os.path.dirname(p), "tessdata")
                if os.path.isdir(td):
                    os.environ.setdefault("TESSDATA_PREFIX", td)
                return


_auto_tesseract()

# (display, code, sample glyph) — glyph UI chips mate
LANGUAGES = [
    ("English", "eng", "A"), ("Gujarati", "guj", "અ"), ("Hindi", "hin", "अ"),
    ("Sanskrit", "san", "ॐ"), ("Marathi", "mar", "म"), ("Bengali", "ben", "অ"),
    ("Tamil", "tam", "அ"), ("Telugu", "tel", "అ"), ("Kannada", "kan", "ಕ"),
    ("Malayalam", "mal", "അ"), ("Punjabi", "pan", "ਪ"), ("Odia", "ori", "ଅ"),
    ("Assamese", "asm", "অ"), ("Urdu", "urd", "ا"), ("Nepali", "nep", "न"),
]

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"}
PDF_EXTS = {".pdf"}
DOCX_EXTS = {".docx"}
OFFICE_EXTS = {".doc", ".odt", ".rtf"}
TEXT_EXTS = {".txt", ".md", ".csv", ".log"}

SCRIPT_RANGES = {
    "eng": [(0x41, 0x5A), (0x61, 0x7A)],
    "guj": [(0x0A80, 0x0AFF)],
    "dev": [(0x0900, 0x097F)],
    "ben": [(0x0980, 0x09FF)],
    "guru": [(0x0A00, 0x0A7F)],
    "ori": [(0x0B00, 0x0B7F)],
    "tam": [(0x0B80, 0x0BFF)],
    "tel": [(0x0C00, 0x0C7F)],
    "kan": [(0x0C80, 0x0CFF)],
    "mal": [(0x0D00, 0x0D7F)],
    "arab": [(0x0600, 0x06FF), (0x0750, 0x077F)],
}
LANG_TO_SCRIPT = {
    "eng": "eng", "guj": "guj", "hin": "dev", "san": "dev", "mar": "dev",
    "nep": "dev", "ben": "ben", "asm": "ben", "pan": "guru", "ori": "ori",
    "tam": "tam", "tel": "tel", "kan": "kan", "mal": "mal", "urd": "arab",
}
SCRIPT_LABEL = {
    "eng": "eng", "guj": "guj", "dev": "hin/san", "ben": "ben", "guru": "pan",
    "ori": "ori", "tam": "tam", "tel": "tel", "kan": "kan", "mal": "mal", "arab": "urd",
}


# ---------------------------------------------------------------- tesseract
def installed_languages():
    try:
        return set(pytesseract.get_languages(config=""))
    except Exception:
        return set()


def find_soffice():
    for c in ("soffice", "libreoffice"):
        p = shutil.which(c)
        if p:
            return p
    return None


# ---------------------------------------------------------------- model
def _run(text, bold=False, italic=False, size=None):
    return {"text": text, "bold": bold, "italic": italic, "size": size}


def _break():
    return {"text": "\n", "bold": False, "italic": False, "size": None, "brk": True}


def _paragraphize(paras):
    """Ek paragraph ni andar na line-breaks ne space-join ma badle (paragraph-based output).
    Line-end hyphen hoy to word jodi de. Bold/italic runs jalvai rahe."""
    out = []
    for para in paras:
        merged = []
        for run in para:
            if run.get("brk"):
                if merged:
                    prev = merged[-1]
                    pt = prev.get("text", "")
                    if len(pt) >= 2 and pt.endswith("-") and pt[-2].isalpha():
                        prev["text"] = pt[:-1]              # hyphenated word jodo
                    elif pt and not pt.endswith(" "):
                        merged.append(_run(" "))            # line break -> space
                continue
            merged.append(run)
        # trailing space cleanup
        while merged and merged[-1].get("text", "") == " ":
            merged.pop()
        if merged:
            out.append(merged)
    return out


def looks_like_real_text(text):
    return len("".join(text.split())) >= 15


def render_page_image(page, dpi):
    pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72.0, dpi / 72.0), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")


def extract_pdf_text_page(page):
    data = page.get_text("dict")
    paras = []
    for block in data.get("blocks", []):
        if block.get("type", 1) != 0:
            continue
        runs = []
        lines = block.get("lines", [])
        for li, line in enumerate(lines):
            for span in line.get("spans", []):
                t = span.get("text", "")
                if not t:
                    continue
                flags = span.get("flags", 0)
                font = span.get("font", "").lower()
                bold = bool(flags & 16) or "bold" in font or "black" in font or "semibold" in font
                italic = bool(flags & 2) or "italic" in font or "oblique" in font
                runs.append(_run(t, bold, italic, round(span.get("size", 0), 1) or None))
            if li < len(lines) - 1:
                runs.append(_break())
        if runs:
            paras.append(runs)
    return paras


def ocr_image_structured(pil_img, lang):
    try:
        data = pytesseract.image_to_data(pil_img, lang=lang, config="--psm 3",
                                         output_type=Output.DICT)
    except Exception:
        txt = pytesseract.image_to_string(pil_img, lang=lang, config="--psm 3")
        return [[_run(line)] for line in txt.splitlines() if line.strip()] or [[_run("")]]

    grouped = {}
    n = len(data["text"])
    for i in range(n):
        if data["level"][i] != 5:
            continue
        word = data["text"][i]
        if not word or not word.strip():
            continue
        key = (data["block_num"][i], data["par_num"][i])
        grouped.setdefault(key, {}).setdefault(data["line_num"][i], []).append(word)

    paras = []
    for key in sorted(grouped.keys()):
        lines = grouped[key]
        runs = []
        ordered = sorted(lines.keys())
        for idx, ln in enumerate(ordered):
            runs.append(_run(" ".join(lines[ln])))
            if idx < len(ordered) - 1:
                runs.append(_break())
        if runs:
            paras.append(runs)
    return paras or [[_run("")]]


def extract_docx_file(path):
    from docx import Document as Docx
    doc = Docx(path)
    paras = []
    for p in doc.paragraphs:
        runs = []
        for r in p.runs:
            if not r.text:
                continue
            size = r.font.size.pt if r.font.size else None
            runs.append(_run(r.text, bool(r.bold), bool(r.italic), size))
        if not runs and p.text.strip():
            runs = [_run(p.text)]
        if runs:
            paras.append(runs)
    return paras


def extract_text_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        text = f.read()
    return [[_run(line)] for line in text.split("\n")]


def libreoffice_to_docx(path, tmpdir):
    soffice = find_soffice()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) joiye .doc/.odt/.rtf mate.")
    os.makedirs(tmpdir, exist_ok=True)
    subprocess.run([soffice, "--headless", "--convert-to", "docx",
                    "--outdir", tmpdir, path], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    out = os.path.join(tmpdir, os.path.splitext(os.path.basename(path))[0] + ".docx")
    if not os.path.isfile(out):
        raise RuntimeError("LibreOffice conversion failed.")
    return out


def page_count(path):
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in PDF_EXTS:
            d = fitz.open(path); n = d.page_count; d.close(); return n
        if ext in (".tif", ".tiff", ".gif"):
            with Image.open(path) as im:
                return getattr(im, "n_frames", 1)
    except Exception:
        pass
    return 1


def parse_range(spec, maxp):
    pages = set()
    for part in str(spec).replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                for x in range(int(a), int(b) + 1):
                    if 1 <= x <= maxp:
                        pages.add(x)
        elif part.isdigit():
            x = int(part)
            if 1 <= x <= maxp:
                pages.add(x)
    return sorted(pages)


def _counts_line(paras, lang_codes):
    c = count_scripts([("", paras)], lang_codes)
    return " ".join(f"{k}={v}" for k, v in c.items())


def build_document(path, lang, dpi, force_ocr, selected_pages, progress=None, log=None):
    """Return list[(label, paras)]. selected_pages: 1-based list or None=all.
    log(msg): optional per-page live message callback."""
    ext = os.path.splitext(path)[1].lower()
    lang_codes = lang.split("+")
    pages = []

    def tick():
        if progress:
            progress()

    def emit(label, mode, paras):
        if log:
            log(f"{label}  [{mode}]  {_counts_line(paras, lang_codes)}")

    if ext in PDF_EXTS:
        doc = fitz.open(path)
        total = doc.page_count
        todo = selected_pages or list(range(1, total + 1))
        for pno in todo:
            i = pno - 1
            if i < 0 or i >= total:
                continue
            page = doc[i]
            raw = page.get_text("text")
            if force_ocr or not looks_like_real_text(raw):
                paras = ocr_image_structured(render_page_image(page, dpi), lang)
                mode = "OCR"
            else:
                paras = extract_pdf_text_page(page)
                mode = "text"
            paras = _paragraphize(paras)
            pages.append((f"Page {pno}", paras))
            emit(f"Page {pno}", mode, paras)
            tick()
        doc.close()

    elif ext in IMAGE_EXTS:
        frames = []
        with Image.open(path) as im:
            for fr in ImageSequence.Iterator(im):
                frames.append(fr.convert("L").copy())
        todo = selected_pages or list(range(1, len(frames) + 1))
        for pno in todo:
            if 1 <= pno <= len(frames):
                paras = _paragraphize(ocr_image_structured(frames[pno - 1], lang))
                pages.append((f"Page {pno}", paras))
                emit(f"Page {pno}", "OCR", paras)
                tick()

    elif ext in DOCX_EXTS:
        paras = extract_docx_file(path)
        pages = [("Document", paras)]; emit("Document", "read", paras); tick()

    elif ext in OFFICE_EXTS:
        conv = libreoffice_to_docx(path, os.path.join(os.path.dirname(path), "_conv"))
        paras = extract_docx_file(conv)
        pages = [("Document", paras)]; emit("Document", "read", paras); tick()

    elif ext in TEXT_EXTS:
        paras = extract_text_file(path)
        pages = [("Document", paras)]; emit("Document", "read", paras); tick()

    else:
        try:
            with Image.open(path) as im:
                paras = ocr_image_structured(im.convert("L"), lang)
            pages = [("Page 1", paras)]; emit("Page 1", "OCR", paras)
        except Exception:
            paras = extract_text_file(path)
            pages = [("Document", paras)]; emit("Document", "read", paras)
        tick()

    return pages


# ---------------------------------------------------------------- render
def render_text(items, pagewise):
    out = []
    for idx, (label, page) in enumerate(items):
        if pagewise:
            if idx > 0:
                out.append("")
            out.append(f"===== {label} =====")
        para_texts = ["".join(r["text"] for r in para) for para in page]
        out.append("\n\n".join(para_texts))
    return "\n".join(out).strip() + "\n"


def count_scripts(items, lang_codes):
    text = " ".join(r["text"] for _, page in items for para in page for r in para)
    scripts = []
    for c in lang_codes:
        s = LANG_TO_SCRIPT.get(c)
        if s and s not in scripts:
            scripts.append(s)
    if not scripts:
        scripts = ["eng"]
    counts = {s: 0 for s in scripts}
    for ch in text:
        o = ord(ch)
        for s in scripts:
            for lo, hi in SCRIPT_RANGES[s]:
                if lo <= o <= hi:
                    counts[s] += 1
                    break
    return {SCRIPT_LABEL.get(s, s): n for s, n in counts.items()}


def _set_run_font(run, name, size_pt, bold, italic):
    from docx.shared import Pt
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    run.bold = bold
    run.italic = italic
    if size_pt:
        run.font.size = Pt(size_pt)
    run.font.name = name
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), name)


def write_docx(items, out_path, font_name, pagewise):
    from docx import Document as Docx
    from docx.shared import Pt, Mm
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement

    doc = Docx()
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Mm(210), Mm(297)
    normal = doc.styles["Normal"]
    normal.font.name = font_name
    normal.font.size = Pt(12)
    rpr = normal.element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.insert(0, rfonts)
    for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rfonts.set(qn(attr), font_name)

    for idx, (label, page) in enumerate(items):
        if pagewise and idx > 0:
            doc.add_page_break()
        if pagewise:
            h = doc.add_paragraph()
            _set_run_font(h.add_run(label), font_name, 13, True, False)
        for para in page:
            p = doc.add_paragraph()
            for r in para:
                if r.get("brk"):
                    p.add_run().add_break()
                    continue
                _set_run_font(p.add_run(r["text"]), font_name,
                              r.get("size") or 12, r.get("bold", False),
                              r.get("italic", False))
    doc.save(out_path)

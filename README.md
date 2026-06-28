# SMVS OCR

Self-hosted web app to convert **Indian-language documents & images** into editable
**text and Word (.docx)**. Built for SMVS's Coolify/Docker stack — Dockerfile ma badhi
Tesseract language packs install thaay, etle deploy karyu ke turant chale.

Supports Gujarati, Hindi, Sanskrit, Marathi, Bengali, Tamil, Telugu, Kannada,
Malayalam, Punjabi, Odia, Assamese, Urdu, Nepali, English — **combination** select
kari shakay (mixed-language file mate sahi output).

## Features
- Upload **multiple files** (drag-drop): PDF, images (PNG/JPG/TIFF/BMP/WEBP/GIF),
  Word (.docx/.doc), ODT, RTF, text.
- **Per-file language** ane **per-file page selection** (All / specific page checkboxes / `1-3,5,8`).
- "Set Language For All File" + **Apply To All** (badhi file ek saathe).
- **Auto-detect** per page: text-based PDF → direct extract; scanned → Tesseract OCR.
- **Paragraph-based output** (line-to-line nahi) — text ane Word banne ma.
- Output **.txt + .docx** (Hind Vadodara font, complex-script aware), per-file + **.zip**.
- **Live processing log**, **upload progress bars** (per-file + total).
- **Output preview** (editable) + per-file tabs + Copy + **View popup** (moto view + download).
- **Toast notifications** (bottom-right) badhi actions mate.
- **Clear All** ane tab-close par data server par thi turant delete.

## Data & privacy
- **Uploaded files** convert puro thaya j **turant delete** thaay.
- **Converted output** (.txt/.docx/.zip) **24 kalak** sudhi rahe (config thi badli shakay),
  jethi user modu aave to pan download kari sake.
- **Clear All** athva **tab/window close** → output pan turant delete.
- Backstop: dareki request par juni jobs auto-cleanup (24h).
- **Admin page** `/admin` (password-protected) — leftover jobs joi/delete kari shakay.

## Repo structure
```
.
├── app.py               # FastAPI backend (endpoints + admin + cleanup)
├── engine.py            # OCR / extraction / paragraph render / docx engine
├── static/
│   ├── index.html  app.js  style.css     # main UI
│   ├── admin.html  admin.js              # /admin page
│   └── logo.png  logo-white.png
├── requirements.txt
├── Dockerfile           # installs Tesseract + all Indian lang packs
├── docker-compose.yaml
├── config.example.yaml  # copy -> config.yaml (admin password ahiya)
├── .dockerignore  .gitignore  LICENSE
└── README.md
```
> `config.yaml`, `push_to_github.bat`, `run_local.bat` git ma **push nathi thata** (.gitignore).

## Configuration (`config.yaml`)
`config.example.yaml` ne `config.yaml` naam thi copy karo ane set karo:
```yaml
admin_password: "Your-Strong-Password"   # /admin mate
output_retention_hours: 24               # output ketla kalak rahe
max_files: 50
```
Coolify par YAML mount na karvu hoy to `ADMIN_PASSWORD` **env var** pan chale
(priority: config.yaml > env var).

## Run locally (Docker)
```bash
docker compose up --build
# open http://localhost:8000
```
Or plain Docker:
```bash
docker build -t smvs-ocr .
docker run -p 8000:8000 -e ADMIN_PASSWORD=secret smvs-ocr
```

## Deploy on Coolify
1. **+ New → Application → from Git repository** (aa repo).
2. Build pack: **Dockerfile** (auto-detect).
3. **Port: 8000**.
4. **Domain** add (e.g. `ocr.divyajivan.com`) — Traefik + SSL.
5. **Env var** `ADMIN_PASSWORD` set karo (athva `/app/config.yaml` mount karo).
6. **Persistent storage** mount `/app/jobs` (24h output restart ma jalvai rahe).
7. Deploy. (Pehlo build dheemo — lang packs + LibreOffice.)

Lean image (no .doc/.odt/.rtf):
```bash
docker build --build-arg WITH_LIBREOFFICE=0 -t smvs-ocr .
```

## API
| Method | Path | Su kare |
|--------|------|---------|
| GET | `/api/languages` | available languages + installed flag |
| POST | `/api/convert` | multipart `files[]` + `options` (JSON) → **streaming** NDJSON results + live log |
| POST | `/api/pagecount` | single file → page count (page checkboxes mate) |
| GET | `/api/download/{job}/{file}` | generated .txt/.docx/.zip |
| POST | `/api/clear/{job}` | job nu server data delete (Clear All / tab-close) |
| POST | `/api/admin/list` | (password) stored jobs list |
| POST | `/api/admin/delete` | (password) selected jobs delete |
| GET | `/admin` | admin page |
| GET | `/health` | status + installed langs |

`options` JSON: `dpi`, `force_ocr`, `layout` (pagewise/continuous), `formats[]`
(txt/docx), `font`, `langs[]` (default), `items[]` (per-file `{langs[], pages}`).

## Language packs
Image ma packs: eng, guj, hin, san, mar, ben, asm, tam, tel, kan, mal, pan, ori,
urd, nep. Biju joiye to `Dockerfile` ma `tesseract-ocr-<code>` add karo.
UI fakt installed languages batave chhe.

## Limitations
- Scanned OCR ma **bold/italic detect nathi thatu** (Tesseract LSTM limitation);
  paragraph/line structure jaru rahe. Text-based PDF/Word ma full formatting.
- OCR accuracy scan quality par adhaar — 300 DPI, clean, straight → best.
- Hind Vadodara font Word ma set thaay; viewing PC par e font hovo joiye.

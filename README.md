# Akshar OCR

Self-hosted web app to convert **Indian-language documents & images** into editable
**text and Word (.docx)**. Built for SMVS's Coolify/Docker stack — Dockerfile ma badhi
Tesseract language packs install thaay, etle deploy karyu ke turant chale.

Supports Gujarati, Hindi, Sanskrit, Marathi, Bengali, Tamil, Telugu, Kannada,
Malayalam, Punjabi, Odia, Assamese, Urdu, Nepali, English — **combination** select
kari shakay (mixed-language file mate sahi output).

## Features
- Upload **multiple files** (drag-drop): PDF, images (PNG/JPG/TIFF/BMP/WEBP/GIF),
  Word (.docx/.doc), ODT, RTF, text.
- **Auto-detect** per page: text-based PDF → direct extract; scanned → Tesseract OCR.
- **Per-file page range** (e.g. `1-3,5,8`) for PDFs / multipage images.
- **Formatting**: text-based PDF/Word ma bold/italic/size; OCR ma paragraph/line structure.
- Output **.txt + .docx** (Hind Vadodara font, complex-script aware), per-file + **.zip**.
- **In-browser preview** + copy; per-file script character counts.
- **Layout**: page-wise (separation) or continuous.

## Repo structure
```
.
├── app.py              # FastAPI backend (endpoints)
├── engine.py           # OCR / extraction / render / docx engine
├── static/             # web UI (index.html, style.css, app.js)
├── requirements.txt
├── Dockerfile          # installs Tesseract + all Indian lang packs
├── docker-compose.yml
├── .dockerignore / .gitignore / LICENSE
└── README.md
```

## Run locally (Docker)
```bash
docker compose up --build
# open http://localhost:8000
```
Or plain Docker:
```bash
docker build -t akshar-ocr .
docker run -p 8000:8000 akshar-ocr
```

## Deploy on Coolify
1. **+ New Resource → Application → from Git repository** (aa repo).
2. Build pack: **Dockerfile** (auto-detect thashe).
3. **Port: 8000** set karo.
4. Domain add karo (e.g. `ocr.divyajivan.com`). Coolify Traefik + SSL handle karshe.
5. Deploy. (Pehlo build dheemo — language packs + LibreOffice download thaay.)

> Manual Traefik vaaprta hov to `docker-compose.yml` ma labels uncomment karo.

## Run without Docker (dev)
```bash
# Ubuntu: tesseract + jaroori lang packs
sudo apt install -y tesseract-ocr tesseract-ocr-guj tesseract-ocr-hin \
     tesseract-ocr-san tesseract-ocr-eng   # + bija joiye te
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

## Language packs
Image ma aa packs install chhe: eng, guj, hin, san, mar, ben, asm, tam, tel,
kan, mal, pan, ori, urd, nep. Biju joiye to `Dockerfile` ma `tesseract-ocr-<code>`
add karo. UI fakt installed languages enable batave chhe (`GET /api/languages`).

## Image size note
`Dockerfile` default ma **LibreOffice** include kare chhe (.doc/.odt/.rtf mate).
Lean image joiye (no .doc support) to build:
```bash
docker build --build-arg WITH_LIBREOFFICE=0 -t akshar-ocr .
```

## API
| Method | Path | Su kare |
|--------|------|---------|
| GET | `/api/languages` | available languages + installed flag |
| POST | `/api/convert` | multipart `files[]` + `options` (JSON) → results |
| GET | `/api/download/{job}/{file}` | generated .txt/.docx/.zip |
| GET | `/health` | status + installed langs |

`options` JSON: `langs[]`, `dpi`, `force_ocr`, `layout` (pagewise/continuous),
`formats[]` (txt/docx), `font`, `pages` ({filename: "1-3,5"}).

Jobs `jobs/` ma store thaay ne **1 kalak pachhi auto-delete** thaay.

## Limitations
- Scanned OCR ma **bold/italic detect nathi thatu** (Tesseract LSTM limitation);
  paragraph/line structure jaru rahe. Text-based PDF/Word ma full formatting.
- OCR accuracy scan quality par adhaar — 300 DPI, clean, straight → best.
- Hind Vadodara font Word ma set thaay; render mate e font viewing PC par hovo joiye.

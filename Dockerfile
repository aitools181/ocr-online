FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

# LibreOffice (.doc/.odt/.rtf support). Set to 0 for a leaner image.
ARG WITH_LIBREOFFICE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-eng tesseract-ocr-guj tesseract-ocr-hin tesseract-ocr-san \
        tesseract-ocr-mar tesseract-ocr-ben tesseract-ocr-asm tesseract-ocr-tam \
        tesseract-ocr-tel tesseract-ocr-kan tesseract-ocr-mal tesseract-ocr-pan \
        tesseract-ocr-ori tesseract-ocr-urd tesseract-ocr-nep \
    && if [ "$WITH_LIBREOFFICE" = "1" ]; then \
         apt-get install -y --no-install-recommends libreoffice-writer; \
       fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

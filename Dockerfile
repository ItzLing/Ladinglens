FROM python:3.12-slim

# pytesseract is only a wrapper -- without the tesseract binary OCR fails at
# runtime in the container while working fine on a developer machine.
# poppler-utils backs the PDF-to-image step the OCR ladder falls back to.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr poppler-utils \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

# Dependencies first: this layer is cached unless requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# data/loader.py is imported at startup, so it ships. The dataset itself does
# not -- POST /process takes its documents in the request body, which is what
# keeps organizer material out of this image.
COPY app/ ./app/
COPY data/loader.py ./data/loader.py

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

# Hosts inject $PORT; default to 8000 for a plain `docker run`.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

# syntax=docker/dockerfile:1
# Use Bookworm variant for latest Debian security patches.
FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get upgrade -y --no-install-recommends \
  && apt-get install -y --no-install-recommends \
    curl \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libreoffice-writer \
    libreoffice-common \
  && rm -rf /var/lib/apt/lists/* \
  && pip install uv --no-cache-dir

COPY requirements.txt .
# Install CPU-only torch first to avoid the 2GB CUDA wheel from PyPI.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system torch torchvision --index-url https://download.pytorch.org/whl/cpu
# Pin headless OpenCV before unstructured[pdf] can pull in the GUI variant,
# which requires libGL at runtime and fails in slim containers.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system opencv-python-headless
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system -r requirements.txt

RUN python -m spacy download en_core_web_lg

COPY . .

RUN mkdir -p storage/pdfs

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV ENVIRONMENT=docker
ENV STORAGE_DIR=/app/storage

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

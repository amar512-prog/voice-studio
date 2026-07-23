FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Debian bookworm (GCC 12) is pinned because OpenFst 1.8.3 does not compile on
# the newer GCC in current `python:3.12-slim` (trixie).
FROM python:3.12-slim-bookworm AS app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/app/data \
    STATIC_DIR=/app/frontend_dist

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       ffmpeg build-essential wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# pynini (via WeTextProcessing) is source-only and links against a matching
# OpenFst built with the GRM extensions; build it before installing Python deps.
ARG OPENFST_VERSION=1.8.3
RUN wget -q "https://www.openfst.org/twiki/pub/FST/FstDownload/openfst-${OPENFST_VERSION}.tar.gz" \
    && tar xzf "openfst-${OPENFST_VERSION}.tar.gz" \
    && cd "openfst-${OPENFST_VERSION}" \
    && ./configure --enable-far --enable-mpdt --enable-pdt --enable-grm \
    && make -j"$(nproc)" \
    && make install \
    && ldconfig \
    && cd .. \
    && rm -rf "openfst-${OPENFST_VERSION}" "openfst-${OPENFST_VERSION}.tar.gz"

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY --from=frontend-build /frontend/dist ./frontend_dist

RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

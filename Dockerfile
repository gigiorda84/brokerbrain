# ---- Builder stage ----
FROM python:3.12-slim-bookworm AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libjpeg62-turbo-dev \
    libpng-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build

# Copy minimum files for hatchling to resolve deps
COPY pyproject.toml .
COPY src/__init__.py src/__init__.py

RUN pip install --no-cache-dir .

# ---- Runtime stage ----
FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libjpeg62-turbo \
    libpng16-16 \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY src/ src/
COPY data/ data/
COPY alembic/ alembic/
COPY alembic.ini .
COPY scripts/entrypoint.sh scripts/entrypoint.sh

RUN chmod +x scripts/entrypoint.sh \
    && mkdir -p /app/uploads \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

ENTRYPOINT ["scripts/entrypoint.sh"]
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]

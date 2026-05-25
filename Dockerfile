FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .
# Stamp the deployed commit SHA into /app/COMMIT_SHA so future audits
# can run `railway ssh --service <svc> "cat /app/COMMIT_SHA"`. The
# Railway CLI excludes .git from `railway up` uploads, so we can't
# read the SHA inside the build — scripts/deploy.sh writes it to a
# COMMIT_SHA file before invoking `railway up`. Falls back to "unknown"
# when deployed via plain `railway up` (no wrapper).
RUN if [ -f COMMIT_SHA ]; then \
        mv COMMIT_SHA /app/COMMIT_SHA; \
    else \
        echo "unknown" > /app/COMMIT_SHA; \
    fi
RUN pip install --no-cache-dir -e . --no-deps

EXPOSE ${PORT:-5000}

# Run migrations then start gunicorn
CMD ["sh", "-c", "python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind 0.0.0.0:${PORT:-5000}"]

FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    ffmpeg \
    tesseract-ocr \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .
# Stamp the deployed commit SHA so future code-parity audits can run
# `railway ssh --service docket-web "cat /app/COMMIT_SHA"` instead of
# doing file-hash forensics against git history. Falls back to
# "unknown" if .git isn't in the build context (defensive — `railway
# up` includes it by default). Strip .git after so the runtime image
# stays lean.
RUN if [ -d .git ]; then \
        git config --global --add safe.directory /app && \
        git rev-parse HEAD > /app/COMMIT_SHA; \
    else \
        echo "unknown" > /app/COMMIT_SHA; \
    fi && \
    rm -rf .git
RUN pip install --no-cache-dir -e . --no-deps

EXPOSE ${PORT:-5000}

# Run migrations then start gunicorn
CMD ["sh", "-c", "python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind 0.0.0.0:${PORT:-5000}"]

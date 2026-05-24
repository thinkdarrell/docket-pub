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
RUN pip install --no-cache-dir -e . --no-deps

EXPOSE ${PORT:-5000}

# Run migrations then start gunicorn
CMD ["sh", "-c", "python -m docket.migrations.runner && gunicorn 'docket.web:create_app()' --bind 0.0.0.0:${PORT:-5000}"]

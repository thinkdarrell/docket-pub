web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --timeout 120
worker: python -m docket.worker.scheduler

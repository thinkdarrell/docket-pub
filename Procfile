web: python -m docket.migrations.runner && exec gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000} --workers 1 --threads 4 --env "PGOPTIONS=-c statement_timeout=30000" --env PGCONNECT_TIMEOUT=10 --timeout 120
worker: python -m docket.worker.scheduler

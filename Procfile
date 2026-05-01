web: python -m docket.migrations.runner && gunicorn "docket.web:create_app()" --bind 0.0.0.0:${PORT:-5000}

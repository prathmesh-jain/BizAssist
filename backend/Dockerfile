FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

# Attachments and logs are written under /app; everything else stays root-owned.
RUN useradd --create-home --uid 1000 app \
    && mkdir -p tmp logs \
    && chown -R app:app tmp logs
USER app

EXPOSE 8000

# The app never creates its own tables, so bring the schema up to date first; a failed migration stops the start.
# Assumes one API container: several starting together would race on migrations.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]

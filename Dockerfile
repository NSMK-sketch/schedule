FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE=/data/schedule.db \
    SCHEDULE_START_BOT=1

WORKDIR /app

RUN useradd --create-home --uid 1000 --shell /bin/sh app \
    && mkdir -p /data /opt/seed \
    && chown app:app /data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app app ./app
COPY --chown=app:app static ./static
COPY --chown=app:app templates ./templates
COPY --chown=app:app wsgi.py run.py ./
COPY instance/schedule.seed.db /opt/seed/schedule.db
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN python -c "from app.database import remove_default_credentials_from_path; remove_default_credentials_from_path('/opt/seed/schedule.db')" \
    && chmod 755 /docker-entrypoint.sh \
    && chown app:app /opt/seed/schedule.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health')"

ENTRYPOINT ["/docker-entrypoint.sh"]

# EcoTrack backend.
#
# Python 3.12 to match .python-version; see AUDIT.md Q1 for why not 3.13.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Build deps for psycopg, removed again in the same layer to keep the image small.
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

# Requirements first, so a code change does not invalidate the dependency layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Non-root: the container has no business running as root.
RUN useradd --create-home --shell /bin/false ecotrack \
 && chown -R ecotrack:ecotrack /app
USER ecotrack

EXPOSE 8000

# The health endpoint from Phase 2 doubles as the container probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--access-logfile", "-"]

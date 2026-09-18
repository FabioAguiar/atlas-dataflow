FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY api/pyproject.toml ./api/pyproject.toml
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/api/pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"

COPY api/*.py ./api/
COPY registry/ ./registry/
COPY runtime/ ./runtime/
COPY contracts/ ./contracts/
COPY releases/ ./releases/
COPY publisher/*.py ./publisher/
COPY publisher/release-candidate.operational-note.json ./publisher/release-candidate.operational-note.json

RUN groupadd --gid 10001 atlas \
    && useradd --uid 10001 --gid atlas --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin atlas \
    && chown -R atlas:atlas /app

WORKDIR /app/api

EXPOSE 8000

USER atlas

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

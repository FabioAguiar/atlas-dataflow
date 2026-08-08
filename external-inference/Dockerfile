FROM python:3.11.15-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY external-inference/pyproject.toml ./external-inference/pyproject.toml
RUN python -c "import subprocess, sys, tomllib; deps = tomllib.load(open('/app/external-inference/pyproject.toml', 'rb'))['project']['dependencies']; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--no-cache-dir', *deps])"

COPY external-inference/*.py ./external-inference/
COPY external-inference/contracts/ ./external-inference/contracts/
COPY releases/ ./releases/

WORKDIR /app/external-inference

EXPOSE 8100

CMD ["uvicorn", "service_app:app", "--host", "0.0.0.0", "--port", "8100", "--no-access-log"]

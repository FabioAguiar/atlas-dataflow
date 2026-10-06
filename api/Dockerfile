# Production base: readable tag plus the immutable multi-platform index digest
# (linux/amd64 and linux/arm64). Updating the digest is a deliberate, reviewed
# repository change (docs/operations/production-build-provenance.md).
FROM python:3.12-slim@sha256:02108f5d322dd89f1c9e552442c25acb0543dfdbc455693a5599624f20d9155d

# OCI source/revision metadata. The revision is supplied only by the canonical
# builder (scripts/build-production-images.sh), which derives it from the clean
# Git HEAD; no clock-derived "created" label is added.
ARG ATLAS_SOURCE_REVISION=""
LABEL org.opencontainers.image.source="https://github.com/FabioAguiar/atlas-dataflow" \
      org.opencontainers.image.revision="${ATLAS_SOURCE_REVISION}" \
      org.opencontainers.image.title="atlas-dataflow-api"

# Set by the canonical builder from the selected commit timestamp; used only to
# keep generated account metadata independent of the build clock.
ARG SOURCE_DATE_EPOCH

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Production dependencies come only from the committed, hash-locked closure of
# api/pyproject.toml; pip never resolves the pyproject ranges here. Wheels only
# (no sdist builds), every artifact hash enforced, no bytecode at install time
# (pip would embed the build clock); bytecode is then compiled in the
# deterministic checked-hash mode.
COPY api/requirements-production.lock.txt ./api/requirements-production.lock.txt
RUN python -m pip install --no-cache-dir --no-compile --require-hashes --only-binary=:all: \
        -r ./api/requirements-production.lock.txt \
    && python -m pip check \
    && python -m compileall -q --invalidation-mode checked-hash /usr/local/lib/python3.12/site-packages

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

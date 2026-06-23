#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ATLAS_PREVIEW_PORT="${ATLAS_PREVIEW_PORT:-15174}"
API_URL="${API_URL:-http://127.0.0.1:${ATLAS_PREVIEW_PORT}/api/health}"
WEB_URL="${WEB_URL:-http://127.0.0.1:${ATLAS_PREVIEW_PORT}/}"

cd "$ROOT_DIR"

compose() {
  if docker compose version >/dev/null 2>&1; then
    docker compose "$@"
  else
    docker-compose "$@"
  fi
}

cleanup() {
  if [ "${KEEP_M2_CONTAINERS:-0}" != "1" ]; then
    compose down --remove-orphans >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

wait_for_http() {
  local label="$1"
  local url="$2"
  local expected="$3"
  local deadline=$((SECONDS + 60))

  while [ "$SECONDS" -lt "$deadline" ]; do
    if body="$(curl --fail --silent --show-error "$url" 2>/dev/null)"; then
      if [ -z "$expected" ] || printf '%s' "$body" | grep -Fq "$expected"; then
        printf 'OK %s: %s\n' "$label" "$url"
        return 0
      fi
    fi
    sleep 2
  done

  printf 'FAIL %s did not return the expected response at %s\n' "$label" "$url" >&2
  return 1
}

compose up --build -d api web

wait_for_http "API healthcheck" "$API_URL" '"status":"ok"'
wait_for_http "web root" "$WEB_URL" "Atlas DataFlow"

printf 'M2 local validation completed.\n'

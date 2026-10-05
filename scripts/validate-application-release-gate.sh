#!/usr/bin/env bash
# Atlas DataFlow application release gate (Project Spec S0301).
#
# One repository-owned entrypoint for the local and CI release gate. It stops
# at the first failing mandatory check and never skips one: a missing command
# is a failure, not a reason to continue. It never deploys, never touches
# production, Supabase, backups or secrets, never rewrites Git state and never
# deletes files itself (`npm ci` alone replaces web/node_modules).
#
# Prerequisites (see docs/operations/application-release-gate.md):
#   - a real Git checkout, run as a non-root user;
#   - an active Python 3.12 virtual environment installed from
#     requirements-test.lock.txt;
#   - Node.js 22 with npm.
#
# Usage: scripts/validate-application-release-gate.sh
set -euo pipefail

readonly REQUIRED_PYTHON_MINOR="3.12"
readonly REQUIRED_NODE_MAJOR="22"
readonly PYTHON_LOCK="requirements-test.lock.txt"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly ROOT_DIR
cd "${ROOT_DIR}"

PYTHON_BIN="${PYTHON:-python}"
readonly PYTHON_BIN

step() {
  printf '\n==> [release-gate] %s\n' "$1"
}

fail() {
  printf '[release-gate] FAILED: %s\n' "$1" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "required command '$1' is not available"
}

worktree_state() {
  git status --porcelain=v1 --untracked-files=all
}

step "preflight: commands, Git checkout and runner identity"
for cmd in git "${PYTHON_BIN}" node npm find; do
  require_command "${cmd}"
done
[ "$(git rev-parse --is-inside-work-tree 2>/dev/null)" = "true" ] \
  || fail "not inside a Git work tree"
[ "$(cd "$(git rev-parse --show-toplevel)" && pwd)" = "${ROOT_DIR}" ] \
  || fail "the Git top level is not this repository root"
[ "$(id -u)" -ne 0 ] || fail "the release gate must run as a non-root user"
WORKTREE_BEFORE="$(worktree_state)"
readonly WORKTREE_BEFORE

step "python: interpreter, virtual environment and locked dependency set"
"${PYTHON_BIN}" - "${REQUIRED_PYTHON_MINOR}" "${PYTHON_LOCK}" <<'PY'
import re
import sys
from importlib import metadata
from pathlib import Path

required_minor, lock_path = sys.argv[1], Path(sys.argv[2])
actual_minor = f"{sys.version_info.major}.{sys.version_info.minor}"
if actual_minor != required_minor:
    sys.exit(f"Python {required_minor} is required, found {actual_minor}")
if sys.prefix == sys.base_prefix:
    sys.exit("the release gate must run inside a virtual environment")

pins = {}
for line in lock_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#"):
        continue
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;#]+)", line)
    if match is None:
        sys.exit(f"{lock_path}: not an exact pin: {line!r}")
    pins[match.group(1)] = match.group(2)

mismatches = []
for name, version in sorted(pins.items()):
    try:
        installed = metadata.version(name)
    except metadata.PackageNotFoundError:
        mismatches.append(f"{name}: not installed (lock {version})")
        continue
    if installed != version:
        mismatches.append(f"{name}: installed {installed}, lock {version}")
if mismatches:
    sys.exit("environment does not match the lock:\n  " + "\n  ".join(mismatches))
print(f"Python {sys.version.split()[0]}; {len(pins)} locked packages installed at their exact versions")
PY

step "python: pip check"
"${PYTHON_BIN}" -m pip check

step "python: full pytest suite"
PYTHONDONTWRITEBYTECODE=1 "${PYTHON_BIN}" -m pytest -p no:cacheprovider -q -rs

step "frontend: Node.js version"
node_major="$(node -p 'process.versions.node.split(".")[0]')"
[ "${node_major}" = "${REQUIRED_NODE_MAJOR}" ] \
  || fail "Node.js ${REQUIRED_NODE_MAJOR} is required, found $(node --version)"

step "frontend: npm ci from the committed lock"
npm --prefix web ci --no-audit --no-fund

step "frontend: runtime dependency audit (moderate or higher blocks)"
npm --prefix web audit --omit=dev --audit-level=moderate

step "frontend: full dependency audit (high or critical blocks)"
npm --prefix web audit --audit-level=high

step "frontend: full Vitest suite (no retries)"
npm --prefix web test -- --retry=0

step "frontend: production build (typecheck + vite build)"
npm --prefix web run build

step "frontend: no TypeScript/Vite emit outside the build output"
emitted="$(find web -path web/node_modules -prune -o -path web/dist -prune -o \
  \( -name '*.tsbuildinfo' -o -name 'vite.config.js' -o -name 'vite.config.d.ts' \) -print)"
[ -z "${emitted}" ] || fail "unintended TypeScript/Vite emit: ${emitted}"

step "shell: syntax of tracked shell scripts"
while IFS= read -r -d '' script; do
  bash -n "${script}" || fail "shell syntax error in ${script}"
done < <(git ls-files -z -- '*.sh')

step "hygiene: no tracked path is ignored"
tracked_ignored="$(git ls-files --cached --ignored --exclude-standard)"
[ -z "${tracked_ignored}" ] || fail "tracked paths are ignored by the current policy: ${tracked_ignored}"

step "hygiene: whitespace errors in the working tree and index"
git diff --check
git diff --cached --check

step "hygiene: the gate left the working tree unchanged"
[ "$(worktree_state)" = "${WORKTREE_BEFORE}" ] \
  || fail "the install/test/build sequence changed the working tree"

printf '\n[release-gate] application-release-gate: all mandatory checks passed\n'

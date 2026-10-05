# Application release gate

Project Spec S0301. This document describes the single, repository-owned release gate of the Atlas DataFlow application repository and its CI. It covers this repository only; infrastructure CI and production deployment belong to the infrastructure repository.

## Stable check name

The aggregate CI check is **`application-release-gate`** (job `application-release-gate` in `.github/workflows/application-ci.yml`). It only runs after the `secret-scan` and `shell-lint` jobs succeed, so a green `application-release-gate` implies all three passed. It is the name intended for a later GitHub branch-protection rule.

A green gate is repository evidence only. It is not GitHub branch protection (configuring that rule is a separate step that must itself be evidenced) and it is not M53 production readiness, which stays derived from recorded live evidence (`docs/current-architecture-overview.md`, section 9).

## Python test environment

The test environment is declared in repository source and locked to exact versions:

| Source | Owns |
|---|---|
| `api/pyproject.toml` | API/runtime dependencies (FastAPI, PyJWT[crypto], exact pandas/scikit-learn/joblib serving pins) |
| `pyproject.toml` extra `scientific-forecasting` | statsmodels for the offline scientific reproduction tests |
| `pyproject.toml` extra `test` | direct test-only tools: pytest, httpx, PyYAML, psycopg |
| `requirements-test.in` | the compile manifest naming the sources above |
| `requirements-test.lock.txt` | every resolved third-party package pinned with `==` |

Create a fresh environment with Python 3.12:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-virtualenv -r requirements-test.lock.txt
.venv/bin/python -m pip check
```

Regenerate the lock only through the pip-tools command recorded in `requirements-test.in`, under Python 3.12, from the repository root. Never install extra packages ad hoc to make the suite pass, and never add credentials, private indexes or local absolute paths to these files; `tests/test_test_environment_contract.py` enforces this. Cryptographic hashes are not required yet (production supply-chain reproducibility is a later spec).

## Running the gate locally

Prerequisites: a real Git checkout, a non-root user, the Python 3.12 virtual environment above activated (or `PYTHON` pointing at its interpreter), and Node.js 22 with npm.

```bash
. .venv/bin/activate
scripts/validate-application-release-gate.sh
```

The wrapper runs `set -euo pipefail`, stops at the first failing check and treats a missing command as a failure. In order it checks:

1. commands, Git checkout and non-root runner;
2. Python 3.12 inside a virtual environment whose installed packages exactly match the lock;
3. `pip check`;
4. the full pytest suite (no deselection, no retries);
5. Node.js 22, then `npm ci` from `web/package-lock.json`;
6. `npm audit --omit=dev --audit-level=moderate` (runtime dependencies: moderate or higher blocks);
7. `npm audit --audit-level=high` (all dependencies: high or critical blocks);
8. the full Vitest suite with `--retry=0`;
9. the production build (`npm run build` = strict `tsc` typecheck with `noEmit` + `vite build`);
10. no `*.tsbuildinfo`, `vite.config.js` or `vite.config.d.ts` emitted outside `web/dist`;
11. `bash -n` on every tracked shell script;
12. `git ls-files -ci --exclude-standard` is empty;
13. `git diff --check` for the working tree and the index;
14. the working tree is byte-for-byte as it was before the gate started.

It never deploys, never touches production, Supabase, backups or secrets, never rewrites Git state and never deletes files itself; `npm ci` alone replaces `web/node_modules`.

## CI workflow

`.github/workflows/application-ci.yml` runs on pull requests, pushes to `main` and manual dispatch with `contents: read` permissions only and no repository secrets. It does not use `pull_request_target`. Every third-party action is pinned to a full commit SHA.

| Job | What it does |
|---|---|
| `secret-scan` | full-history checkout (`fetch-depth: 0`), pinned Gitleaks binary verified by SHA-256, `gitleaks git --redact` over the whole history |
| `shell-lint` | ShellCheck on every tracked `*.sh` |
| `application-release-gate` | Python 3.12 + Node.js 22, fresh virtual environment from `requirements-test.lock.txt`, then `scripts/validate-application-release-gate.sh` |

No log or report artifact is uploaded; Gitleaks findings are printed redacted.

## Intentional skips

The gate does not deselect or retry tests. These skips remain intentional and bounded:

- `tests/supabase/test_inference_usage_reservation_live.py` — the live PostgreSQL reservation suite skips unless `ATLAS_TEST_POSTGRES_DSN` points at a disposable PostgreSQL 15+ database (`ATLAS_REQUIRE_POSTGRES_TESTS=1` turns the skip into a failure). A skip is not evidence for the quota criteria.
- `tests/pipeline/test_scientific_reproduction_nottem.py` — the SHA-verified external scientific source is gitignored and not part of the mandatory local gate.
- `tests/test_native_multiclass_training.py` (real end-to-end run section) — needs the local, gitignored raw input `data/raw/dry-bean/dataset.csv`, so it skips in a clean checkout such as CI; its synthetic tests still run.

## Branch protection

Branch protection for `main` is not configured by this repository and must not be assumed. When it is configured, it should require the `application-release-gate` check; that configuration must be recorded as its own evidence.

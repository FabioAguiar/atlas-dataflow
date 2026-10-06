# Production build and supply-chain provenance

Project Spec S0302. This document is the single source of truth for how the production API and web images of the Atlas DataFlow application repository are built from immutable inputs, how that build is checked, and what the resulting evidence does and does not prove. It covers this repository only. Production deployment adoption and runtime provenance verification belong to S0304 (see [Non-goals](#non-goals-and-ownership)).

## Two separate repository gates

| Check | Workflow | Responsibility |
|---|---|---|
| `application-release-gate` (S0301) | `.github/workflows/application-ci.yml` | the application is correct: full pytest, Vitest, frontend build, npm audits, repository hygiene ([application-release-gate.md](application-release-gate.md)) |
| `production-supply-chain-gate` (S0302) | `.github/workflows/production-supply-chain-ci.yml` | the production images are built from pinned, locked, attributable inputs: base digests, hash-locked API dependencies, `npm ci`, reproducibility, both architectures, SBOM/provenance |

Both are mandatory repository checks with different responsibilities; neither replaces the other. A green supply-chain gate says nothing about application correctness, and a green application gate says nothing about how the images are built. `production-supply-chain-gate` is the stable aggregate check name intended for a later GitHub branch-protection rule; configuring that rule is a separate, evidenced step.

## Authoritative dependency sources

| Source | Owns |
|---|---|
| `api/pyproject.toml` | the direct API runtime requirements (the only place their ranges and exact serving pins are declared) |
| `api/requirements-production.lock.txt` | the exact, hash-covered closure of `api/pyproject.toml` that the production API image installs |
| `web/package.json` + `web/package-lock.json` | the frontend dependency graph, installed only with `npm ci` |
| `FROM` lines of `api/Dockerfile` and `web/Dockerfile` | the three production base images, each `tag@sha256:<index digest>` |
| `requirements-test.lock.txt` | the S0301 test environment only; never installed into a production image |

The API image copies only `api/requirements-production.lock.txt` and runs `pip install --require-hashes --only-binary=:all:` followed by `pip check`; it no longer resolves the `api/pyproject.toml` ranges at image build time. Test-only and scientific-reproduction packages (pytest, httpx, psycopg, statsmodels) are not part of the production lock.

## Regenerating the API production lock

Regenerate only when `api/pyproject.toml` changes or a deliberate dependency update is reviewed. Use Python 3.12 and exactly `pip-tools==7.6.1`, from the repository root:

```bash
python3.12 -m venv /tmp/atlas-lock-tools
/tmp/atlas-lock-tools/bin/python -m pip install pip-tools==7.6.1
CUSTOM_COMPILE_COMMAND='pip-tools==7.6.1 under Python 3.12, from the repository root (see docs/operations/production-build-provenance.md): pip-compile --allow-unsafe --constraint=requirements-test.lock.txt --generate-hashes --no-emit-index-url --strip-extras --output-file=api/requirements-production.lock.txt api/pyproject.toml' \
  /tmp/atlas-lock-tools/bin/pip-compile --allow-unsafe --constraint=requirements-test.lock.txt \
    --generate-hashes --no-emit-index-url --strip-extras \
    --output-file=api/requirements-production.lock.txt api/pyproject.toml
```

- `api/pyproject.toml` is the only requirement input. `requirements-test.lock.txt` is a version *constraint* so production ships the exact versions the S0301 gate tested; it adds no package. Regenerate the test lock first if the two must move together.
- `--generate-hashes` is mandatory: every artifact of every pinned version carries a `sha256` hash, and the image installs with `--require-hashes`. The same lock serves linux/amd64 and linux/arm64; there is no per-architecture requirements file.
- Never add credentials, private or extra indexes, `--find-links`, editable (`-e`) entries, local or absolute paths, or VCS references to the lock.
- Validate the result before committing: a fresh Python 3.12 virtual environment must install it with `pip install --require-hashes --only-binary=:all: -r api/requirements-production.lock.txt` and pass `pip check`. `scripts/validate-production-supply-chain.sh` performs exactly this.

## Updating a base-image digest

Every production `FROM` keeps its readable tag and adds the immutable multi-platform **index** digest (never a single-platform child manifest), for example `python:3.12-slim@sha256:…`. A digest update is a deliberate repository change that must be reviewed like code:

1. resolve the official image: `docker buildx imagetools inspect docker.io/library/<image>:<tag>`;
2. confirm the index lists both `linux/amd64` and `linux/arm64`;
3. replace only the digest in the Dockerfile (same image family and tag line unless a separate, justified change says otherwise);
4. run the supply-chain gate and the application release gate.

No `latest`-style or tag-only reference is accepted; `tests/test_production_supply_chain_contract.py` rejects it.

## Required architectures

`linux/amd64` and `linux/arm64`, from the same Dockerfiles and the same committed locks. CI builds the non-native architecture under QEMU emulation; that is buildability evidence only, not ARM64 runtime evidence.

## Canonical build entrypoint

`scripts/build-production-images.sh` is the one canonical production-image builder:

```bash
scripts/build-production-images.sh --mode probe|attested --output-dir /tmp/atlas-images \
  [--component api|web|all] [--platform linux/amd64[,linux/arm64]] \
  [--expect-revision <sha>] [--web-arg NAME=VALUE]...
```

It requires a real, clean Git checkout and a docker-container Buildx builder (`BUILDX_BUILDER`). It builds from a fresh clone of `HEAD` in a temporary directory, so ignored or untracked local files never reach an image, and writes OCI archives to an output directory outside the checkout. It never deploys, starts or stops services, logs in to or pushes to a registry, or changes Git state, and it needs no production credential.

### Revision and timestamp rules

- `org.opencontainers.image.revision` (build argument `ATLAS_SOURCE_REVISION`) is always `git rev-parse HEAD` of the clean checkout. `--expect-revision` can only assert it: a mismatching value fails the build.
- `SOURCE_DATE_EPOCH` is the committer timestamp of that commit (`git log -1 --format=%ct`). A conflicting `SOURCE_DATE_EPOCH` in the environment fails the build. BuildKit uses it for the image `created` time, history and (with `rewrite-timestamp=true`) layer file times; the Dockerfiles use it to keep the `/etc/shadow` account day of the `atlas` user independent of the build clock.
- `org.opencontainers.image.source` is the static canonical repository `https://github.com/FabioAguiar/atlas-dataflow`. No clock-derived label is added.
- A dirty working tree is refused: no reproducibility or provenance claim is made for uncommitted source.

### Frontend build inputs

Only the public, browser-inlined inputs `VITE_API_BASE_URL`, `VITE_ENABLE_ADMIN`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` and `VITE_TURNSTILE_SITE_KEY` are accepted; any other name, and values that look like a Supabase secret or service-role key, are rejected. CI uses fixed synthetic values (`https://synthetic-ci.supabase.invalid`, a dummy publishable key and Cloudflare's documented Turnstile test site key) so no build depends on a live Supabase or Turnstile service.

## Reproducibility probe

From one clean commit and the same synthetic inputs, the gate builds each image twice for the runner's native architecture with `--no-cache --pull`, no attestations and `rewrite-timestamp=true`, and requires the two **image manifest digests** read from the OCI archives to be equal (API A = API B, web A = web B). Mutable local tags and BuildKit cache identity are never used as proof. A mismatch fails the gate and must be classified; known build-clock inputs are already neutralised (pip installs with `--no-compile` and bytecode is compiled with `--invalidation-mode checked-hash`, and account dates come from `SOURCE_DATE_EPOCH`).

**Image digest versus attestation envelope.** The probe compares the application image itself. An attested build wraps the same image in an index that also carries attestation manifests whose provenance contains build-instance data (invocation id, start/finish times), so the *index* digest of attested builds is expected to differ between runs. Provenance is therefore excluded from the comparison, never removed from the real attested build path.

## SBOM and provenance

`--mode attested` adds, for every image manifest, a BuildKit attestation manifest with:

- an SPDX SBOM (`https://spdx.dev/Document`) produced by a digest-pinned `docker/buildkit-syft-scanner`; the API SBOM lists the installed Python packages, the web SBOM also scans the build stage so it lists the npm graph that produced the bundle;
- an SLSA provenance statement (`https://slsa.dev/provenance/v1`, `mode=max`) whose VCS metadata names the canonical source and exact revision and whose resolved dependencies record every base image by its pinned digest.

The gate verifies that the attestation manifest's OCI `subject` is the image manifest it describes, that both statements exist, that the SBOM contains every locked API package (and the direct web dependencies) at the locked version, that the provenance revision equals `HEAD` and that the pinned base digests appear as materials. These attestations are **unsigned** BuildKit metadata stored next to the image. They are not a cryptographically signed third-party guarantee: no signing, transparency-log publication, registry promotion or SLSA level is claimed by S0302.

## Running the gate

Locally, from a clean checkout, with a Python 3.12 environment that has pytest and PyYAML (for example the S0301 test environment) and network access to Docker Hub and PyPI:

```bash
PYTHON=.venv/bin/python scripts/validate-production-supply-chain.sh
```

It stops at the first failing check: static contract test, base digest syntax and registry platform check, production lock contract, fresh hash-enforced install + `pip check`, npm lock / `npm ci` contract, builder capability, reproducibility probe, attested `linux/amd64,linux/arm64` builds with label/SBOM/provenance checks, and post-run repository cleanliness. A missing tool, emulator or attestation capability fails the gate. On a host that cannot emulate the other architecture, `--skip-unavailable-platforms` runs every other check but still exits `3`, never `0`. Working files stay in a temporary directory outside the checkout.

## Non-goals and ownership

- S0302 proves how images **can be** built from this repository. It does not prove what currently runs in production.
- No deployment, restart, registry push, signing or production-readiness claim is part of S0302.
- Production deployment adoption of these builds and runtime provenance verification belong to **S0304**; infrastructure CI belongs to S0303.

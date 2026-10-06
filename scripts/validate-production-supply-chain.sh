#!/usr/bin/env bash
# Production supply-chain gate of the Atlas DataFlow application repository
# (Project Spec S0302). Stops at the first failing check and exits non-zero.
#
# It never deploys, never starts or stops production services, never touches
# Supabase, backups or restores, never logs in to or pushes to a registry,
# never rewrites Git state and never deletes repository files. Working
# artifacts (OCI archives, SBOM/provenance extracts, a disposable virtual
# environment) live in a temporary directory outside the checkout.
#
# Requirements: a clean Git checkout, Docker with Buildx, a Python 3.12
# interpreter with pytest and PyYAML (PYTHON, default python3; e.g. the
# environment from requirements-test.lock.txt) and network access to the
# public registries (Docker Hub, PyPI). A docker-container Buildx builder able
# to build linux/amd64 and linux/arm64 is used when BUILDX_BUILDER names one;
# otherwise a temporary builder with a digest-pinned BuildKit is created and
# removed at exit. Both architectures are mandatory: a missing one fails the
# gate. --skip-unavailable-platforms runs every other check but still exits 3
# (never 0) when a required platform could not be built.
set -euo pipefail

readonly REQUIRED_PLATFORMS=(linux/amd64 linux/arm64)
readonly BUILDKIT_IMAGE="moby/buildkit:v0.33.1@sha256:cec9f139f45e93c5c69c60f8b07cfad9f43f4ef6b6a6cd917527fea5ff2e3dea"
readonly SOURCE_URL="https://github.com/FabioAguiar/atlas-dataflow"
# Synthetic, public-safe web build inputs (no live Supabase/Turnstile
# dependency). The Turnstile value is Cloudflare's documented test site key.
readonly SYNTHETIC_WEB_ARGS=(
  --web-arg "VITE_API_BASE_URL=/api"
  --web-arg "VITE_ENABLE_ADMIN=false"
  --web-arg "VITE_SUPABASE_URL=https://synthetic-ci.supabase.invalid"
  --web-arg "VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_synthetic_ci_only"
  --web-arg "VITE_TURNSTILE_SITE_KEY=1x00000000000000000000AA"
)

PYTHON="${PYTHON:-python3}"
skip_unavailable=0
created_builder=""
step_number=0

fail() {
  printf '\nproduction-supply-chain-gate: FAILED: %s\n' "$*" >&2
  exit 1
}

step() {
  step_number=$((step_number + 1))
  printf '\n==> [%02d] %s\n' "${step_number}" "$*"
}

cleanup() {
  if [[ -n "${created_builder}" ]]; then
    if ! docker buildx rm "${created_builder}" >/dev/null 2>&1; then
      printf 'warning: could not remove temporary builder %s\n' "${created_builder}" >&2
    fi
  fi
}
trap cleanup EXIT

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-unavailable-platforms) skip_unavailable=1; shift ;;
    *) fail "unknown argument: $1" ;;
  esac
done

step "required commands, Git checkout and clean source tree"
for cmd in git docker "${PYTHON}" mktemp sha256sum tar; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found: ${cmd}"
done
docker info >/dev/null 2>&1 || fail "the Docker daemon is not reachable"
docker buildx version >/dev/null 2>&1 || fail "Docker Buildx is not available"
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "not inside a Git checkout"
cd "${repo_root}"
initial_status="$(git status --porcelain --untracked-files=all)"
[[ -z "${initial_status}" ]] || fail "the working tree is not clean"
revision="$(git rev-parse --verify 'HEAD^{commit}')"
source_date_epoch="$(git log -1 --format=%ct "${revision}")"
"${PYTHON}" -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)' \
  || fail "PYTHON must be a Python 3.12 interpreter"
docker version --format 'docker engine {{.Server.Version}} ({{.Server.Os}}/{{.Server.Arch}})'
docker buildx version
printf 'revision %s, SOURCE_DATE_EPOCH %s\n' "${revision}" "${source_date_epoch}"

work_dir="$(mktemp -d "${TMPDIR:-/tmp}/atlas-supply-chain.XXXXXXXX")"
case "${work_dir}/" in
  "${repo_root}/"*) fail "the temporary directory must be outside the checkout" ;;
esac
export TMPDIR="${work_dir}"
helper="${work_dir}/supply_chain_check.py"
cat >"${helper}" <<'PY'
"""Offline checks of the S0302 supply-chain artifacts (stdlib only)."""
import json
import re
import sys
import tarfile
import tomllib
from pathlib import Path

ROOT = Path.cwd()
FROM_RE = re.compile(
    r"^FROM\s+(?P<repo>[a-z0-9./-]+):(?P<tag>[A-Za-z0-9._-]+)"
    r"@sha256:(?P<digest>[0-9a-f]{64})(?:\s+AS\s+(?P<stage>\S+))?\s*$"
)
EXPECTED_BASES = {("python", "3.12-slim"), ("node", "22-alpine"), ("nginx", "alpine")}
TEST_ONLY = {"pytest", "httpx", "statsmodels", "psycopg", "psycopg-binary"}


def die(message):
    print(f"supply-chain check failed: {message}", file=sys.stderr)
    sys.exit(1)


def norm(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def from_lines(path):
    return [line.strip() for line in path.read_text().splitlines() if re.match(r"^FROM\s", line)]


def bases():
    found = []
    for dockerfile in (ROOT / "api" / "Dockerfile", ROOT / "web" / "Dockerfile"):
        for line in from_lines(dockerfile):
            match = FROM_RE.match(line)
            if not match:
                die(f"{dockerfile.relative_to(ROOT)}: FROM is not tag@sha256 pinned: {line}")
            found.append((match["repo"], match["tag"], match["digest"]))
    if {(repo, tag) for repo, tag, _ in found} != EXPECTED_BASES or len(found) != 3:
        die(f"unexpected production base set: {found}")
    for repo, tag, digest in found:
        print(f"docker.io/library/{repo}:{tag}@sha256:{digest}")


def index_platforms(raw_path, required):
    data = json.loads(Path(raw_path).read_text())
    media = data.get("mediaType", "")
    if media not in (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
    ):
        die(f"base digest is not a multi-platform index ({media})")
    present = {
        f"{m['platform']['os']}/{m['platform']['architecture']}"
        for m in data.get("manifests", [])
        if m.get("platform", {}).get("os") not in (None, "unknown")
    }
    missing = sorted(set(required.split(",")) - present)
    if missing:
        die(f"base index lacks required platforms {missing}")
    print("platforms present: " + ", ".join(sorted(p for p in present if p in required.split(","))))


def lock_pins():
    pins, hashes, current = {}, {}, None
    text = (ROOT / "api" / "requirements-production.lock.txt").read_text()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if re.search(r"(^|\s)(-e|--editable|--index-url|--extra-index-url|-i|--find-links|-f|--trusted-host)\b", line):
            die(f"forbidden lock directive: {line}")
        if re.search(r"(file:|git\+|hg\+|svn\+|bzr\+|://|\s@\s|^/)", line):
            die(f"forbidden lock reference: {line}")
        if line.startswith("--hash="):
            if current is None or not re.fullmatch(r"--hash=sha256:[0-9a-f]{64}( \\)?", line):
                die(f"malformed hash line: {line}")
            hashes[current] += 1
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!_-]+)( \\)?", line)
        if not match:
            die(f"lock entry is not an exact pin: {line}")
        current = norm(match[1])
        pins[current] = match[2]
        hashes[current] = 0
    return pins, hashes


def lock_contract():
    pins, hashes = lock_pins()
    unhashed = sorted(name for name, count in hashes.items() if count == 0)
    if not pins or unhashed:
        die(f"lock entries without hashes: {unhashed}")
    header = (ROOT / "api" / "requirements-production.lock.txt").read_text().split("\n\n", 1)[0]
    for needle in ("Python 3.12", "pip-tools==7.6.1", "--generate-hashes", "api/pyproject.toml"):
        if needle not in header:
            die(f"lock header does not record {needle!r}")
    leaked = sorted(TEST_ONLY & set(pins))
    if leaked:
        die(f"test-only packages in the production lock: {leaked}")
    print(f"production lock: {len(pins)} exact pins, {sum(hashes.values())} sha256 hashes")


def installed_matches_lock():
    from importlib import metadata

    from pip._vendor.packaging.requirements import Requirement

    pins, _ = lock_pins()
    installed = {norm(d.metadata["Name"]): d.version for d in metadata.distributions()}
    installed.pop("pip", None)
    if installed != pins:
        extra = sorted(set(installed) - set(pins))
        missing = sorted(set(pins) - set(installed))
        die(f"installed set differs from lock (extra={extra}, missing={missing})")
    project = tomllib.loads((ROOT / "api" / "pyproject.toml").read_text())["project"]
    for spec in project["dependencies"]:
        requirement = Requirement(spec)
        version = installed.get(norm(requirement.name))
        if version is None or not requirement.specifier.contains(version, prereleases=True):
            die(f"direct dependency {spec!r} not satisfied (installed {version})")
    leaked = sorted(TEST_ONLY & set(installed))
    if leaked:
        die(f"test-only packages installed: {leaked}")
    print(f"fresh environment matches the lock ({len(installed)} packages) and every api/pyproject.toml requirement")


def npm_lock_contract():
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text())
    if lock.get("lockfileVersion", 0) < 2:
        die("web/package-lock.json lockfileVersion < 2")
    checked = 0
    for path, entry in lock.get("packages", {}).items():
        if not path or entry.get("link"):
            continue
        resolved = entry.get("resolved", "")
        if not resolved.startswith("https://registry.npmjs.org/"):
            die(f"{path}: not resolved from the public npm registry")
        if not re.fullmatch(r"sha512-[A-Za-z0-9+/]+={0,2}", entry.get("integrity", "")):
            die(f"{path}: missing sha512 integrity")
        checked += 1
    dockerfile = (ROOT / "web" / "Dockerfile").read_text()
    if "COPY package.json package-lock.json ./\nRUN npm ci\n" not in dockerfile:
        die("web/Dockerfile does not copy both package files before npm ci")
    if re.search(r"\bnpm\s+(install|i|update)\b", dockerfile):
        die("web/Dockerfile runs npm install/update")
    print(f"web/package-lock.json: {checked} registry entries with sha512 integrity; npm ci build path intact")


class Layout:
    def __init__(self, archive):
        self.tar = tarfile.open(archive)

    def blob(self, digest):
        algorithm, hexdigest = digest.split(":", 1)
        return json.load(self.tar.extractfile(f"blobs/{algorithm}/{hexdigest}"))

    def index(self):
        return json.load(self.tar.extractfile("index.json"))


def probe_digest(archive):
    layout = Layout(archive)
    manifests = layout.index()["manifests"]
    if len(manifests) != 1 or manifests[0]["mediaType"] != "application/vnd.oci.image.manifest.v1+json":
        die(f"{archive}: probe output is not exactly one image manifest without attestations")
    print(manifests[0]["digest"])


def lock_versions_for_sbom(component):
    if component == "api":
        pins, _ = lock_pins()
        return pins
    lock = json.loads((ROOT / "web" / "package-lock.json").read_text())
    package = json.loads((ROOT / "web" / "package.json").read_text())
    wanted = {}
    for name in package.get("dependencies", {}):
        entry = lock["packages"].get(f"node_modules/{name}")
        if entry:
            wanted[name] = entry["version"]
    return wanted


def attested(archive, component, revision, platforms, report):
    layout = Layout(archive)
    top = layout.index()["manifests"]
    if len(top) != 1 or top[0]["mediaType"] != "application/vnd.oci.image.index.v1+json":
        die(f"{archive}: attested output is not one image index")
    index = layout.blob(top[0]["digest"])
    images, attestations = {}, {}
    for descriptor in index["manifests"]:
        annotations = descriptor.get("annotations") or {}
        if annotations.get("vnd.docker.reference.type") == "attestation-manifest":
            attestations[annotations["vnd.docker.reference.digest"]] = descriptor
        else:
            platform = descriptor["platform"]
            images[f"{platform['os']}/{platform['architecture']}"] = descriptor
    dockerfile = ROOT / component / "Dockerfile"
    pinned = {m["digest"] for m in map(FROM_RE.match, from_lines(dockerfile)) if m}
    expected_versions = {norm(k): v for k, v in lock_versions_for_sbom(component).items()}
    results = []
    for platform in platforms.split(","):
        image = images.get(platform)
        if image is None:
            die(f"{component}: no image manifest for {platform}")
        manifest = layout.blob(image["digest"])
        config = layout.blob(manifest["config"]["digest"])
        labels = config.get("config", {}).get("Labels") or {}
        if labels.get("org.opencontainers.image.source") != sys.argv[-1]:
            die(f"{component} {platform}: org.opencontainers.image.source label mismatch")
        if labels.get("org.opencontainers.image.revision") != revision:
            die(f"{component} {platform}: org.opencontainers.image.revision label mismatch")
        attestation = attestations.get(image["digest"])
        if attestation is None:
            die(f"{component} {platform}: no attestation manifest bound to {image['digest']}")
        att_manifest = layout.blob(attestation["digest"])
        if (att_manifest.get("subject") or {}).get("digest") != image["digest"]:
            die(f"{component} {platform}: attestation manifest subject does not bind the image")
        statements = {}
        for layer in att_manifest["layers"]:
            statement = layout.blob(layer["digest"])
            for subject in statement.get("subject") or []:
                if "sha256:" + subject.get("digest", {}).get("sha256", "") != image["digest"]:
                    die(f"{component} {platform}: in-toto subject does not match the image")
            statements.setdefault(statement["predicateType"], []).append(statement)
        sboms = statements.get("https://spdx.dev/Document", [])
        provenances = [s for t, group in statements.items() if t.startswith("https://slsa.dev/provenance/") for s in group]
        if not sboms:
            die(f"{component} {platform}: SBOM attestation missing")
        if len(provenances) != 1:
            die(f"{component} {platform}: expected exactly one provenance attestation")
        inventory = {}
        for sbom in sboms:
            for package in sbom["predicate"].get("packages", []):
                inventory.setdefault(norm(package.get("name", "")), set()).add(package.get("versionInfo"))
        absent = sorted(n for n, v in expected_versions.items() if v not in inventory.get(n, set()))
        if absent:
            die(f"{component} {platform}: SBOM lacks locked packages {absent}")
        predicate = provenances[0]["predicate"]
        vcs = (predicate.get("runDetails", {}).get("metadata", {}).get("buildkit_metadata", {}) or {}).get("vcs", {})
        if vcs.get("revision") != revision or vcs.get("source") != sys.argv[-1]:
            die(f"{component} {platform}: provenance VCS revision/source mismatch")
        dependencies = predicate.get("buildDefinition", {}).get("resolvedDependencies", [])
        material_digests = {d.get("digest", {}).get("sha256") for d in dependencies if d.get("uri", "").startswith("pkg:docker/")}
        if not pinned <= material_digests:
            die(f"{component} {platform}: provenance lacks the pinned base digests")
        results.append({
            "component": component,
            "platform": platform,
            "image_manifest_digest": image["digest"],
            "attestation_manifest_digest": attestation["digest"],
            "sbom_documents": len(sboms),
            "sbom_packages": sum(len(s["predicate"].get("packages", [])) for s in sboms),
            "provenance_predicate": provenances[0]["predicateType"],
            "provenance_revision": vcs["revision"],
            "pinned_base_digests_in_materials": sorted(pinned),
        })
        print(f"{component} {platform}: image {image['digest']}, SBOM+provenance bound, revision and base digests verified")
    with open(report, "a", encoding="utf-8") as handle:
        for result in results:
            handle.write(json.dumps(result, sort_keys=True) + "\n")


COMMANDS = {
    "bases": lambda: bases(),
    "index-platforms": lambda: index_platforms(sys.argv[2], sys.argv[3]),
    "lock-contract": lambda: lock_contract(),
    "installed-matches-lock": lambda: installed_matches_lock(),
    "npm-lock-contract": lambda: npm_lock_contract(),
    "probe-digest": lambda: probe_digest(sys.argv[2]),
    "attested": lambda: attested(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6]),
}

if __name__ == "__main__":
    COMMANDS[sys.argv[1]]()
PY

step "static production supply-chain contract test"
PYTHONDONTWRITEBYTECODE=1 "${PYTHON}" -m pytest -q -p no:cacheprovider tests/test_production_supply_chain_contract.py

step "base-image digest syntax and multi-platform registry resolution"
"${PYTHON}" "${helper}" bases >"${work_dir}/base-refs.txt"
mapfile -t base_refs <"${work_dir}/base-refs.txt"
[[ "${#base_refs[@]}" -eq 3 ]] || fail "expected exactly three production base references"
required_csv="$(IFS=,; printf '%s' "${REQUIRED_PLATFORMS[*]}")"
for ref in "${base_refs[@]}"; do
  printf '%s\n' "${ref}"
  docker buildx imagetools inspect --raw "${ref}" >"${work_dir}/base-index.json" \
    || fail "cannot resolve ${ref} in the official registry"
  "${PYTHON}" "${helper}" index-platforms "${work_dir}/base-index.json" "${required_csv}"
done

step "API production lock contract"
"${PYTHON}" "${helper}" lock-contract

step "fresh hash-enforced install of the production lock + pip check"
"${PYTHON}" -m venv "${work_dir}/production-venv"
venv_python="${work_dir}/production-venv/bin/python"
"${venv_python}" -m pip install --quiet --require-virtualenv --no-cache-dir \
  --require-hashes --only-binary=:all: -r api/requirements-production.lock.txt
"${venv_python}" -m pip check
PYTHONDONTWRITEBYTECODE=1 "${venv_python}" "${helper}" installed-matches-lock

step "frontend npm lock / npm ci build contract"
"${PYTHON}" "${helper}" npm-lock-contract

step "Buildx builder with cross-platform and attestation support"
if [[ -n "${BUILDX_BUILDER:-}" ]]; then
  builder_driver="$(docker buildx inspect "${BUILDX_BUILDER}" | sed -n 's/^Driver:[[:space:]]*//p' | head -n 1)"
  [[ "${builder_driver}" != "docker" ]] || fail "BUILDX_BUILDER uses the docker driver; a docker-container builder is required"
else
  created_builder="atlas-supply-chain-${RANDOM}${RANDOM}"
  docker buildx create --name "${created_builder}" --driver docker-container \
    --driver-opt "image=${BUILDKIT_IMAGE}" >/dev/null
  export BUILDX_BUILDER="${created_builder}"
fi
builder_platforms="$(docker buildx inspect --bootstrap "${BUILDX_BUILDER}" | sed -n 's/^Platforms:[[:space:]]*//p' | tr -d ' ')"
printf 'builder %s platforms: %s\n' "${BUILDX_BUILDER}" "${builder_platforms}"
available=()
missing=()
for platform in "${REQUIRED_PLATFORMS[@]}"; do
  case ",${builder_platforms}," in
    *",${platform},"*|*",${platform}/"*) available+=("${platform}") ;;
    *) missing+=("${platform}") ;;
  esac
done
if [[ "${#missing[@]}" -gt 0 && "${skip_unavailable}" -ne 1 ]]; then
  fail "the builder cannot build required platform(s): ${missing[*]} (install QEMU/binfmt or use a capable builder)"
fi
[[ "${#available[@]}" -gt 0 ]] || fail "the builder can build none of the required platforms"
native_platform="linux/$(docker version --format '{{.Server.Arch}}')"
case " ${available[*]} " in
  *" ${native_platform} "*) ;;
  *) fail "the builder cannot build the native platform ${native_platform}" ;;
esac

step "same-source reproducibility probe (${native_platform}, two independent no-cache builds)"
for component in api web; do
  for run in a b; do
    scripts/build-production-images.sh --mode probe --component "${component}" \
      --platform "${native_platform}" --expect-revision "${revision}" \
      --output-dir "${work_dir}/probe-${run}" "${SYNTHETIC_WEB_ARGS[@]}"
  done
  archive_name="${component}-probe-${native_platform//\//-}.oci.tar"
  digest_a="$("${PYTHON}" "${helper}" probe-digest "${work_dir}/probe-a/${archive_name}")"
  digest_b="$("${PYTHON}" "${helper}" probe-digest "${work_dir}/probe-b/${archive_name}")"
  printf '%s probe A %s\n%s probe B %s\n' "${component}" "${digest_a}" "${component}" "${digest_b}"
  [[ "${digest_a}" == "${digest_b}" ]] \
    || fail "${component} image digest differs between identical no-cache builds (nondeterministic build input)"
  printf '%s %s %s\n' "${component}" "${digest_a}" "${digest_b}" >>"${work_dir}/reproducibility.txt"
done

platforms_csv="$(IFS=,; printf '%s' "${available[*]}")"
platforms_label="$(printf '%s' "${platforms_csv}" | tr '/,' '-_')"
step "attested production builds (${platforms_csv}): OCI labels, SBOM and provenance"
scripts/build-production-images.sh --mode attested --component all \
  --platform "${platforms_csv}" --expect-revision "${revision}" \
  --output-dir "${work_dir}/attested" "${SYNTHETIC_WEB_ARGS[@]}"
for component in api web; do
  "${PYTHON}" "${helper}" attested \
    "${work_dir}/attested/${component}-attested-${platforms_label}.oci.tar" \
    "${component}" "${revision}" "${platforms_csv}" "${work_dir}/attestation-report.jsonl" "${SOURCE_URL}"
done

step "post-run repository cleanliness"
[[ -z "$(git ls-files -ci --exclude-standard)" ]] || fail "tracked files match ignore rules"
git diff --check || fail "git diff --check reported problems"
git diff --cached --check || fail "git diff --cached --check reported problems"
[[ "$(git status --porcelain --untracked-files=all)" == "${initial_status}" ]] \
  || fail "the gate changed the working tree"
[[ "$(git rev-parse HEAD)" == "${revision}" ]] || fail "HEAD moved during the gate"

# Large OCI archives are removed file by file; the reduced evidence stays.
for archive in "${work_dir}"/probe-a/*.oci.tar "${work_dir}"/probe-b/*.oci.tar "${work_dir}"/attested/*.oci.tar; do
  if [[ -f "${archive}" ]]; then
    rm -f -- "${archive}"
  fi
done
printf '\nreduced evidence: %s/reproducibility.txt, %s/attestation-report.jsonl\n' "${work_dir}" "${work_dir}"

if [[ "${#missing[@]}" -gt 0 ]]; then
  printf '\nproduction-supply-chain-gate: INCOMPLETE: required platform(s) not built here: %s\n' "${missing[*]}" >&2
  exit 3
fi
printf '\nproduction-supply-chain-gate: OK (revision %s; platforms %s)\n' "${revision}" "${platforms_csv}"

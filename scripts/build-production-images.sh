#!/usr/bin/env bash
# Canonical production-image builder of the Atlas DataFlow application
# repository (Project Spec S0302).
#
# Builds the API (api/Dockerfile, context = repository root) and web
# (web/Dockerfile, context = web/) production images from a clean Git HEAD and
# writes them as OCI archives into an output directory OUTSIDE the checkout.
#
#   probe     no-cache build without attestations; the image manifest digest
#             is the reproducibility probe value (one platform).
#   attested  build with a BuildKit SBOM attestation and a provenance
#             attestation (mode=max) bound to every produced image manifest.
#
# The source revision and SOURCE_DATE_EPOCH are derived from HEAD and its
# commit timestamp; a caller can only assert them (--expect-revision), never
# replace them. The build context is a fresh, clean clone of HEAD in a
# temporary directory, so ignored or untracked local files never enter an
# image. This script never deploys, never starts or stops services, never
# logs in to or pushes to a registry and never changes Git state.
#
# Web build inputs are public by definition (they are inlined into the
# browser bundle). Only the allowlisted VITE_* names below are accepted, and
# values that look like server-side secrets are rejected.
#
# Usage:
#   scripts/build-production-images.sh --mode probe|attested --output-dir DIR
#       [--component api|web|all] [--platform linux/amd64[,linux/arm64]]
#       [--expect-revision SHA] [--web-arg NAME=VALUE]...
set -euo pipefail

readonly SOURCE_URL="https://github.com/FabioAguiar/atlas-dataflow"
# BuildKit SBOM generator, pinned by its multi-platform index digest.
readonly SBOM_GENERATOR="docker/buildkit-syft-scanner:stable-1@sha256:ae4f3b554449e7e25548e7d8ccc029d17357348e30c6e3df01b92bc93654d6a9"
readonly WEB_ARG_NAMES=(
  VITE_API_BASE_URL
  VITE_ENABLE_ADMIN
  VITE_SUPABASE_URL
  VITE_SUPABASE_PUBLISHABLE_KEY
  VITE_TURNSTILE_SITE_KEY
)

fail() {
  printf 'build-production-images: %s\n' "$*" >&2
  exit 1
}

usage() {
  sed -n '/^# Usage:/,/^set -euo pipefail/p' "${BASH_SOURCE[0]}" | sed -e '$d' -e 's/^# \{0,1\}//' >&2
  exit 2
}

# --- builder platform normalization (exercised in isolation by
# tests/test_production_supply_chain_contract.py) ---
# Reads `docker buildx inspect` output on stdin and prints the canonical,
# comma-separated platform list of every "Platforms:" line. Buildx marks
# preferred platforms with a trailing "*" (e.g. "linux/arm64*"); that
# presentation marker is dropped. Tokens that are not well-formed
# os/arch[/variant] platforms after normalization are discarded, so they can
# never satisfy a required platform.
canonical_builder_platforms() {
  local line token
  local -a canonical=() tokens=()
  while IFS= read -r line; do
    [[ "${line}" =~ ^Platforms:[[:space:]]*(.*)$ ]] || continue
    IFS=',' read -r -a tokens <<<"${BASH_REMATCH[1]}"
    for token in "${tokens[@]}"; do
      token="${token//[[:space:]]/}"
      token="${token%\*}"
      [[ "${token}" =~ ^[a-z0-9]+/[a-z0-9_]+(/[a-z0-9]+)?$ ]] && canonical+=("${token}")
    done
  done
  (IFS=,; printf '%s' "${canonical[*]}")
}

# Succeeds when the canonical list ($1) contains the exact required platform
# ($2) or one of its explicit variants ("linux/arm64/v8" -> "linux/arm64").
builder_has_platform() {
  case ",$1," in
    *",$2,"*|*",$2/"*) return 0 ;;
    *) return 1 ;;
  esac
}
# --- end builder platform normalization ---

mode=""
output_dir=""
component="all"
platforms=""
expect_revision=""
web_args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --mode) [[ $# -ge 2 ]] || usage; mode="$2"; shift 2 ;;
    --output-dir) [[ $# -ge 2 ]] || usage; output_dir="$2"; shift 2 ;;
    --component) [[ $# -ge 2 ]] || usage; component="$2"; shift 2 ;;
    --platform) [[ $# -ge 2 ]] || usage; platforms="$2"; shift 2 ;;
    --expect-revision) [[ $# -ge 2 ]] || usage; expect_revision="$2"; shift 2 ;;
    --web-arg) [[ $# -ge 2 ]] || usage; web_args+=("$2"); shift 2 ;;
    -h|--help) usage ;;
    *) fail "unknown argument: $1" ;;
  esac
done

case "${mode}" in
  probe|attested) ;;
  *) fail "--mode must be probe or attested" ;;
esac
case "${component}" in
  api|web|all) ;;
  *) fail "--component must be api, web or all" ;;
esac
[[ -n "${output_dir}" ]] || fail "--output-dir is required"

for cmd in git docker mktemp realpath base64; do
  command -v "${cmd}" >/dev/null 2>&1 || fail "required command not found: ${cmd}"
done
docker buildx version >/dev/null 2>&1 || fail "Docker Buildx is not available"

repo_root="$(git rev-parse --show-toplevel 2>/dev/null)" || fail "not inside a Git checkout"
[[ "$(git -C "${repo_root}" rev-parse --is-inside-work-tree)" == "true" ]] || fail "not a Git work tree"
[[ -f "${repo_root}/api/Dockerfile" && -f "${repo_root}/web/Dockerfile" ]] \
  || fail "this is not the Atlas DataFlow application repository"

# A reproducibility or provenance claim is only made for a clean source tree.
if [[ -n "$(git -C "${repo_root}" status --porcelain --untracked-files=normal)" ]]; then
  fail "the working tree is not clean; commit or stash changes before a canonical build"
fi

revision="$(git -C "${repo_root}" rev-parse --verify 'HEAD^{commit}')"
[[ "${revision}" =~ ^[0-9a-f]{40}$ ]] || fail "HEAD is not a full SHA-1 commit id"
if [[ -n "${expect_revision}" && "${expect_revision}" != "${revision}" ]]; then
  fail "expected revision ${expect_revision} does not match HEAD ${revision}"
fi
source_date_epoch="$(git -C "${repo_root}" log -1 --format=%ct "${revision}")"
[[ "${source_date_epoch}" =~ ^[0-9]+$ ]] || fail "cannot derive SOURCE_DATE_EPOCH from the commit"
if [[ -n "${SOURCE_DATE_EPOCH:-}" && "${SOURCE_DATE_EPOCH}" != "${source_date_epoch}" ]]; then
  fail "SOURCE_DATE_EPOCH in the environment does not match the commit timestamp"
fi

native_platform="linux/$(docker version --format '{{.Server.Arch}}')"
if [[ -z "${platforms}" ]]; then
  platforms="${native_platform}"
fi
IFS=',' read -r -a platform_list <<<"${platforms}"
for platform in "${platform_list[@]}"; do
  case "${platform}" in
    linux/amd64|linux/arm64) ;;
    *) fail "unsupported platform: ${platform} (allowed: linux/amd64, linux/arm64)" ;;
  esac
done
if [[ "${mode}" == "probe" && "${#platform_list[@]}" -ne 1 ]]; then
  fail "probe mode builds exactly one platform"
fi

# The selected builder is inspected once; driver, name and platforms all come
# from that single observation.
builder_inspect="$(docker buildx inspect --bootstrap 2>/dev/null)" \
  || fail "cannot inspect the selected Buildx builder"
builder_driver="$(sed -n 's/^Driver:[[:space:]]*//p' <<<"${builder_inspect}" | head -n 1)"
[[ -n "${builder_driver}" ]] || fail "cannot inspect the selected Buildx builder"
if [[ "${builder_driver}" == "docker" ]]; then
  fail "the selected Buildx builder uses the docker driver; select a docker-container builder (BUILDX_BUILDER)"
fi
builder_name="$(sed -n 's/^Name:[[:space:]]*//p' <<<"${builder_inspect}" | head -n 1)"
[[ -n "${builder_name}" ]] || fail "cannot determine the selected Buildx builder name"
builder_platforms="$(canonical_builder_platforms <<<"${builder_inspect}")"
[[ -n "${builder_platforms}" ]] || fail "the selected Buildx builder reported no parseable platforms"
for platform in "${platform_list[@]}"; do
  builder_has_platform "${builder_platforms}" "${platform}" \
    || fail "the selected Buildx builder cannot build ${platform}"
done

# Web build inputs: allowlisted public names only; reject secret-looking values.
declare -A web_values=()
for name in "${WEB_ARG_NAMES[@]}"; do
  web_values["${name}"]=""
done
for pair in "${web_args[@]}"; do
  [[ "${pair}" == *=* ]] || fail "--web-arg must be NAME=VALUE"
  name="${pair%%=*}"
  value="${pair#*=}"
  [[ -v "web_values[${name}]" ]] || fail "web build input ${name} is not an allowlisted public VITE_* input"
  case "${value}" in
    *service_role*|sb_secret_*) fail "web build input ${name} looks like a server-side secret" ;;
  esac
  if [[ "${value}" =~ ^eyJ[A-Za-z0-9_-]*\.([A-Za-z0-9_-]+)\.[A-Za-z0-9_-]*$ ]]; then
    payload="${BASH_REMATCH[1]}"
    while (( ${#payload} % 4 != 0 )); do payload+="="; done
    if ! decoded="$(printf '%s' "${payload}" | tr '_-' '/+' | base64 -d 2>/dev/null)"; then
      decoded=""
    fi
    [[ "${decoded}" != *service_role* ]] || fail "web build input ${name} is a service-role token"
  fi
  web_values["${name}"]="${value}"
done

# Resolve without creating anything, so a rejected path leaves no residue.
output_dir="$(realpath -m -- "${output_dir}")"
case "${output_dir}/" in
  "$(realpath -- "${repo_root}")/"*) fail "--output-dir must be outside the source checkout" ;;
esac
mkdir -p -- "${output_dir}"

# Fresh, clean clone of the exact revision as the build context. Its origin is
# the canonical public repository so BuildKit records that as the VCS source.
work_dir="$(mktemp -d "${TMPDIR:-/tmp}/atlas-build-context.XXXXXXXX")"
source_dir="${work_dir}/source"
git clone --quiet --no-tags --depth 1 "file://${repo_root}" "${source_dir}"
git -C "${source_dir}" checkout --quiet --detach "${revision}"
git -C "${source_dir}" remote set-url origin "${SOURCE_URL}"
[[ "$(git -C "${source_dir}" rev-parse HEAD)" == "${revision}" ]] || fail "build context revision mismatch"
[[ -z "$(git -C "${source_dir}" status --porcelain --untracked-files=normal)" ]] || fail "build context is not clean"

platform_label="$(printf '%s' "${platforms}" | tr '/,' '-_')"
common_args=(
  --builder "${builder_name}"
  --platform "${platforms}"
  --build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}"
  --build-arg "ATLAS_SOURCE_REVISION=${revision}"
  --pull
  --no-cache
)
if [[ "${mode}" == "probe" ]]; then
  common_args+=(--provenance=false --sbom=false)
else
  common_args+=(--attest "type=provenance,mode=max" --attest "type=sbom,generator=${SBOM_GENERATOR}")
fi

build_component() {
  local name="$1"
  local dockerfile context
  local extra_args=()
  if [[ "${name}" == "api" ]]; then
    dockerfile="${source_dir}/api/Dockerfile"
    context="${source_dir}"
  else
    dockerfile="${source_dir}/web/Dockerfile"
    context="${source_dir}/web"
    local input
    for input in "${WEB_ARG_NAMES[@]}"; do
      extra_args+=(--build-arg "${input}=${web_values[${input}]}")
    done
  fi
  local archive="${output_dir}/${name}-${mode}-${platform_label}.oci.tar"
  local metadata="${output_dir}/${name}-${mode}-${platform_label}.metadata.json"
  printf 'build-production-images: building %s (%s, %s) at %s\n' "${name}" "${mode}" "${platforms}" "${revision}"
  docker buildx build \
    "${common_args[@]}" \
    "${extra_args[@]}" \
    --file "${dockerfile}" \
    --metadata-file "${metadata}" \
    --output "type=oci,dest=${archive},rewrite-timestamp=true" \
    "${context}"
}

case "${component}" in
  api) build_component api ;;
  web) build_component web ;;
  all) build_component api; build_component web ;;
esac

{
  printf 'revision=%s\n' "${revision}"
  printf 'source_date_epoch=%s\n' "${source_date_epoch}"
  printf 'source=%s\n' "${SOURCE_URL}"
  printf 'mode=%s\n' "${mode}"
  printf 'platforms=%s\n' "${platforms}"
} >"${output_dir}/build-${mode}-${platform_label}.env"

printf 'build-production-images: OK (%s, revision %s, SOURCE_DATE_EPOCH %s); outputs in %s\n' \
  "${mode}" "${revision}" "${source_date_epoch}" "${output_dir}"
printf 'build-production-images: temporary build context left at %s (outside the checkout)\n' "${work_dir}"

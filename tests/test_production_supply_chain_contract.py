"""Project Spec S0302: the production supply-chain contract is static and enforced.

Repository files are parsed as text/YAML/JSON only. No network, Docker,
registry, PyPI, npm, GitHub, production or Supabase access happens here;
digest resolution, builds, reproducibility and attestations are exercised by
``scripts/validate-production-supply-chain.sh`` and its CI workflow. The only
subprocess (S0306) runs the validator's pure Buildx platform normalization
functions under bash against synthetic ``docker buildx inspect`` output.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DOCKERFILE = REPO_ROOT / "api" / "Dockerfile"
WEB_DOCKERFILE = REPO_ROOT / "web" / "Dockerfile"
PRODUCTION_LOCK = REPO_ROOT / "api" / "requirements-production.lock.txt"
TEST_LOCK = REPO_ROOT / "requirements-test.lock.txt"
API_PYPROJECT = REPO_ROOT / "api" / "pyproject.toml"
BUILD_SCRIPT = REPO_ROOT / "scripts" / "build-production-images.sh"
VALIDATOR = REPO_ROOT / "scripts" / "validate-production-supply-chain.sh"
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "production-supply-chain-ci.yml"
PROVENANCE_DOC = REPO_ROOT / "docs" / "operations" / "production-build-provenance.md"
GATE_DOC = REPO_ROOT / "docs" / "operations" / "application-release-gate.md"
README = REPO_ROOT / "README.md"

CANONICAL_SOURCE = "https://github.com/FabioAguiar/atlas-dataflow"
AGGREGATE_CHECK = "production-supply-chain-gate"
REQUIRED_PLATFORMS = ("linux/amd64", "linux/arm64")
EXPECTED_BASES = {
    API_DOCKERFILE: [("python", "3.12-slim", None)],
    WEB_DOCKERFILE: [("node", "22-alpine", "build"), ("nginx", "alpine", "serve")],
}
TEST_ONLY_PACKAGES = {"pytest", "httpx", "statsmodels", "psycopg", "psycopg-binary"}
PINNED_FROM = re.compile(
    r"^FROM\s+(?P<repo>[a-z0-9./-]+):(?P<tag>[A-Za-z0-9._-]+)"
    r"@sha256:(?P<digest>[0-9a-f]{64})(?:\s+AS\s+(?P<stage>\S+))?$"
)
PINNED_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
PINNED_IMAGE = re.compile(r"^[a-z0-9./-]+:[A-Za-z0-9._-]+@sha256:[0-9a-f]{64}$")
DESTRUCTIVE_OR_PUBLISHING = re.compile(
    r"\beval\b|\|\|\s*true\b|\bset\s+-x\b|\bprintenv\b|\benv\s*$|\brm\s+-[a-zA-Z]*r"
    r"|\bgit\s+(?:-C\s+\S+\s+)?(?:push|commit|reset|clean|stash|rebase|tag|branch\s+-[dD])\b"
    r"|\bdocker\s+(?:push|login|compose|stop|restart|rm\b|run\b)|\bdocker-compose\b"
    r"|--push\b|type=registry|push=true|\bsupabase\s+(?:db|functions|link|migration)\b|\bpg_dump\b|\bpg_restore\b|\bssh\b",
    re.MULTILINE,
)


def _instructions(path: Path) -> list[str]:
    """Dockerfile instructions with continuations joined and comments dropped."""
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]
    return [" ".join(chunk.split()) for chunk in "\n".join(lines).replace("\\\n", " ").splitlines() if chunk.strip()]


def _final_stage(path: Path) -> list[str]:
    instructions = _instructions(path)
    last_from = max(i for i, line in enumerate(instructions) if line.startswith("FROM "))
    return instructions[last_from:]


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries(path: Path) -> dict[str, tuple[str, int]]:
    entries: dict[str, tuple[str, int]] = {}
    current = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("--hash="):
            assert current is not None, f"hash without a requirement: {line}"
            assert re.fullmatch(r"--hash=sha256:[0-9a-f]{64}( \\)?", line), line
            version, count = entries[current]
            entries[current] = (version, count + 1)
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9.+!_-]+)( \\)?", line)
        assert match, f"lock entry is not an exact pin: {line!r}"
        current = _norm(match[1])
        entries[current] = (match[2], 0)
    return entries


def _code(path: Path) -> str:
    """Shell source without comment lines (comments may describe what is forbidden)."""
    return _code_text(path.read_text(encoding="utf-8"))


def _code_text(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# --- base images -----------------------------------------------------------


@pytest.mark.parametrize("dockerfile", list(EXPECTED_BASES), ids=lambda p: p.parent.name)
def test_every_production_from_is_a_readable_tag_plus_sha256_digest(dockerfile: Path) -> None:
    froms = [line for line in _instructions(dockerfile) if line.upper().startswith("FROM ")]
    assert froms, f"{dockerfile} has no FROM"
    found = []
    for line in froms:
        match = PINNED_FROM.match(line)
        assert match, f"tag-only or malformed production FROM: {line!r}"
        assert match["tag"] != "latest"
        found.append((match["repo"], match["tag"], match["stage"]))
    assert found == EXPECTED_BASES[dockerfile]


def test_base_digests_are_distinct_sha256_index_pins() -> None:
    digests = [
        PINNED_FROM.match(line)["digest"]
        for dockerfile in EXPECTED_BASES
        for line in _instructions(dockerfile)
        if line.startswith("FROM ")
    ]
    assert len(digests) == 3
    assert len(set(digests)) == 3


# --- API production lock ---------------------------------------------------


def test_api_dockerfile_installs_only_the_hash_locked_production_lock() -> None:
    instructions = _instructions(API_DOCKERFILE)
    text = "\n".join(instructions)
    assert "COPY api/requirements-production.lock.txt ./api/requirements-production.lock.txt" in instructions
    installs = [line for line in instructions if "pip install" in line or "pip3 install" in line]
    assert len(installs) == 1, installs
    install = installs[0]
    for flag in ("--require-hashes", "--only-binary=:all:", "--no-cache-dir", "-r ./api/requirements-production.lock.txt"):
        assert flag in install
    assert "python -m pip check" in install
    # pyproject ranges are never resolved inside the image any more.
    assert "pyproject.toml" not in text
    assert "tomllib" not in text
    assert "requirements-test.lock.txt" not in text


def test_api_dockerfile_bytecode_and_account_metadata_do_not_depend_on_the_build_clock() -> None:
    text = "\n".join(_instructions(API_DOCKERFILE))
    assert "--no-compile" in text
    assert "--invalidation-mode checked-hash" in text
    assert "ARG SOURCE_DATE_EPOCH" in text


def test_production_lock_is_exactly_pinned_hash_covered_and_clean() -> None:
    entries = _lock_entries(PRODUCTION_LOCK)
    assert entries
    assert all(count > 0 for _, count in entries.values()), "every pinned package needs sha256 hashes"
    text = PRODUCTION_LOCK.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert not re.search(r"(^|\s)(-e|--editable|-i|--index-url|--extra-index-url|-f|--find-links|--trusted-host)\b", body, re.M)
    assert not re.search(r"(file:|git\+|hg\+|svn\+|bzr\+|://|\s@\s)", body)
    assert not re.search(r"(/home/|/Users/|/root/|/tmp/|[A-Za-z]:\\)", text)
    assert not re.search(r"(?i)(password|token|secret)\s*[=:]", text)


def test_production_lock_header_records_the_canonical_regeneration_procedure() -> None:
    header = PRODUCTION_LOCK.read_text(encoding="utf-8").split("\n\n", 1)[0]
    for needle in (
        "Python 3.12",
        "pip-tools==7.6.1",
        "--generate-hashes",
        "--output-file=api/requirements-production.lock.txt api/pyproject.toml",
        "docs/operations/production-build-provenance.md",
    ):
        assert needle in header


def test_production_lock_covers_every_direct_api_requirement() -> None:
    entries = _lock_entries(PRODUCTION_LOCK)
    project = tomllib.loads(API_PYPROJECT.read_text(encoding="utf-8"))["project"]
    for spec in project["dependencies"]:
        requirement = Requirement(spec)
        name = _norm(requirement.name)
        assert name in entries, f"direct dependency {requirement.name} missing from the production lock"
        assert requirement.specifier.contains(entries[name][0], prereleases=True), spec


def test_production_lock_excludes_test_only_packages_and_matches_tested_versions() -> None:
    production = _lock_entries(PRODUCTION_LOCK)
    assert not TEST_ONLY_PACKAGES & set(production)
    tested: dict[str, str] = {}
    for line in TEST_LOCK.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==(\S+)", line)
        if match:
            tested[_norm(match[1])] = match[2]
    for name, (version, _) in production.items():
        assert tested.get(name) == version, f"{name}=={version} differs from the S0301-tested version"


def test_no_architecture_specific_dependency_files_exist() -> None:
    api_locks = sorted(p.name for p in (REPO_ROOT / "api").glob("requirements*"))
    assert api_locks == ["requirements-production.lock.txt"]
    assert sorted(p.name for p in (REPO_ROOT / "web").glob("package-lock*.json")) == ["package-lock.json"]


# --- frontend --------------------------------------------------------------


def test_web_dockerfile_keeps_the_committed_lock_and_npm_ci() -> None:
    instructions = _instructions(WEB_DOCKERFILE)
    copy = instructions.index("COPY package.json package-lock.json ./")
    assert instructions[copy + 1] == "RUN npm ci"
    text = "\n".join(instructions)
    assert not re.search(r"\b(npm|yarn|pnpm)\s+(install|i|add|update|upgrade)\b", text)
    assert "ARG BUILDKIT_SBOM_SCAN_STAGE=true" in text


# --- OCI metadata ----------------------------------------------------------


@pytest.mark.parametrize("dockerfile", [API_DOCKERFILE, WEB_DOCKERFILE], ids=lambda p: p.parent.name)
def test_final_image_declares_oci_source_and_revision(dockerfile: Path) -> None:
    stage = "\n".join(_final_stage(dockerfile))
    assert 'ARG ATLAS_SOURCE_REVISION=""' in stage
    assert f'org.opencontainers.image.source="{CANONICAL_SOURCE}"' in stage
    assert 'org.opencontainers.image.revision="${ATLAS_SOURCE_REVISION}"' in stage
    assert "ARG SOURCE_DATE_EPOCH" in stage
    # No clock-derived metadata that would defeat reproducibility.
    assert "org.opencontainers.image.created" not in stage
    assert not re.search(r"\$\(date\b|`date\b", stage)


# --- canonical build and validation scripts --------------------------------


@pytest.mark.parametrize("script", [BUILD_SCRIPT, VALIDATOR], ids=lambda p: p.name)
def test_scripts_use_safe_shell_practices(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "\nset -euo pipefail\n" in text
    assert os.access(script, os.X_OK)
    match = DESTRUCTIVE_OR_PUBLISHING.search(_code(script))
    assert match is None, f"{script.name}: forbidden construct {match.group(0)!r}" if match else ""


def test_build_script_derives_revision_and_timestamp_from_a_clean_head() -> None:
    code = _code(BUILD_SCRIPT)
    assert "status --porcelain" in code
    assert "rev-parse --verify 'HEAD^{commit}'" in code
    assert "log -1 --format=%ct" in code
    assert '--build-arg "ATLAS_SOURCE_REVISION=${revision}"' in code
    assert '--build-arg "SOURCE_DATE_EPOCH=${source_date_epoch}"' in code
    assert "--expect-revision" in code and "does not match HEAD" in code
    assert "SOURCE_DATE_EPOCH in the environment does not match" in code
    # The revision build argument has exactly one, derived, source.
    assert code.count("ATLAS_SOURCE_REVISION=") == 1


def test_build_script_builds_both_images_reproducibly_and_attested() -> None:
    code = _code(BUILD_SCRIPT)
    assert '"${source_dir}/api/Dockerfile"' in code and '"${source_dir}/web/Dockerfile"' in code
    assert "--no-cache" in code
    assert "rewrite-timestamp=true" in code
    assert "type=oci,dest=" in code
    assert "--provenance=false --sbom=false" in code
    assert '"type=provenance,mode=max"' in code
    assert "type=sbom,generator=" in code
    assert PINNED_IMAGE.search(re.search(r'SBOM_GENERATOR="([^"]+)"', code)[1])
    for platform in REQUIRED_PLATFORMS:
        assert platform in code
    assert "must be outside the source checkout" in code


def test_build_script_accepts_only_public_web_inputs() -> None:
    code = _code(BUILD_SCRIPT)
    allowlist = re.search(r"WEB_ARG_NAMES=\(\n(.*?)\n\)", code, re.S)[1].split()
    assert allowlist == [
        "VITE_API_BASE_URL",
        "VITE_ENABLE_ADMIN",
        "VITE_SUPABASE_URL",
        "VITE_SUPABASE_PUBLISHABLE_KEY",
        "VITE_TURNSTILE_SITE_KEY",
    ]
    assert "is not an allowlisted public VITE_* input" in code
    assert "service_role" in code and "sb_secret_" in code


def test_validator_covers_every_mandatory_stage_and_fails_closed() -> None:
    code = _code(VALIDATOR)
    for needle in (
        "tests/test_production_supply_chain_contract.py",
        "imagetools inspect --raw",
        "--require-hashes",
        "pip check",
        "npm-lock-contract",
        "--mode probe",
        "--mode attested",
        "https://spdx.dev/Document",
        "https://slsa.dev/provenance/",
        "org.opencontainers.image.revision",
        "git ls-files -ci --exclude-standard",
        "git diff --check",
    ):
        assert needle in code, needle
    for platform in REQUIRED_PLATFORMS:
        assert platform in code
    assert PINNED_IMAGE.search(re.search(r'BUILDKIT_IMAGE="([^"]+)"', code)[1])
    # A skipped platform can never produce a green result.
    assert "exit 3" in code
    assert code.index("tests/test_production_supply_chain_contract.py") < code.index("--mode probe")
    # Synthetic web inputs only.
    assert "synthetic-ci.supabase.invalid" in code


# --- Buildx platform discovery (S0306) ---------------------------------------

PLATFORM_BLOCK = re.compile(
    r"^# --- builder platform normalization .*?^# --- end builder platform normalization ---$",
    re.S | re.M,
)
GITHUB_RUNNER_PLATFORMS = "linux/amd64*, linux/arm64*, linux/amd64/v2, linux/amd64/v3, linux/386"


def _platform_block() -> str:
    match = PLATFORM_BLOCK.search(VALIDATOR.read_text(encoding="utf-8"))
    assert match, "the validator lost its isolated builder platform normalization block"
    return match.group(0)


def _discover(inspect_output: str) -> tuple[str, dict[str, bool]]:
    """Run the validator's own normalization functions on synthetic inspect output (no Docker)."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the validator's platform functions")
    driver = (
        "set -euo pipefail\n"
        f"{_platform_block()}\n"
        'platforms="$(canonical_builder_platforms)"\n'
        "printf '%s\\n' \"${platforms}\"\n"
        f"for platform in {' '.join(REQUIRED_PLATFORMS)}; do\n"
        '  if builder_has_platform "${platforms}" "${platform}"; then echo "${platform} yes"; '
        'else echo "${platform} no"; fi\n'
        "done\n"
    )
    result = subprocess.run(
        [bash, "-c", driver],
        input=inspect_output,
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
        timeout=30,
    )
    canonical, *verdicts = result.stdout.splitlines()
    return canonical, {line.split()[0]: line.split()[1] == "yes" for line in verdicts}


def _inspect(platforms_line: str) -> str:
    return (
        "Name:          atlas-supply-chain\n"
        "Driver:        docker-container\n"
        "Nodes:\n"
        "Name:                  atlas-supply-chain0\n"
        "Status:                running\n"
        "BuildKit version:      v0.33.1\n"
        f"Platforms:             {platforms_line}\n"
        "Labels:\n"
        " org.mobyproject.buildkit.worker.executor: oci\n"
    )


def test_validator_platform_discovery_goes_through_the_normalization_functions() -> None:
    code = _code(VALIDATOR)
    assert "readonly REQUIRED_PLATFORMS=(linux/amd64 linux/arm64)" in code
    block = _platform_block()
    assert "docker" not in _code_text(block), "normalization must stay a pure string transformation"
    discovery = code[code.index('step "Buildx builder with cross-platform'):code.index('native_platform=')]
    assert 'docker buildx inspect --bootstrap "${BUILDX_BUILDER}"' in discovery
    assert 'canonical_builder_platforms <<<"${builder_inspect}"' in discovery
    assert 'builder_has_platform "${builder_platforms}" "${platform}"' in discovery
    assert 'fail "the builder reported no parseable platforms"' in discovery
    assert 'fail "the builder cannot build required platform(s)' in discovery
    assert "sed -n 's/^Platforms:" not in discovery


def test_buildx_preferred_platform_markers_are_normalized_to_required_platforms() -> None:
    canonical, available = _discover(_inspect(GITHUB_RUNNER_PLATFORMS))
    assert canonical == "linux/amd64,linux/arm64,linux/amd64/v2,linux/amd64/v3,linux/386"
    assert available == {"linux/amd64": True, "linux/arm64": True}


def test_genuinely_missing_arm64_is_still_rejected_despite_decorated_tokens() -> None:
    canonical, available = _discover(_inspect("linux/amd64*, linux/amd64/v2, linux/386"))
    assert canonical == "linux/amd64,linux/amd64/v2,linux/386"
    assert available == {"linux/amd64": True, "linux/arm64": False}


def test_genuinely_missing_amd64_is_still_rejected() -> None:
    _, available = _discover(_inspect("linux/arm64*, linux/arm/v7, linux/arm/v6"))
    assert available == {"linux/amd64": False, "linux/arm64": True}


@pytest.mark.parametrize(
    ("platforms_line", "expected"),
    [
        ("linux/amd64, linux/arm64", {"linux/amd64": True, "linux/arm64": True}),
        ("linux/arm64*,linux/amd64", {"linux/amd64": True, "linux/arm64": True}),
        # An explicit variant keeps meaning its own base platform, nothing else.
        ("linux/arm64/v8, linux/amd64/v2", {"linux/amd64": True, "linux/arm64": True}),
        ("linux/arm/v7, linux/arm/v6", {"linux/amd64": False, "linux/arm64": False}),
        # Look-alikes, doubled markers and stray characters never match exactly.
        ("linux/arm64evil, linux/amd640, xlinux/amd64", {"linux/amd64": False, "linux/arm64": False}),
        ("linux/arm64**, *linux/amd64, linux/amd64*/v2", {"linux/amd64": False, "linux/arm64": False}),
        ("linux/arm64 linux/amd64", {"linux/amd64": False, "linux/arm64": False}),
    ],
)
def test_platform_matching_stays_exact_and_fail_closed(platforms_line: str, expected: dict[str, bool]) -> None:
    _, available = _discover(_inspect(platforms_line))
    assert available == expected


@pytest.mark.parametrize(
    "inspect_output",
    ["", "Name: atlas\nDriver: docker-container\n", _inspect(""), _inspect("*, ,"), _inspect("not-a-platform")],
    ids=["empty", "no-platforms-line", "empty-platforms", "only-markers", "unparseable"],
)
def test_empty_or_unparseable_platform_discovery_yields_no_platform(inspect_output: str) -> None:
    canonical, available = _discover(inspect_output)
    assert canonical == ""
    assert available == {"linux/amd64": False, "linux/arm64": False}


def test_platform_lines_of_every_builder_node_are_combined() -> None:
    output = _inspect("linux/amd64*, linux/386") + _inspect("linux/arm64*, linux/arm/v7")
    canonical, available = _discover(output)
    assert canonical == "linux/amd64,linux/386,linux/arm64,linux/arm/v7"
    assert available == {"linux/amd64": True, "linux/arm64": True}


# --- CI workflow ------------------------------------------------------------


def test_workflow_triggers_and_least_privilege(workflow: dict) -> None:
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"] == {"branches": ["main"]}
    assert "pull_request_target" not in WORKFLOW.read_text(encoding="utf-8")
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        assert job.get("permissions", {"contents": "read"}) == {"contents": "read"}


def test_workflow_has_one_stable_aggregate_check(workflow: dict) -> None:
    assert list(workflow["jobs"]) == [AGGREGATE_CHECK]
    assert workflow["jobs"][AGGREGATE_CHECK]["name"] == AGGREGATE_CHECK


def test_workflow_actions_and_images_are_immutably_pinned(workflow: dict) -> None:
    steps = workflow["jobs"][AGGREGATE_CHECK]["steps"]
    uses = [step["uses"] for step in steps if "uses" in step]
    assert uses
    for reference in uses:
        assert PINNED_ACTION.match(reference), reference
    qemu = next(step for step in steps if step.get("uses", "").startswith("docker/setup-qemu-action@"))
    assert PINNED_IMAGE.match(qemu["with"]["image"])
    assert "arm64" in qemu["with"]["platforms"]
    buildx = next(step for step in steps if step.get("uses", "").startswith("docker/setup-buildx-action@"))
    assert buildx["with"]["driver"] == "docker-container"
    assert PINNED_IMAGE.match(buildx["with"]["driver-opts"].removeprefix("image="))


def test_workflow_validates_statically_before_building_and_never_publishes(workflow: dict) -> None:
    steps = workflow["jobs"][AGGREGATE_CHECK]["steps"]
    runs = [step.get("run", "") for step in steps]
    static = next(i for i, run in enumerate(runs) if "tests/test_production_supply_chain_contract.py" in run)
    gate = next(i for i, run in enumerate(runs) if "scripts/validate-production-supply-chain.sh" in run)
    buildx = next(i for i, step in enumerate(steps) if "setup-buildx-action" in step.get("uses", ""))
    assert static < buildx < gate
    checkout = next(step for step in steps if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] is False
    text = WORKFLOW.read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "secrets." not in body
    assert not re.search(r"login-action|build-push-action|docker\s+(login|push)|push:\s*true|--push\b", body)
    assert not re.search(r"(?i)\bdeploy|docker\s+compose|supabase\s+(db|functions|link)|pg_dump|pg_restore|\bssh\b", body)


# --- documentation ---------------------------------------------------------


def test_provenance_doc_covers_the_contract_and_its_limits() -> None:
    text = PROVENANCE_DOC.read_text(encoding="utf-8")
    for needle in (
        "`application-release-gate`",
        "`production-supply-chain-gate`",
        "api/requirements-production.lock.txt",
        "pip-tools==7.6.1",
        "--generate-hashes",
        "linux/amd64",
        "linux/arm64",
        "scripts/build-production-images.sh",
        "SOURCE_DATE_EPOCH",
        "git rev-parse HEAD",
        "synthetic",
        "attestation manifests",
        "**unsigned**",
        "S0304",
    ):
        assert needle in text, needle
    assert "image manifest digest" in text.lower()
    assert re.search(r"\*index\* digest of attested builds is expected to differ", text)
    assert "does not prove what currently runs in production" in text
    assert not re.search(r"(?i)\b(is|are) (cryptographically )?signed\b", text)
    assert not re.search(r"(?i)SLSA (level|build level) [1-4] (is )?(achieved|met|satisfied)", text)


def test_release_gate_doc_and_readme_point_to_the_supply_chain_contract() -> None:
    gate = GATE_DOC.read_text(encoding="utf-8")
    assert "`production-supply-chain-gate`" in gate
    assert "production-build-provenance.md" in gate
    readme = README.read_text(encoding="utf-8")
    assert "docs/operations/production-build-provenance.md" in readme
    assert "production-supply-chain-gate" in readme

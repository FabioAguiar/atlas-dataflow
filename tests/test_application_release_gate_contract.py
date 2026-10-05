"""Project Spec S0301: static contract of the application CI and release gate.

``.github/workflows/application-ci.yml`` and
``scripts/validate-application-release-gate.sh`` are parsed as YAML/text only;
nothing is executed. The gate proves the repository-side contract (triggers,
least privilege, immutable pins, mandatory checks, no deploy) -- it does not
prove that GitHub ran the workflow or that branch protection requires it.
"""

import os
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "application-ci.yml"
WRAPPER_PATH = REPO_ROOT / "scripts" / "validate-application-release-gate.sh"
GATE_DOC_PATH = REPO_ROOT / "docs" / "operations" / "application-release-gate.md"

AGGREGATE_CHECK = "application-release-gate"
_PINNED_ACTION = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_./-]+)?@[0-9a-f]{40}$")
_FORBIDDEN_RUN_COMMANDS = re.compile(
    r"\b(?:docker\s+(?:push|login|compose\s+up)|ssh|scp|kubectl|supabase|pg_dump|pg_restore|psql"
    r"|deploy|rsync|curl\s+[^\n]*-X\s*(?:POST|PUT|PATCH|DELETE))\b",
    re.IGNORECASE,
)
_DESTRUCTIVE_SHELL = re.compile(
    r"\brm\s+-[A-Za-z]*[rR]|\brmtree\b|\bgit\s+(?:reset|clean|checkout|restore|stash|push|commit|rebase|rm)\b"
    r"|\beval\b|\|\|\s*true\b|--deselect\b|\s-k\s|--ignore(?:-glob)?\b|--lf\b|--reruns?\b"
)
WRAPPER_MANDATORY_FRAGMENTS = (
    "-m pip check",
    '-m pytest -p no:cacheprovider -q -rs\n',
    "npm --prefix web ci",
    "npm --prefix web audit --omit=dev --audit-level=moderate",
    "npm --prefix web audit --audit-level=high",
    "npm --prefix web test -- --retry=0",
    "npm --prefix web run build",
    "'*.tsbuildinfo'",
    "'vite.config.js'",
    "'vite.config.d.ts'",
    "git ls-files --cached --ignored --exclude-standard",
    "git diff --check",
    "git diff --cached --check",
    "bash -n",
    "requirements-test.lock.txt",
)


@pytest.fixture(scope="module")
def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def workflow(workflow_text: str) -> dict:
    return yaml.safe_load(workflow_text)


@pytest.fixture(scope="module")
def wrapper_text() -> str:
    return WRAPPER_PATH.read_text(encoding="utf-8")


def _triggers(workflow: dict) -> dict:
    # PyYAML (YAML 1.1) loads the bare key "on" as boolean True.
    return workflow.get("on", workflow.get(True))


def _steps(workflow: dict):
    for job_id, job in workflow["jobs"].items():
        for step in job.get("steps", []):
            yield job_id, step


def _code_lines(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def test_workflow_triggers_are_pull_request_main_push_and_manual(workflow, workflow_text) -> None:
    triggers = _triggers(workflow)
    assert set(triggers) == {"pull_request", "push", "workflow_dispatch"}
    assert triggers["push"]["branches"] == ["main"]
    assert "pull_request_target" not in workflow_text


def test_workflow_permissions_are_read_only(workflow) -> None:
    assert workflow["permissions"] == {"contents": "read"}
    for job in workflow["jobs"].values():
        permissions = job.get("permissions", {})
        assert all(value in ("read", "none") for value in permissions.values()), permissions


def test_third_party_actions_are_pinned_to_full_commit_shas(workflow) -> None:
    uses = [step["uses"] for _, step in _steps(workflow) if "uses" in step]
    assert uses
    for reference in uses:
        assert _PINNED_ACTION.match(reference), reference


def test_checkouts_do_not_persist_credentials(workflow) -> None:
    checkouts = [step for _, step in _steps(workflow) if step.get("uses", "").startswith("actions/checkout@")]
    assert checkouts
    for step in checkouts:
        assert step.get("with", {}).get("persist-credentials") is False


def test_secret_scan_uses_full_history_redacted_and_verified_gitleaks(workflow) -> None:
    job = workflow["jobs"]["secret-scan"]
    checkout = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    runs = "\n".join(step.get("run", "") for step in job["steps"])
    assert re.fullmatch(r"[0-9a-f]{64}", job["env"]["GITLEAKS_SHA256"])
    assert "sha256sum --check --strict" in runs
    assert "gitleaks git --redact" in runs
    assert "--exit-code 1" in runs


def test_shell_lint_job_runs_shellcheck_on_tracked_scripts(workflow) -> None:
    runs = "\n".join(step.get("run", "") for step in workflow["jobs"]["shell-lint"]["steps"])
    assert "git ls-files -z -- '*.sh'" in runs
    assert "shellcheck" in runs
    assert "exit 1" in runs


def test_aggregate_release_gate_job_has_a_stable_name_and_needs_every_check(workflow) -> None:
    job = workflow["jobs"][AGGREGATE_CHECK]
    assert job["name"] == AGGREGATE_CHECK
    assert set(job["needs"]) == {"secret-scan", "shell-lint"}
    assert set(workflow["jobs"]) == {"secret-scan", "shell-lint", AGGREGATE_CHECK}


def test_release_gate_job_uses_locked_python_312_node_22_and_the_wrapper(workflow) -> None:
    steps = workflow["jobs"][AGGREGATE_CHECK]["steps"]
    python = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    node = next(step for step in steps if step.get("uses", "").startswith("actions/setup-node@"))
    assert python["with"]["python-version"] == "3.12"
    assert node["with"]["node-version"] == "22"
    runs = "\n".join(step.get("run", "") for step in steps)
    assert "-m venv" in runs
    assert "pip install --require-virtualenv -r requirements-test.lock.txt" in runs
    assert runs.strip().endswith("scripts/validate-application-release-gate.sh")
    assert "npm install" not in runs


def test_workflow_uses_no_secrets_artifacts_or_deploy_commands(workflow, workflow_text) -> None:
    assert not re.search(r"\$\{\{[^}]*\bsecrets\b", workflow_text)
    assert "upload-artifact" not in workflow_text
    for _, step in _steps(workflow):
        assert not _FORBIDDEN_RUN_COMMANDS.search(step.get("run", "")), step.get("name")


def test_wrapper_is_executable_strict_and_covers_every_mandatory_check(wrapper_text) -> None:
    assert os.access(WRAPPER_PATH, os.X_OK)
    assert wrapper_text.startswith("#!/usr/bin/env bash\n")
    assert "\nset -euo pipefail\n" in wrapper_text
    for fragment in WRAPPER_MANDATORY_FRAGMENTS:
        assert fragment in wrapper_text, fragment
    for command in ("git", "node", "npm"):
        assert re.search(rf"for cmd in [^\n]*\b{command}\b", wrapper_text), command
    assert '[ "$(id -u)" -ne 0 ]' in wrapper_text


def test_wrapper_has_no_destructive_eval_or_skip_shortcut(wrapper_text) -> None:
    assert _DESTRUCTIVE_SHELL.findall(_code_lines(wrapper_text)) == []


@pytest.mark.parametrize(
    "line",
    [
        "rm -rf web/node_modules",
        "git reset --hard",
        "git clean -fdx",
        'eval "$cmd"',
        "npm --prefix web test || true",
        "python -m pytest --deselect tests/x.py",
        "python -m pytest --ignore=tests/api",
    ],
)
def test_destructive_shell_detector_rejects_unsafe_variants(line: str) -> None:
    assert _DESTRUCTIVE_SHELL.search(line)


def test_gate_documentation_names_the_check_and_does_not_claim_branch_protection() -> None:
    text = GATE_DOC_PATH.read_text(encoding="utf-8")
    assert f"`{AGGREGATE_CHECK}`" in text
    assert "not configured by this repository" in text
    assert not re.search(r"branch protection (?:is|has been) (?:configured|enabled|enforced)", text, re.IGNORECASE)

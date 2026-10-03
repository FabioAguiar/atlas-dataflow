"""Repository hygiene gate: no tracked path may also be ignored.

Git's own ignore engine is the authority (``git ls-files -ci --exclude-standard``),
so the gate covers every ignore category in the current policy without
hard-coding any generated directory name. Git is only invoked read-only: the
index, the working tree and the Git configuration are never touched, and the
contents of offending files are never read.
"""

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MAX_REPORTED_PATHS = 20

TRACKED_IGNORED_COMMAND = ("git", "ls-files", "--cached", "--ignored", "--exclude-standard", "-z")


def _run_git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        list(args),
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def tracked_ignored_paths() -> list[str]:
    result = _run_git(*TRACKED_IGNORED_COMMAND)
    assert result.returncode == 0, (
        f"git ls-files exited with {result.returncode}: {result.stderr.strip()[:500]}"
    )
    return [path for path in result.stdout.split("\0") if path]


def hygiene_violation_message(paths: list[str]) -> str:
    shown = paths[:MAX_REPORTED_PATHS]
    lines = [
        f"tracked ignored count = {len(paths)}",
        "Ignored generated artifacts are still tracked by Git; remove them from the "
        "index (keeping working-tree copies) instead of extending the ignore policy.",
        *(f"  {path}" for path in shown),
    ]
    if len(paths) > len(shown):
        lines.append(f"  ... and {len(paths) - len(shown)} more")
    return "\n".join(lines)


def test_repository_root_is_the_git_work_tree():
    result = _run_git("git", "rev-parse", "--show-toplevel")
    assert result.returncode == 0, result.stderr.strip()[:500]
    assert Path(result.stdout.strip()).resolve() == REPO_ROOT


def test_no_tracked_path_is_ignored_by_current_policy():
    paths = tracked_ignored_paths()
    assert not paths, hygiene_violation_message(paths)


def test_tracked_ignored_paths_are_parsed_from_git_output(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, stdout="a/b.pyc\0dir with space/x.tsbuildinfo\0", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert tracked_ignored_paths() == ["a/b.pyc", "dir with space/x.tsbuildinfo"]
    (args, kwargs), = calls
    assert args == list(TRACKED_IGNORED_COMMAND)
    assert kwargs["cwd"] == REPO_ROOT
    assert kwargs.get("shell", False) is False


def test_git_failure_is_reported_not_treated_as_clean(monkeypatch):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 128, stdout="", stderr="fatal: not a git repository"),
    )

    with pytest.raises(AssertionError, match="exited with 128"):
        tracked_ignored_paths()


def test_violation_message_reports_count_and_bounds_listed_paths():
    paths = [f"generated/file-{index}.bin" for index in range(MAX_REPORTED_PATHS + 5)]

    message = hygiene_violation_message(paths)

    assert f"tracked ignored count = {len(paths)}" in message
    assert paths[MAX_REPORTED_PATHS - 1] in message
    assert paths[MAX_REPORTED_PATHS] not in message
    assert "... and 5 more" in message

"""
Generic, dataset-agnostic release-id allocator (Project Spec S0219).

Allocates a collision-safe `release_id` in canonical `release-YYYYMMDD-NNN`
form from a governed `train-YYYYMMDDTHHMMSSZ` training run id. Read-only:
reserves nothing and writes nothing to the repository -- candidate assembly
(`pipeline/assemble_candidate.py`) provides the second, write-time
collision gate that makes a reservation durable.

Never derives the release date from wall-clock time or a Publisher Run
directory name, and never uses a dataset slug to create an independent
sequence namespace -- the canonical `NNN` sequence is global across every
dataset for a given date.
"""

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_SOURCE_RUN_ID_PATTERN = re.compile(r"^train-(?P<date>[0-9]{8})T[0-9]{6}Z$")
_CANONICAL_RELEASE_ID_PATTERN = re.compile(r"^release-(?P<date>[0-9]{8})-(?P<seq>[0-9]{3})$")

_PROMOTED_RELEASES_PREFIX = "releases"
_CANDIDATE_STAGING_PREFIX = "releases/candidates"
_PUBLISHER_RUNS_PREFIX = "publisher/runs"

_MIN_SEQUENCE = 1
_MAX_SEQUENCE = 999


class ReleaseIdentityAllocationError(ValueError):
    """Raised when a collision-safe release id cannot be allocated."""


def _reserved_sequences_from_dirnames(base: Path, date: str) -> set[int]:
    """Reserved canonical sequences from immediate subdirectory names of `base`.

    Legacy timestamp-style release directory names (for example
    `release-20260710t151619z`) never match `_CANONICAL_RELEASE_ID_PATTERN`
    and are silently ignored -- they must not corrupt canonical sequence
    allocation.
    """
    reserved: set[int] = set()
    if not base.is_dir():
        return reserved
    for entry in base.iterdir():
        if not entry.is_dir():
            continue
        match = _CANONICAL_RELEASE_ID_PATTERN.match(entry.name)
        if match and match.group("date") == date:
            reserved.add(int(match.group("seq")))
    return reserved


def _reserved_sequences_from_promoted_releases(repo_root: Path, date: str) -> set[int]:
    return _reserved_sequences_from_dirnames(repo_root / _PROMOTED_RELEASES_PREFIX, date)


def _reserved_sequences_from_candidates(repo_root: Path, date: str) -> set[int]:
    """Reserved canonical sequences from every dataset's candidate directory.

    Scans candidates for every dataset globally
    (`releases/candidates/*/release-YYYYMMDD-NNN/`) -- never scoped to a
    single dataset slug, so different datasets share one sequence
    namespace for the same date.
    """
    reserved: set[int] = set()
    candidates_root = repo_root / _CANDIDATE_STAGING_PREFIX
    if not candidates_root.is_dir():
        return reserved
    for dataset_dir in candidates_root.iterdir():
        if dataset_dir.is_dir():
            reserved |= _reserved_sequences_from_dirnames(dataset_dir, date)
    return reserved


def _reserved_sequences_from_publisher_runs(repo_root: Path, date: str) -> set[int]:
    """Reserved canonical sequences from Publisher Run validation results.

    Defense in depth only: a `candidate_identity.release_id` recorded in
    `publisher/runs/*/validation-result.json` is treated as reserved when it
    is a syntactically valid canonical release id for the target date --
    regardless of whether that Publisher Run's own validation outcome was
    accepted or rejected, and regardless of whether the candidate directory
    it once referenced still exists. A malformed, missing, or non-canonical
    `release_id` is skipped rather than raised, since this scan never
    inspects a run's directory name and never trusts it as a release id.
    """
    reserved: set[int] = set()
    runs_root = repo_root / _PUBLISHER_RUNS_PREFIX
    if not runs_root.is_dir():
        return reserved
    for run_dir in runs_root.iterdir():
        if not run_dir.is_dir():
            continue
        validation_path = run_dir / "validation-result.json"
        if not validation_path.is_file():
            continue
        try:
            validation_result = json.loads(validation_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, OSError):
            continue
        if not isinstance(validation_result, dict):
            continue
        candidate_identity = validation_result.get("candidate_identity")
        if not isinstance(candidate_identity, dict):
            continue
        release_id = candidate_identity.get("release_id")
        if not isinstance(release_id, str):
            continue
        match = _CANONICAL_RELEASE_ID_PATTERN.match(release_id)
        if match and match.group("date") == date:
            reserved.add(int(match.group("seq")))
    return reserved


def _reserved_sequences_for_date(repo_root: Path, date: str) -> set[int]:
    reserved = _reserved_sequences_from_promoted_releases(repo_root, date)
    reserved |= _reserved_sequences_from_candidates(repo_root, date)
    reserved |= _reserved_sequences_from_publisher_runs(repo_root, date)
    return reserved


def allocate_release_id(source_run_id: str, repo_root: Path | str | None = None) -> str:
    """Allocate the first free canonical `release_id` for `source_run_id`'s date.

    `source_run_id` must be a governed `train-YYYYMMDDTHHMMSSZ` id; the
    returned `release-YYYYMMDD-NNN` id always derives its date from this
    argument, never from wall-clock time. Scans, read-only:

    - promoted releases (`releases/release-YYYYMMDD-NNN/`);
    - every dataset's existing candidates
      (`releases/candidates/*/release-YYYYMMDD-NNN/`);
    - Publisher Run validation results, as defense in depth.

    Different dates never interfere with each other, and this function
    never creates a reservation directory or otherwise modifies the
    repository -- candidate assembly provides the write-time collision gate
    that makes an allocated id durable.
    """
    match = _SOURCE_RUN_ID_PATTERN.match(source_run_id)
    if not match:
        raise ReleaseIdentityAllocationError(
            f"source_run_id must match train-YYYYMMDDTHHMMSSZ, got: {source_run_id!r}"
        )
    date = match.group("date")

    resolved_repo_root = Path(repo_root or _REPO_ROOT).expanduser().resolve()
    reserved = _reserved_sequences_for_date(resolved_repo_root, date)

    for seq in range(_MIN_SEQUENCE, _MAX_SEQUENCE + 1):
        if seq not in reserved:
            return f"release-{date}-{seq:03d}"

    raise ReleaseIdentityAllocationError(
        f"release id sequence exhausted for date {date}: all {_MAX_SEQUENCE} "
        "canonical ids (001..999) are already reserved"
    )

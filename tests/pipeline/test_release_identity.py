import json
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import release_identity  # noqa: E402


RUN_ID = "train-20260818T120000Z"
DATE = "20260818"


def _mkdirs(*paths: Path) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def _write_publisher_run(
    repo_root: Path,
    run_name: str,
    *,
    release_id: str,
    dataset_slug: str = "telco-customer-churn",
    validation_outcome: str = "accepted",
) -> None:
    run_dir = repo_root / "publisher" / "runs" / run_name
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "validation-result.json").write_text(
        json.dumps(
            {
                "schema_version": "release-candidate-validation.v1",
                "validation_outcome": validation_outcome,
                "candidate_identity": {
                    "dataset_slug": dataset_slug,
                    "release_id": release_id,
                    "release_version": "1.0.0-rc.1",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_empty_namespace_allocates_dash_001(tmp_path):
    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-001"


def test_promoted_release_reservation_yields_dash_002(tmp_path):
    _mkdirs(tmp_path / "releases" / "release-20260818-001")

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-002"


def test_same_dataset_candidate_reservation_yields_dash_002(tmp_path):
    _mkdirs(tmp_path / "releases" / "candidates" / "dry-bean" / "release-20260818-001")

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-002"


def test_other_dataset_candidate_reservation_yields_dash_002(tmp_path):
    _mkdirs(tmp_path / "releases" / "candidates" / "telco-customer-churn" / "release-20260818-001")

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-002"


def test_promoted_dash_001_and_candidate_dash_002_yields_dash_003(tmp_path):
    _mkdirs(
        tmp_path / "releases" / "release-20260818-001",
        tmp_path / "releases" / "candidates" / "dry-bean" / "release-20260818-002",
    )

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-003"


def test_valid_publisher_run_reservation_is_skipped(tmp_path):
    # No release/candidate directory exists for -001 at all -- only a
    # Publisher Run validation-result.json references it. The allocator
    # must still treat it as reserved (defense in depth) and skip it.
    _write_publisher_run(tmp_path, "validate-20260818T230644Z", release_id="release-20260818-001")

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-002"


def test_different_date_reservations_do_not_interfere(tmp_path):
    _mkdirs(
        tmp_path / "releases" / "release-20260817-001",
        tmp_path / "releases" / "candidates" / "dry-bean" / "release-20260819-001",
    )

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-001"


def test_legacy_timestamp_release_names_are_ignored(tmp_path):
    _mkdirs(
        tmp_path / "releases" / "release-20260818t120000z",
        tmp_path / "releases" / "candidates" / "telco-customer-churn" / "release-20260818t120000z",
    )

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-001"


def test_invalid_source_run_id_fails(tmp_path):
    with pytest.raises(release_identity.ReleaseIdentityAllocationError):
        release_identity.allocate_release_id("release-20260818-001", repo_root=tmp_path)


def test_sequence_exhaustion_fails_closed(tmp_path):
    releases_root = tmp_path / "releases"
    for seq in range(1, 1000):
        (releases_root / f"release-{DATE}-{seq:03d}").mkdir(parents=True)

    with pytest.raises(release_identity.ReleaseIdentityAllocationError):
        release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path)


def test_allocator_creates_no_files(tmp_path):
    _mkdirs(tmp_path / "releases" / "release-20260818-001")

    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))
    release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*"))

    assert before == after


def test_current_state_fixture_release_and_candidate_dash_001_yields_dash_002(tmp_path):
    """Mirrors the repository's real current state for 2026-08-18: a promoted
    release-20260818-001 and a dry-bean candidate at the same id (Project
    Spec S0219 acceptance criterion 12/21)."""
    _mkdirs(
        tmp_path / "releases" / "release-20260818-001",
        tmp_path / "releases" / "candidates" / "dry-bean" / "release-20260818-001",
    )

    assert release_identity.allocate_release_id(RUN_ID, repo_root=tmp_path) == "release-20260818-002"

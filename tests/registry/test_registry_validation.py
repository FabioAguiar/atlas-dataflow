"""
Registry validation tests for M3-02.

Verifies that the validator accepts valid registry content and rejects
inconsistent published state with predictable, deterministic errors.

Run from the repository root:
    python -m pytest tests/registry/test_registry_validation.py -v
or directly:
    python tests/registry/test_registry_validation.py
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.update import (  # noqa: E402
    allocate_unique_dataset_slug,
    derive_registry_action,
    remove_dataset_entry,
    rename_dataset_slug,
    run as registry_update_run,
)
from registry.validate import RELEASE_ID_PATTERN, validate_registry, validate_registry_file  # noqa: E402

VALID_DIR = Path(__file__).parent / "valid"
INVALID_DIR = Path(__file__).parent / "invalid"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _codes(result: dict) -> set[str]:
    return {e["code"] for e in result["errors"]}


# ---------------------------------------------------------------------------
# Valid fixture
# ---------------------------------------------------------------------------

def test_valid_registry_passes():
    result = validate_registry_file(VALID_DIR / "datasets.json")
    assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Invalid fixtures
# ---------------------------------------------------------------------------

def test_missing_schema_version_rejected():
    registry = _load(INVALID_DIR / "missing-schema-version.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "MISSING_SCHEMA_VERSION" in _codes(result)


def test_missing_dataset_slug_rejected():
    registry = _load(INVALID_DIR / "missing-dataset-slug.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "MISSING_DATASET_SLUG" in _codes(result)


def test_duplicate_slug_rejected():
    registry = _load(INVALID_DIR / "duplicate-slug.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "DUPLICATE_DATASET_SLUG" in _codes(result)


def test_missing_active_release_rejected():
    registry = _load(INVALID_DIR / "missing-active-release.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "MISSING_ACTIVE_RELEASE" in _codes(result)


def test_malformed_active_release_rejected():
    registry = _load(INVALID_DIR / "malformed-active-release.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "INVALID_ACTIVE_RELEASE_FORMAT" in _codes(result)


@pytest.mark.parametrize(
    "release_id",
    ["release-20260616-001", "release-20260712t190939z"],
)
def test_canonical_release_id_pattern_accepts_supported_formats(release_id):
    assert RELEASE_ID_PATTERN.fullmatch(release_id)


@pytest.mark.parametrize(
    "release_id",
    ["", "release-latest", "release-20260712T190939Z", "release-20260712t190939z-extra"],
)
def test_canonical_release_id_pattern_rejects_malformed_formats(release_id):
    assert RELEASE_ID_PATTERN.fullmatch(release_id) is None


def test_missing_public_metadata_rejected():
    registry = _load(INVALID_DIR / "missing-public-metadata.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "MISSING_PUBLIC_METADATA" in _codes(result)


def test_unsafe_metadata_rejected():
    registry = _load(INVALID_DIR / "unsafe-metadata.json")
    result = validate_registry(registry)
    assert result["valid"] is False
    assert "UNSAFE_METADATA_FIELDS" in _codes(result)


# ---------------------------------------------------------------------------
# Inline semantic checks (not covered by fixtures above)
# ---------------------------------------------------------------------------

def test_invalid_slug_format_rejected():
    result = validate_registry({
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "x", "description": "x"},
            "release_id": {"pattern": "x", "description": "x"},
            "active_release": {"description": "x"},
        },
        "datasets": [{
            "dataset_slug": "INVALID SLUG!",
            "active_release": "release-20260616-001",
            "public_metadata": {
                "title": "T", "summary": "S", "domain": "D",
                "visibility": "public", "tags": [],
            },
        }],
    })
    assert result["valid"] is False
    assert "INVALID_DATASET_SLUG_FORMAT" in _codes(result)


def test_non_public_visibility_rejected():
    result = validate_registry({
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "x", "description": "x"},
            "release_id": {"pattern": "x", "description": "x"},
            "active_release": {"description": "x"},
        },
        "datasets": [{
            "dataset_slug": "example-dataset",
            "active_release": "release-20260616-001",
            "public_metadata": {
                "title": "T", "summary": "S", "domain": "D",
                "visibility": "private", "tags": [],
            },
        }],
    })
    assert result["valid"] is False
    assert "INVALID_METADATA_VISIBILITY" in _codes(result)


def test_error_messages_contain_no_filesystem_paths():
    """Validation errors must not leak internal filesystem details."""
    registry = _load(INVALID_DIR / "unsafe-metadata.json")
    result = validate_registry(registry)
    for error in result["errors"]:
        msg = error.get("message", "")
        assert "/internal/" not in msg
        assert "/workspace/" not in msg
        assert "/home/" not in msg


# ---------------------------------------------------------------------------
# allocate_unique_dataset_slug (Project Spec S0042)
# ---------------------------------------------------------------------------

def _registry_with_slugs(*slugs: str) -> dict:
    return {
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [{"dataset_slug": slug} for slug in slugs],
    }


def test_allocate_unique_dataset_slug_empty_registry_returns_base():
    registry = _registry_with_slugs()
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn"


def test_allocate_unique_dataset_slug_returns_base_when_free():
    registry = _registry_with_slugs("bank-marketing")
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn"


def test_allocate_unique_dataset_slug_uses_suffix_one_when_base_taken():
    registry = _registry_with_slugs("telco-customer-churn")
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn1"


def test_allocate_unique_dataset_slug_uses_suffix_two_when_base_and_one_taken():
    registry = _registry_with_slugs("telco-customer-churn", "telco-customer-churn1")
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn2"


def test_allocate_unique_dataset_slug_reuses_gap_deterministically():
    registry = _registry_with_slugs("telco-customer-churn", "telco-customer-churn2")
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn1"


def test_allocate_unique_dataset_slug_ignores_absent_removed_entries():
    # A slug that is simply not present in the current registry (e.g. because
    # its Dataset Detail was removed) must be treated as available, never as
    # permanently reserved.
    registry = _registry_with_slugs("telco-customer-churn2")
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn"
    assert allocate_unique_dataset_slug("telco-customer-churn2", registry) == "telco-customer-churn21"


# ---------------------------------------------------------------------------
# derive_registry_action (Project Spec S0046)
# ---------------------------------------------------------------------------

def test_derive_registry_action_created_when_dataset_entry_created():
    assert derive_registry_action({
        "dataset_entry_created": True,
        "previous_active_release_id": None,
        "release_id": "release-20260710t101438z",
    }) == "created"


def test_derive_registry_action_reused_when_previous_matches_release():
    assert derive_registry_action({
        "dataset_entry_created": False,
        "previous_active_release_id": "release-20260710t101438z",
        "release_id": "release-20260710t101438z",
    }) == "reused"


def test_derive_registry_action_updated_when_previous_differs_and_entry_not_created():
    assert derive_registry_action({
        "dataset_entry_created": False,
        "previous_active_release_id": "release-20260601-001",
        "release_id": "release-20260710t101438z",
    }) == "updated"


def test_derive_registry_action_updated_when_no_previous_active_release_and_entry_not_created():
    # An entry that already existed in the registry (dataset_entry_created is
    # False) but had no active_release yet (previous_active_release_id is
    # None) is a genuine first activation, not a same-release no-op --
    # "updated", not "reused".
    assert derive_registry_action({
        "dataset_entry_created": False,
        "previous_active_release_id": None,
        "release_id": "release-20260710t101438z",
    }) == "updated"


# ---------------------------------------------------------------------------
# remove_dataset_entry (Project Spec S0049)
# ---------------------------------------------------------------------------

def _full_entry(slug: str, release: str) -> dict:
    return {
        "dataset_slug": slug,
        "active_release": release,
        "public_metadata": {
            "title": slug.replace("-", " ").title(),
            "summary": f"Published dataset: {slug}.",
            "domain": "example",
            "visibility": "public",
            "tags": [],
        },
    }


def _write_full_registry(repo_root: Path, entries: list) -> None:
    registry_dir = repo_root / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "datasets.json").write_text(
        json.dumps(
            {
                "schema_version": "atlas.dataflow.registry.v1",
                "conventions": {
                    "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "x"},
                    "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "x"},
                    "active_release": {"description": "x"},
                },
                "datasets": entries,
            }
        ),
        encoding="utf-8",
    )


def test_remove_dataset_entry_removes_only_matching_entry(tmp_path):
    _write_full_registry(
        tmp_path,
        [
            _full_entry("telco-customer-churn", "release-20260616-001"),
            _full_entry("bank-marketing", "release-20260617-001"),
        ],
    )

    result = remove_dataset_entry("telco-customer-churn", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "telco-customer-churn",
        "removed": True,
        "previous_active_release": "release-20260616-001",
        "errors": [],
    }

    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    slugs = [entry["dataset_slug"] for entry in registry["datasets"]]
    assert slugs == ["bank-marketing"]
    # The resulting registry must still validate cleanly after removal.
    assert validate_registry(registry)["valid"] is True


def test_remove_dataset_entry_writes_backup_before_mutating_registry(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    remove_dataset_entry("telco-customer-churn", repo_root=tmp_path)

    backup_content = (tmp_path / "registry" / "datasets.json.previous").read_text(encoding="utf-8")
    assert backup_content == original_content


def test_remove_dataset_entry_missing_slug_returns_structured_failure_and_does_not_mutate(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    result = remove_dataset_entry("does-not-exist", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "does-not-exist",
        "removed": False,
        "previous_active_release": None,
        "errors": [
            {
                "code": "DATASET_DETAIL_NOT_FOUND",
                "field": "dataset_slug",
                "message": "No Dataset Detail was found for the given dataset_slug.",
            }
        ],
    }
    assert (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_remove_dataset_entry_invalid_slug_format_returns_structured_failure():
    result = remove_dataset_entry("Not A Valid Slug!")

    assert result == {
        "dataset_slug": "Not A Valid Slug!",
        "removed": False,
        "previous_active_release": None,
        "errors": [
            {
                "code": "DATASET_SLUG_INVALID",
                "field": "dataset_slug",
                "message": "The dataset_slug is missing or does not match the required pattern.",
            }
        ],
    }


def test_remove_dataset_entry_leaves_release_and_publisher_run_directories_untouched(tmp_path):
    # Removal must only ever touch registry/datasets.json (and its backup) --
    # never releases/, publisher/runs/, contracts, notebooks, or model
    # artifacts, all of which live entirely outside the registry file.
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    release_dir = tmp_path / "releases" / "release-20260616-001"
    release_dir.mkdir(parents=True)
    (release_dir / "manifest.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "publisher" / "runs" / "some-run"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = remove_dataset_entry("telco-customer-churn", repo_root=tmp_path)

    assert result["removed"] is True
    assert (release_dir / "manifest.json").is_file()
    assert (run_dir / "manifest.json").is_file()


def test_remove_dataset_entry_frees_slug_for_reallocation(tmp_path):
    # After removal, allocate_unique_dataset_slug must offer the removed
    # slug again rather than treating it as permanently reserved.
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])

    remove_dataset_entry("telco-customer-churn", repo_root=tmp_path)

    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    assert allocate_unique_dataset_slug("telco-customer-churn", registry) == "telco-customer-churn"


# ---------------------------------------------------------------------------
# rename_dataset_slug (Project Spec S0051)
# ---------------------------------------------------------------------------

def test_rename_dataset_slug_updates_only_matching_entry_dataset_slug(tmp_path):
    _write_full_registry(
        tmp_path,
        [
            _full_entry("telco-customer-churn", "release-20260616-001"),
            _full_entry("bank-marketing", "release-20260617-001"),
        ],
    )

    result = rename_dataset_slug("telco-customer-churn", "telco-churn-renamed", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "telco-customer-churn",
        "new_dataset_slug": "telco-churn-renamed",
        "renamed": True,
        "errors": [],
    }

    registry = json.loads((tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8"))
    renamed_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-churn-renamed")
    other_entry = next(e for e in registry["datasets"] if e["dataset_slug"] == "bank-marketing")

    # active_release and public_metadata for the renamed entry are preserved.
    assert renamed_entry["active_release"] == "release-20260616-001"
    assert renamed_entry["public_metadata"] == _full_entry("telco-customer-churn", "release-20260616-001")["public_metadata"]
    # The other entry is untouched.
    assert other_entry == _full_entry("bank-marketing", "release-20260617-001")
    assert validate_registry(registry)["valid"] is True


def test_rename_dataset_slug_persists_injected_canonical_update_timestamp(tmp_path):
    _write_full_registry(
        tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")]
    )

    result = rename_dataset_slug(
        "telco-customer-churn",
        "telco-churn-renamed",
        repo_root=tmp_path,
        updated_at="2026-07-12T21:30:00Z",
    )

    assert result["renamed"] is True
    registry = _load(tmp_path / "registry" / "datasets.json")
    assert registry["datasets"][0]["dataset_detail_updated_at"] == "2026-07-12T21:30:00Z"


def test_registry_rejects_non_utc_dataset_detail_update_timestamp():
    entry = _full_entry("telco-customer-churn", "release-20260616-001")
    entry["dataset_detail_updated_at"] = "2026-07-12"

    result = validate_registry({
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [entry],
    })

    assert result["valid"] is False
    assert "INVALID_DATASET_DETAIL_UPDATED_AT" in _codes(result)


def test_rename_dataset_slug_writes_backup_before_mutating_registry(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    rename_dataset_slug("telco-customer-churn", "telco-churn-renamed", repo_root=tmp_path)

    backup_content = (tmp_path / "registry" / "datasets.json.previous").read_text(encoding="utf-8")
    assert backup_content == original_content


def test_rename_dataset_slug_rejects_duplicate_target_and_does_not_mutate(tmp_path):
    _write_full_registry(
        tmp_path,
        [
            _full_entry("telco-customer-churn", "release-20260616-001"),
            _full_entry("bank-marketing", "release-20260617-001"),
        ],
    )
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    result = rename_dataset_slug("telco-customer-churn", "bank-marketing", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "telco-customer-churn",
        "new_dataset_slug": "bank-marketing",
        "renamed": False,
        "errors": [
            {
                "code": "DATASET_SLUG_ALREADY_EXISTS",
                "field": "new_dataset_slug",
                "message": "Another Dataset Detail already uses this dataset_slug.",
            }
        ],
    }
    assert (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_rename_dataset_slug_allows_the_original_slug_of_the_edited_row():
    # Renaming a slug to itself is a no-op, distinct from a duplicate with
    # another entry, and is rejected with its own dedicated error code.
    result = rename_dataset_slug("telco-customer-churn", "telco-customer-churn")

    assert result == {
        "dataset_slug": "telco-customer-churn",
        "new_dataset_slug": "telco-customer-churn",
        "renamed": False,
        "errors": [
            {
                "code": "DATASET_SLUG_UNCHANGED",
                "field": "new_dataset_slug",
                "message": "The new_dataset_slug must differ from the current dataset_slug.",
            }
        ],
    }


def test_rename_dataset_slug_rejects_invalid_target_format_and_does_not_mutate(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    result = rename_dataset_slug("telco-customer-churn", "Not A Valid Slug!", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "telco-customer-churn",
        "new_dataset_slug": "Not A Valid Slug!",
        "renamed": False,
        "errors": [
            {
                "code": "NEW_DATASET_SLUG_INVALID",
                "field": "new_dataset_slug",
                "message": "The new_dataset_slug is missing or does not match the required pattern.",
            }
        ],
    }
    assert (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_rename_dataset_slug_rejects_invalid_source_format():
    result = rename_dataset_slug("Not A Valid Slug!", "telco-churn-renamed")

    assert result == {
        "dataset_slug": "Not A Valid Slug!",
        "new_dataset_slug": "telco-churn-renamed",
        "renamed": False,
        "errors": [
            {
                "code": "DATASET_SLUG_INVALID",
                "field": "dataset_slug",
                "message": "The dataset_slug is missing or does not match the required pattern.",
            }
        ],
    }


def test_rename_dataset_slug_rejects_missing_source_slug_and_does_not_mutate(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    original_content = (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8")

    result = rename_dataset_slug("does-not-exist", "does-not-exist-renamed", repo_root=tmp_path)

    assert result == {
        "dataset_slug": "does-not-exist",
        "new_dataset_slug": "does-not-exist-renamed",
        "renamed": False,
        "errors": [
            {
                "code": "DATASET_DETAIL_NOT_FOUND",
                "field": "dataset_slug",
                "message": "No Dataset Detail was found for the given dataset_slug.",
            }
        ],
    }
    assert (tmp_path / "registry" / "datasets.json").read_text(encoding="utf-8") == original_content
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


def test_rename_dataset_slug_leaves_release_and_publisher_run_directories_untouched(tmp_path):
    _write_full_registry(tmp_path, [_full_entry("telco-customer-churn", "release-20260616-001")])
    release_dir = tmp_path / "releases" / "release-20260616-001"
    release_dir.mkdir(parents=True)
    (release_dir / "manifest.json").write_text("{}", encoding="utf-8")
    run_dir = tmp_path / "publisher" / "runs" / "some-run"
    run_dir.mkdir(parents=True)
    (run_dir / "manifest.json").write_text("{}", encoding="utf-8")

    result = rename_dataset_slug("telco-customer-churn", "telco-churn-renamed", repo_root=tmp_path)

    assert result["renamed"] is True
    assert (release_dir / "manifest.json").is_file()
    assert (run_dir / "manifest.json").is_file()


def test_rename_dataset_slug_rebinds_all_slug_keyed_state(tmp_path):
    old_slug = "telco-customer-churn"
    new_slug = "telco-churn-renamed"
    _write_full_registry(tmp_path, [_full_entry(old_slug, "release-20260616-001")])

    artifact_paths = [
        ("profile-drafts", ".json"),
        ("profile-drafts", ".json.previous"),
        ("profile-snapshots", ".json"),
        ("profile-snapshots", ".json.previous"),
        ("profile-publications", ".json"),
    ]
    for directory, suffix in artifact_paths:
        path = tmp_path / "registry" / directory / f"{old_slug}{suffix}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"dataset_slug": old_slug, "media_ref": "media/card.png"}), encoding="utf-8")

    evidence_path = tmp_path / "registry" / "profile-snapshots" / f"{old_slug}.evidence.json"
    evidence_path.write_text(json.dumps({
        "dataset_slug": old_slug,
        "snapshot_identifier": f"{old_slug}@2026-07-12T00:00:00Z",
        "draft_source_reference": {"path": f"registry/profile-drafts/{old_slug}.json"},
    }), encoding="utf-8")

    predict_views = _load(Path(__file__).parent / "predict-views" / "valid" / "predict-views.json")
    (tmp_path / "registry" / "predict-views.json").write_text(json.dumps(predict_views), encoding="utf-8")
    customizations = {
        "schema_version": "atlas.dataflow.predict-view-customizations.v1",
        "predict_view_customizations": [{"view_id": "churn-risk-overview", "dataset_slug": old_slug}],
    }
    (tmp_path / "registry" / "predict-view-customizations.json").write_text(
        json.dumps(customizations), encoding="utf-8"
    )

    result = rename_dataset_slug(old_slug, new_slug, repo_root=tmp_path)

    assert result["renamed"] is True
    for directory, suffix in artifact_paths:
        assert not (tmp_path / "registry" / directory / f"{old_slug}{suffix}").exists()
        rebound = _load(tmp_path / "registry" / directory / f"{new_slug}{suffix}")
        assert rebound == {"dataset_slug": new_slug, "media_ref": "media/card.png"}
    evidence = _load(tmp_path / "registry" / "profile-snapshots" / f"{new_slug}.evidence.json")
    assert evidence["dataset_slug"] == new_slug
    assert evidence["snapshot_identifier"].startswith(f"{new_slug}@")
    assert evidence["draft_source_reference"]["path"] == f"registry/profile-drafts/{new_slug}.json"
    rebound_views = _load(tmp_path / "registry" / "predict-views.json")
    assert rebound_views["predict_views"][0]["dataset_slug"] == new_slug
    assert rebound_views["predict_views"][0]["binding"]["dataset_slug"] == new_slug
    rebound_customizations = _load(tmp_path / "registry" / "predict-view-customizations.json")
    assert rebound_customizations["predict_view_customizations"][0]["dataset_slug"] == new_slug


def test_rename_dataset_slug_rejects_existing_target_artifact_before_any_mutation(tmp_path):
    old_slug = "telco-customer-churn"
    new_slug = "telco-churn-renamed"
    _write_full_registry(tmp_path, [_full_entry(old_slug, "release-20260616-001")])
    registry_path = tmp_path / "registry" / "datasets.json"
    original_registry = registry_path.read_bytes()
    drafts = tmp_path / "registry" / "profile-drafts"
    drafts.mkdir(parents=True)
    (drafts / f"{old_slug}.json").write_text(json.dumps({"dataset_slug": old_slug}), encoding="utf-8")
    target_content = json.dumps({"dataset_slug": new_slug, "owner": "unrelated"})
    (drafts / f"{new_slug}.json").write_text(target_content, encoding="utf-8")

    result = rename_dataset_slug(old_slug, new_slug, repo_root=tmp_path)

    assert result["renamed"] is False
    assert result["errors"][0]["code"] == "DATASET_SLUG_ARTIFACT_TARGET_EXISTS"
    assert registry_path.read_bytes() == original_registry
    assert (drafts / f"{old_slug}.json").exists()
    assert (drafts / f"{new_slug}.json").read_text(encoding="utf-8") == target_content
    assert not (tmp_path / "registry" / "datasets.json.previous").exists()


# ---------------------------------------------------------------------------
# run() predict-view materialization write-failure rollback (Project Spec S0098)
# ---------------------------------------------------------------------------

def test_run_rolls_back_dataset_registry_when_predict_views_write_fails(tmp_path):
    dataset_slug = "telco-customer-churn"
    release_id = "release-20260102-011"
    _write_full_registry(tmp_path, [])

    # A directory at registry/predict-views.json's path is readable as {}
    # (tolerated as an empty predict-view registry) but not writable as a
    # file -- this forces the predict-view write step specifically to fail
    # with OSError, without needing to mock the filesystem.
    (tmp_path / "registry" / "predict-views.json").mkdir()
    (tmp_path / "registry" / "predict-view-customizations.json").write_text(
        json.dumps({"schema_version": "atlas.dataflow.predict-view-customizations.v1", "predict_view_customizations": []}),
        encoding="utf-8",
    )

    release_dir = tmp_path / "releases" / release_id
    release_dir.mkdir(parents=True)
    (release_dir / "public-context.json").write_text(
        json.dumps({
            "schema_version": "1.0.0", "dataset_slug": dataset_slug, "title": "T",
            "description": "D", "domain": "general",
            "predict_views": [{
                "schema_version": "1.0.0", "view_id": "churn-risk-overview", "dataset_slug": dataset_slug,
                "display": {"title": "T", "summary": "S"},
                "intent": {"prediction_goal": "G", "audience": "A"},
                "binding": {"dataset_slug": dataset_slug, "release": {"mode": "active"}},
                "contract_precedence": {
                    "canonical_contracts_are_source_of_truth": True,
                    "view_metadata_defines_runtime_validation": False,
                    "view_metadata_duplicates_contract": False,
                },
            }],
        }),
        encoding="utf-8",
    )
    (release_dir / "manifest.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    run_dir = tmp_path / "publisher" / "runs" / "run-write-fail"
    run_dir.mkdir(parents=True)
    (run_dir / "promotion-result.json").write_text(
        json.dumps({
            "promotion_outcome": "promoted",
            "candidate_identity": {"dataset_slug": dataset_slug, "release_id": release_id},
        }),
        encoding="utf-8",
    )

    datasets_path = tmp_path / "registry" / "datasets.json"
    datasets_before = datasets_path.read_bytes()

    with pytest.raises(RuntimeError):
        registry_update_run(str(run_dir), repo_root=tmp_path)

    assert datasets_path.read_bytes() == datasets_before


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # remove_dataset_entry's tests use pytest's tmp_path fixture (Project
    # Spec S0049), which the previous manual no-argument test list/runner
    # above could not support -- delegate to pytest itself instead, matching
    # tests/api/test_admin_run_listing.py's own standalone-runner convention.
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))

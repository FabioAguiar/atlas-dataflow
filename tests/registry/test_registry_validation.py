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

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.update import allocate_unique_dataset_slug, derive_registry_action  # noqa: E402
from registry.validate import validate_registry, validate_registry_file  # noqa: E402

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
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_valid_registry_passes,
        test_missing_schema_version_rejected,
        test_missing_dataset_slug_rejected,
        test_duplicate_slug_rejected,
        test_missing_active_release_rejected,
        test_malformed_active_release_rejected,
        test_missing_public_metadata_rejected,
        test_unsafe_metadata_rejected,
        test_invalid_slug_format_rejected,
        test_non_public_visibility_rejected,
        test_error_messages_contain_no_filesystem_paths,
        test_allocate_unique_dataset_slug_empty_registry_returns_base,
        test_allocate_unique_dataset_slug_returns_base_when_free,
        test_allocate_unique_dataset_slug_uses_suffix_one_when_base_taken,
        test_allocate_unique_dataset_slug_uses_suffix_two_when_base_and_one_taken,
        test_allocate_unique_dataset_slug_reuses_gap_deterministically,
        test_allocate_unique_dataset_slug_ignores_absent_removed_entries,
        test_derive_registry_action_created_when_dataset_entry_created,
        test_derive_registry_action_reused_when_previous_matches_release,
        test_derive_registry_action_updated_when_previous_differs_and_entry_not_created,
        test_derive_registry_action_updated_when_no_previous_active_release_and_entry_not_created,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
            passed += 1
        except AssertionError as exc:
            print(f"  FAIL  {t.__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)

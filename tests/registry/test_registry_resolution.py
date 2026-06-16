"""
Registry resolution tests for M3-03.

Verifies that the resolver returns the declared active_release for known dataset
slugs, rejects unknown slugs with DATASET_UNAVAILABLE, rejects entries with no
valid active_release with RELEASE_UNAVAILABLE, and uses no heuristic discovery.

Run from the repository root:
    python -m pytest tests/registry/test_registry_resolution.py -v
or directly:
    python tests/registry/test_registry_resolution.py
"""

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.resolve import (  # noqa: E402
    DatasetUnavailableError,
    RegistryInvalidError,
    ReleaseUnavailableError,
    ResolvedDataset,
    _resolve_from_entries,
    resolve_dataset,
)

_VALID_ENTRY = {
    "dataset_slug": "example-dataset",
    "active_release": "release-20260616-001",
    "public_metadata": {
        "title": "Example Dataset",
        "summary": "Fixture for resolution tests.",
        "domain": "example",
        "visibility": "public",
        "tags": ["example"],
    },
}

_BASE_REGISTRY = {
    "schema_version": "atlas.dataflow.registry.v1",
    "conventions": {
        "dataset_slug": {"pattern": "x", "description": "x"},
        "release_id": {"pattern": "x", "description": "x"},
        "active_release": {"description": "x"},
    },
    "datasets": [_VALID_ENTRY],
}


def _write_registry(tmp: Path, data: dict) -> Path:
    path = tmp / "datasets.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Valid resolution
# ---------------------------------------------------------------------------

def test_known_dataset_resolves():
    """Known dataset_slug resolves to its declared active_release."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        result = resolve_dataset("example-dataset", registry_path=path)
    assert isinstance(result, ResolvedDataset)
    assert result.dataset_slug == "example-dataset"
    assert result.active_release == "release-20260616-001"


def test_resolved_active_release_is_registry_declared_value():
    """The resolved active_release is the declared field value, not derived."""
    registry = {
        **_BASE_REGISTRY,
        "datasets": [
            {
                "dataset_slug": "prod-data",
                "active_release": "release-20260601-002",
                "public_metadata": {
                    "title": "T", "summary": "S", "domain": "D",
                    "visibility": "public", "tags": [],
                },
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), registry)
        result = resolve_dataset("prod-data", registry_path=path)
    assert result.active_release == "release-20260601-002"


# ---------------------------------------------------------------------------
# Error conditions
# ---------------------------------------------------------------------------

def test_unknown_dataset_slug_raises_dataset_unavailable():
    """Unknown dataset_slug raises DatasetUnavailableError with no silent fallback."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("does-not-exist", registry_path=path)
        except DatasetUnavailableError:
            raised = True
    assert raised, "Expected DatasetUnavailableError for unknown slug"


def test_dataset_unavailable_error_code():
    """DatasetUnavailableError carries the DATASET_UNAVAILABLE error code."""
    assert DatasetUnavailableError.code == "DATASET_UNAVAILABLE"


def test_missing_active_release_raises_release_unavailable():
    """Entry with no valid active_release raises ReleaseUnavailableError."""
    entries = [
        {
            "dataset_slug": "broken-dataset",
            "public_metadata": {
                "title": "T", "summary": "S", "domain": "D",
                "visibility": "public", "tags": [],
            },
            # active_release intentionally absent
        }
    ]
    raised = False
    try:
        _resolve_from_entries("broken-dataset", entries)
    except ReleaseUnavailableError:
        raised = True
    assert raised, "Expected ReleaseUnavailableError for missing active_release"


def test_malformed_active_release_raises_release_unavailable():
    """Entry with malformed active_release raises ReleaseUnavailableError."""
    entries = [
        {
            "dataset_slug": "broken-dataset",
            "active_release": "latest",  # not a valid release-YYYYMMDD-NNN value
            "public_metadata": {
                "title": "T", "summary": "S", "domain": "D",
                "visibility": "public", "tags": [],
            },
        }
    ]
    raised = False
    try:
        _resolve_from_entries("broken-dataset", entries)
    except ReleaseUnavailableError:
        raised = True
    assert raised, "Expected ReleaseUnavailableError for malformed active_release"


def test_release_unavailable_error_code():
    """ReleaseUnavailableError carries the RELEASE_UNAVAILABLE error code."""
    assert ReleaseUnavailableError.code == "RELEASE_UNAVAILABLE"


def test_invalid_registry_raises_registry_invalid():
    """Resolver raises RegistryInvalidError when registry fails M3-02 validation."""
    broken = {
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [
            {
                # missing dataset_slug
                "active_release": "release-20260616-001",
                "public_metadata": {
                    "title": "T", "summary": "S", "domain": "D",
                    "visibility": "public", "tags": [],
                },
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), broken)
        raised = False
        try:
            resolve_dataset("any-slug", registry_path=path)
        except RegistryInvalidError:
            raised = True
    assert raised, "Expected RegistryInvalidError when registry is invalid"


# ---------------------------------------------------------------------------
# Proof of absence of heuristic discovery
# ---------------------------------------------------------------------------

def test_resolver_uses_exact_slug_match_not_prefix():
    """
    Proof-of-absence: resolver uses exact string match for dataset_slug.

    "example" is a prefix of "example-dataset" — it must not match.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("example", registry_path=path)
        except DatasetUnavailableError:
            raised = True
    assert raised, "Partial slug 'example' must not match 'example-dataset'"


def test_resolver_uses_exact_slug_match_not_suffix():
    """Proof-of-absence: suffix match must not resolve as a known slug."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("dataset", registry_path=path)
        except DatasetUnavailableError:
            raised = True
    assert raised, "Suffix slug 'dataset' must not match 'example-dataset'"


def test_resolver_does_not_scan_directory_for_active_release():
    """
    Proof-of-absence: the resolver uses only the explicitly passed registry file.

    A second registry file is placed in the same directory with a different
    active_release value. The resolver must return the value from the file
    it was given, not from any directory scan.
    """
    registry_a = {
        **_BASE_REGISTRY,
        "datasets": [
            {
                "dataset_slug": "example-dataset",
                "active_release": "release-20260616-001",
                "public_metadata": {
                    "title": "A", "summary": "A", "domain": "D",
                    "visibility": "public", "tags": [],
                },
            }
        ],
    }
    registry_b = {
        **_BASE_REGISTRY,
        "datasets": [
            {
                "dataset_slug": "example-dataset",
                "active_release": "release-20260101-999",
                "public_metadata": {
                    "title": "B", "summary": "B", "domain": "D",
                    "visibility": "public", "tags": [],
                },
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path_a = Path(tmp) / "datasets.json"
        path_b = Path(tmp) / "datasets-other.json"
        path_a.write_text(json.dumps(registry_a), encoding="utf-8")
        path_b.write_text(json.dumps(registry_b), encoding="utf-8")
        result = resolve_dataset("example-dataset", registry_path=path_a)

    assert result.active_release == "release-20260616-001", (
        "Resolver returned a different active_release — possible directory scan"
    )


def test_no_fallback_to_global_artifact_for_unknown_slug():
    """
    Proof-of-absence: unknown slug returns DatasetUnavailableError, not a fallback
    to a global dataset or default behavior.
    """
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        raised = False
        try:
            resolve_dataset("global-default", registry_path=path)
        except DatasetUnavailableError:
            raised = True
    assert raised, "Unknown slug must not silently resolve to a fallback"


# ---------------------------------------------------------------------------
# Error output sanitization
# ---------------------------------------------------------------------------

def test_dataset_unavailable_error_message_is_sanitized():
    """DatasetUnavailableError must not expose registry paths or internal details."""
    with tempfile.TemporaryDirectory() as tmp:
        path = _write_registry(Path(tmp), _BASE_REGISTRY)
        try:
            resolve_dataset("nonexistent-slug", registry_path=path)
        except DatasetUnavailableError as exc:
            msg = str(exc)
            assert str(tmp) not in msg, "Error must not expose the registry directory path"
            assert str(path) not in msg, "Error must not expose the registry file path"


def test_release_unavailable_error_message_is_sanitized():
    """ReleaseUnavailableError must not expose internal details."""
    entries = [{"dataset_slug": "x", "public_metadata": {}}]
    try:
        _resolve_from_entries("x", entries)
    except ReleaseUnavailableError as exc:
        msg = str(exc)
        assert "/home/" not in msg
        assert "/workspace/" not in msg
        assert "/internal/" not in msg


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    tests = [
        test_known_dataset_resolves,
        test_resolved_active_release_is_registry_declared_value,
        test_unknown_dataset_slug_raises_dataset_unavailable,
        test_dataset_unavailable_error_code,
        test_missing_active_release_raises_release_unavailable,
        test_malformed_active_release_raises_release_unavailable,
        test_release_unavailable_error_code,
        test_invalid_registry_raises_registry_invalid,
        test_resolver_uses_exact_slug_match_not_prefix,
        test_resolver_uses_exact_slug_match_not_suffix,
        test_resolver_does_not_scan_directory_for_active_release,
        test_no_fallback_to_global_artifact_for_unknown_slug,
        test_dataset_unavailable_error_message_is_sanitized,
        test_release_unavailable_error_message_is_sanitized,
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
        except Exception as exc:
            print(f"  ERROR {t.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)

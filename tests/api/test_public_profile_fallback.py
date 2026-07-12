"""
Public profile fallback generation tests for M34-05 validation evidence.

Exercises api/public_profile_fallback.py's generate_fallback_profile and
api/public_profile_loader.py's load_dataset_profile. Generator, loader outcome,
missing-optional-artifact, and non-persistence tests use an isolated fake
repository root (tempfile.TemporaryDirectory), so authored draft state in
the checkout cannot affect fallback expectations and no test writes into
real registry paths.

Run from the repository root:
    python -m pytest tests/api/test_public_profile_fallback.py -v
or directly:
    python tests/api/test_public_profile_fallback.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import public_profile_fallback  # noqa: E402
import public_profile_loader  # noqa: E402
from public_profile_fallback import generate_fallback_profile  # noqa: E402
from public_profile_loader import load_dataset_profile  # noqa: E402
from registry.dataset_public_profile_store import create_draft  # noqa: E402
from registry.resolve import DatasetUnavailableError  # noqa: E402


# ---------------------------------------------------------------------------
# Isolated fixture generator coverage
# ---------------------------------------------------------------------------

def test_unknown_dataset_slug_propagates_dataset_unavailable_error():
    try:
        generate_fallback_profile("does-not-exist-in-registry")
        assert False, "expected DatasetUnavailableError"
    except DatasetUnavailableError:
        pass


# ---------------------------------------------------------------------------
# Isolated fixture: missing optional artifacts and draft-vs-fallback envelope
# ---------------------------------------------------------------------------

_FAKE_RELEASE_ID = "release-20260101-001"

_FAKE_METRICS = {
    "schema_version": "metrics.v1",
    "dataset_slug": "fixture-dataset",
    "release_id": _FAKE_RELEASE_ID,
    "evaluation": {
        "split": "test",
        "sample_size": 100,
        "metrics": {"accuracy": 0.8, "f1_score": 0.75},
    },
}

_FAKE_MODEL_CARD = {
    "schema_version": "model-card.v1",
    "dataset_slug": "fixture-dataset",
    "release_id": _FAKE_RELEASE_ID,
    "model_summary": "Fixture model.",
    "problem_type": "binary_classification",
    "prediction_target": "fixture_target",
}

_FAKE_REGISTRY = {
    "schema_version": "atlas.dataflow.registry.v1",
    "datasets": [
        {
            "dataset_slug": "fixture-dataset",
            "active_release": _FAKE_RELEASE_ID,
            "public_metadata": {
                "title": "Fixture Dataset",
                "summary": "Fixture for fallback generator tests.",
                "domain": "telco",
                "visibility": "public",
                "tags": ["telco"],
            },
        },
        # Fixture datasets below exercise the generalized icon-derivation
        # rule (api/public_profile_fallback.py's _DOMAIN_ICON_RULES) added
        # for M37-02, without touching the real registry/datasets.json
        # (out of scope for this issue) and without requiring a distinct
        # release package: registry entries may share an active_release,
        # since load_public_metrics/load_public_model_card key only on
        # active_release, not dataset_slug.
        {
            "dataset_slug": "fixture-dataset-healthcare",
            "active_release": _FAKE_RELEASE_ID,
            "public_metadata": {
                "title": "Fixture Healthcare Dataset",
                "summary": "Fixture for icon-generalization regression tests.",
                "domain": "healthcare",
                "visibility": "public",
                "tags": ["healthcare"],
            },
        },
        {
            "dataset_slug": "fixture-dataset-unrecognized-domain",
            "active_release": _FAKE_RELEASE_ID,
            "public_metadata": {
                "title": "Fixture Unrecognized-Domain Dataset",
                "summary": "Fixture for generic-icon-fallback regression tests.",
                "domain": "aerospace",
                "visibility": "public",
                "tags": ["aerospace"],
            },
        },
    ],
}


def _build_fake_repo(tmp_root: Path, manifest_artifacts: list) -> Path:
    """Build a fake repo root with registry, one release, and the real schema.

    manifest_artifacts controls which of metrics/model_card artifacts the
    release's manifest.json declares, so a given test can omit one to
    exercise deterministic omission.
    """
    (tmp_root / "registry").mkdir(parents=True)
    (tmp_root / "registry" / "datasets.json").write_text(
        json.dumps(_FAKE_REGISTRY), encoding="utf-8"
    )

    contracts_dir = tmp_root / "contracts"
    contracts_dir.mkdir()
    shutil.copy2(
        REPO_ROOT / "contracts" / "dataset-public-profile.schema.json",
        contracts_dir / "dataset-public-profile.schema.json",
    )

    release_dir = tmp_root / "releases" / _FAKE_RELEASE_ID
    release_dir.mkdir(parents=True)
    (release_dir / "manifest.json").write_text(
        json.dumps({"artifacts": manifest_artifacts}), encoding="utf-8"
    )

    if any(a["role"] == "metrics" for a in manifest_artifacts):
        metrics_dir = release_dir / "metrics"
        metrics_dir.mkdir()
        (metrics_dir / "metrics.json").write_text(
            json.dumps(_FAKE_METRICS), encoding="utf-8"
        )

    if any(a["role"] == "model_card" for a in manifest_artifacts):
        (release_dir / "model-card.json").write_text(
            json.dumps(_FAKE_MODEL_CARD), encoding="utf-8"
        )

    return tmp_root


_FULL_MANIFEST_ARTIFACTS = [
    {"role": "metrics", "reference": "metrics/metrics.json"},
    {"role": "model_card", "reference": "model-card.json"},
]


def test_fixture_fallback_is_schema_valid_deterministic_and_uses_safe_derivations():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        first = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)
        second = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)

    assert first == second
    assert first["profile"]["dataset_slug"] == "fixture-dataset"
    assert first["profile"]["home_card"] == {
        "icon": "telecom",
        "primary_metric_key": "f1_score",
    }
    assert first["profile"]["result_card"]["model_label"] == (
        "Binary Classification: fixture_target"
    )
    assert first["sources_used"] == {"metrics": True, "model_card": True}


def test_missing_metrics_artifact_omits_primary_metric_key_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(
            Path(tmp),
            manifest_artifacts=[{"role": "model_card", "reference": "model-card.json"}],
        )
        result = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)

    assert result["sources_used"]["metrics"] is False
    assert "primary_metric_key" not in result["profile"]["home_card"]
    assert result["profile"]["result_card"]["model_label"] == (
        "Binary Classification: fixture_target"
    )


def test_missing_model_card_artifact_omits_model_label_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(
            Path(tmp),
            manifest_artifacts=[{"role": "metrics", "reference": "metrics/metrics.json"}],
        )
        result = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)

    assert result["sources_used"]["model_card"] is False
    assert "result_card" not in result["profile"]
    assert result["profile"]["home_card"]["primary_metric_key"] == "f1_score"


def test_invalid_json_model_card_omits_model_label_deterministically():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        (fake_repo / "releases" / _FAKE_RELEASE_ID / "model-card.json").write_text(
            "not valid json", encoding="utf-8"
        )
        result = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)

    assert result["sources_used"]["model_card"] is True
    assert "result_card" not in result["profile"]


def test_fixture_healthcare_domain_resolves_to_a_curated_non_generic_icon():
    """A dataset domain outside telecom/bank must not be stuck at "generic"
    (M37-02 decision-02): the generalized _DOMAIN_ICON_RULES recognizes
    "healthcare" and resolves it to Atlas's curated "heart" icon."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        result = generate_fallback_profile("fixture-dataset-healthcare", repo_root=fake_repo)

    assert result["profile"]["home_card"]["icon"] == "heart"


def test_fixture_unrecognized_domain_still_falls_back_to_generic_icon():
    """A domain with no matching keyword family still safely resolves to
    "generic" -- the generalized rule set is additive, not a requirement
    that every domain now have a curated match."""
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        result = generate_fallback_profile(
            "fixture-dataset-unrecognized-domain", repo_root=fake_repo
        )

    assert result["profile"]["home_card"]["icon"] == "generic"


def test_fixture_fallback_is_deterministic_across_repeated_calls():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        first = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)
        second = generate_fallback_profile("fixture-dataset", repo_root=fake_repo)

    assert first == second


def test_fallback_never_writes_a_draft_file_for_fixture_dataset():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        generate_fallback_profile("fixture-dataset", repo_root=fake_repo)
        assert not (fake_repo / "registry" / "profile-drafts").exists()


def test_load_dataset_profile_returns_generated_fallback_without_writing_a_draft():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        drafts_dir = fake_repo / "registry" / "profile-drafts"

        envelope = load_dataset_profile("fixture-dataset", repo_root=fake_repo)

        assert envelope["profile_source"] == "generated_fallback"
        assert envelope["dataset_slug"] == "fixture-dataset"
        assert envelope["sources_used"]["metrics"] is True
        assert envelope["sources_used"]["model_card"] is True
        assert not drafts_dir.exists()


def test_load_dataset_profile_returns_authored_draft_when_one_exists():
    with tempfile.TemporaryDirectory() as tmp:
        fake_repo = _build_fake_repo(Path(tmp), manifest_artifacts=_FULL_MANIFEST_ARTIFACTS)
        authored_profile = {"schema_version": "1.0.0", "dataset_slug": "fixture-dataset"}
        create_draft("fixture-dataset", authored_profile, repo_root=fake_repo)

        envelope = load_dataset_profile("fixture-dataset", repo_root=fake_repo)

    assert envelope["profile_source"] == "authored_draft"
    assert envelope["profile"] == authored_profile
    assert envelope["sources_used"] is None


# ---------------------------------------------------------------------------
# Non-persistence: neither module ever imports/binds create_draft/update_draft
# ---------------------------------------------------------------------------
#
# This checks the actual module namespace rather than scanning source text:
# a raw substring search over inspect.getsource() would also match the
# docstrings' own prose explaining this non-persistence guarantee (they
# name create_draft/update_draft to document that they are never called),
# producing a false failure with no real invariant violation. Checking
# hasattr(...) against the imported names is what actually distinguishes
# "this module can call create_draft/update_draft" from "this module's
# documentation mentions them."

def test_fallback_modules_never_import_create_or_update_draft():
    assert not hasattr(public_profile_fallback, "create_draft")
    assert not hasattr(public_profile_fallback, "update_draft")
    assert not hasattr(public_profile_loader, "create_draft")
    assert not hasattr(public_profile_loader, "update_draft")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-v"]))

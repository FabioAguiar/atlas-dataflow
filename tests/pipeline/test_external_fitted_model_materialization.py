"""
Tests for Project Spec S0181: Deferred External Fitted-Model Materialization
and Validated-Run Artifact Completion Contract (materializer half).

Uses only synthetic in-memory/tmp_path fixtures and opaque arbitrary model
bytes. Never requires a real (Telco-trained) model file, never deserializes
joblib/pickle, never executes a notebook, and never requires the external
Telco filesystem. Fixtures use a generic dataset slug (mirroring
tests/pipeline/test_capability_aware_release_candidate_publisher.py's own
convention) to demonstrate the new materializer is generic, not
dataset-name-driven.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline import generate_inference_bundle  # noqa: E402
from pipeline import materialize_external_fitted_model  # noqa: E402
from pipeline.materialize_external_fitted_model import (  # noqa: E402
    materialize_external_fitted_model as materialize,
)

REPO_ROOT = Path(__file__).parent.parent.parent
MATERIALIZATION_SCHEMA_PATH = REPO_ROOT / "pipeline" / "external-fitted-model-materialization.schema.json"
INFERENCE_BUNDLE_SCHEMA_PATH = REPO_ROOT / "contracts" / "inference-bundle.schema.json"

DATASET_SLUG = "sample-binary-classification-dataset"
MODEL_STATE_FINGERPRINT = "a" * 64
MODEL_BYTES = b"opaque-external-fitted-model-bytes-fixture-not-a-real-pickle"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, doc: dict) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(doc, indent=2, sort_keys=True).encode("utf-8")
    path.write_bytes(data)
    return data


def _write_bytes(path: Path, data: bytes) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def _training_parameter_record(*, dataset_slug: str = DATASET_SLUG, model_artifact_sha256: str) -> dict:
    return {
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "record_kind": "training_parameter_record",
        "origin": "validated_external_fitted_model",
        "producer": "dataset-study-external-producer/v1",
        "handoff_lineage_reference": "artifacts/models/sample/final-model-handoff.json",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "selected_model_id": "candidate-001",
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {
            "library": "scikit-learn",
            "class_name": "HistGradientBoostingClassifier",
        },
        "hyperparameters": {"max_depth": 3, "learning_rate": 0.1},
        "feature_order": ["feature_one", "feature_two"],
        "preprocessing_evidence_reference": "artifacts/models/sample/preprocessing-evidence.json",
        "serializer_metadata_reference": "artifacts/models/sample/serializer-metadata.json",
        "model_artifact_reference": {
            "path": "artifacts/models/sample/model.joblib",
            "sha256": model_artifact_sha256,
        },
        "model_state_fingerprint": MODEL_STATE_FINGERPRINT,
        "atlas_fit_confirmation": {
            "atlas_fit": False,
            "atlas_tuned": False,
            "atlas_recalibrated": False,
            "atlas_altered": False,
        },
        "raw_partition_confirmation": {"raw_partitions_embedded": False},
    }


def _training_metrics(*, dataset_slug: str = DATASET_SLUG) -> dict:
    return {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "artifact_kind": "training_metrics",
        "created_at": "2026-08-01T00:00:00+00:00",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "dataset_slug": dataset_slug,
        },
        "cross_validation_summary": {
            "partition_role": "train",
            "used_for_fitting": True,
            "used_for_model_selection": True,
            "used_for_threshold_selection": False,
            "used_for_adjustment": False,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.81}],
        },
        "validation_evaluation": {
            "partition_role": "validation",
            "used_for_fitting": False,
            "used_for_model_selection": True,
            "used_for_threshold_selection": True,
            "sealed_before_finalization": False,
            "metrics": [{"name": "roc_auc", "value": 0.80}],
        },
    }


def _model_selection_evidence(*, dataset_slug: str = DATASET_SLUG, model_state_fingerprint: str = MODEL_STATE_FINGERPRINT) -> dict:
    return {
        "schema_version": "model-selection-evidence.external-fitted-model.v1",
        "artifact_kind": "model_selection_evidence",
        "created_at": "2026-08-01T00:00:00+00:00",
        "evidence_identity": {
            "model_source_mode": "validated_external_fitted_model",
            "producer": "dataset-study-external-producer/v1",
            "handoff_lineage_reference": "artifacts/models/sample/final-model-handoff.json",
        },
        "dataset_identity": {"dataset_slug": dataset_slug},
        "selection_protocol": {"protocol_id": "cross_validation_with_practical_tie_break"},
        "selection_policy": {"primary_metric": "roc_auc", "ranking_direction": "higher_is_better"},
        "cross_validation_summary": {
            "partition_role": "train",
            "metric_summaries": [{"name": "roc_auc", "mean": 0.81, "standard_deviation": 0.02}],
        },
        "validation_metrics": {
            "partition_role": "validation",
            "metrics": [{"name": "roc_auc", "value": 0.80}],
        },
        "practical_tie": {"tolerance": 0.01, "tie_detected": False, "tie_break_criteria": []},
        "candidates": [
            {
                "candidate_id": "candidate-001",
                "model_family": "hist_gradient_boosting",
                "estimator_identity": {
                    "library": "scikit-learn",
                    "class_name": "HistGradientBoostingClassifier",
                },
            }
        ],
        "selected_candidate": {"candidate_id": "candidate-001"},
        "selection_rationale": "Highest validation ROC AUC with no practical tie.",
        "sealed_test_confirmation": {
            "test_partition_role": "test",
            "used_for_model_selection": False,
            "sealed_before_selection": True,
        },
        "path_references": {"model_selection_evidence_reference": "artifacts/models/sample/model-selection-evidence.json"},
        "hashes": {"algorithm": "sha256", "model_state_fingerprint": model_state_fingerprint},
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "raw_dataset_embedded": False,
            "model_bytes_embedded": False,
            "notebook_state_embedded": False,
            "reduced_and_sanitized": True,
        },
    }


def _multi_family_candidates(*, selected_family_candidate_id: str = "candidate-001") -> list[dict]:
    """All four Project Spec S0186 bounded scientific selection-candidate
    family/class pairs, keeping the fixture's HGB candidate_id matched to
    the training-record fixture's selected_model_id."""
    return [
        {
            "candidate_id": "candidate-000",
            "model_family": "logistic_regression",
            "estimator_identity": {"library": "scikit-learn", "class_name": "LogisticRegression"},
        },
        {
            "candidate_id": "candidate-002",
            "model_family": "decision_tree",
            "estimator_identity": {"library": "scikit-learn", "class_name": "DecisionTreeClassifier"},
        },
        {
            "candidate_id": "candidate-003",
            "model_family": "random_forest",
            "estimator_identity": {"library": "scikit-learn", "class_name": "RandomForestClassifier"},
        },
        {
            "candidate_id": selected_family_candidate_id,
            "model_family": "hist_gradient_boosting",
            "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
        },
    ]


def _model_selection_evidence_multi_family(
    *,
    dataset_slug: str = DATASET_SLUG,
    model_state_fingerprint: str = MODEL_STATE_FINGERPRINT,
    selected_candidate_id: str = "candidate-001",
) -> dict:
    evidence = _model_selection_evidence(dataset_slug=dataset_slug, model_state_fingerprint=model_state_fingerprint)
    evidence["candidates"] = _multi_family_candidates()
    evidence["selected_candidate"] = {"candidate_id": selected_candidate_id}
    return evidence


def _operational_readiness_fail_closed() -> dict:
    return {
        "educational_final_model_complete": True,
        "educational_inference_demo_ready": True,
        "operational_validity": "unconfirmed",
        "operational_threshold": {"status": "unresolved", "value": None},
        "operational_prediction_available": False,
    }


class _SourceFixture:
    """Builds a self-consistent set of source (pre-materialization) files."""

    def __init__(self, tmp_path: Path, *, dataset_slug: str = DATASET_SLUG) -> None:
        self.dataset_slug = dataset_slug
        self.source_dir = tmp_path / "external-source"
        self.model_bytes = MODEL_BYTES
        self.model_sha256 = _sha256_bytes(self.model_bytes)

        self.source_model_path = self.source_dir / "model.joblib"
        _write_bytes(self.source_model_path, self.model_bytes)

        self.training_record = _training_parameter_record(
            dataset_slug=dataset_slug, model_artifact_sha256=self.model_sha256
        )
        self.training_metrics = _training_metrics(dataset_slug=dataset_slug)
        self.model_selection = _model_selection_evidence(dataset_slug=dataset_slug)

        self.source_record_path = self.source_dir / "training-parameter-record.json"
        self.source_metrics_path = self.source_dir / "training-metrics.json"
        self.source_selection_path = self.source_dir / "model-selection-evidence.json"

        record_bytes = _write_json(self.source_record_path, self.training_record)
        metrics_bytes = _write_json(self.source_metrics_path, self.training_metrics)
        selection_bytes = _write_json(self.source_selection_path, self.model_selection)

        self.expected_evidence_hashes = {
            "training_parameter_record": _sha256_bytes(record_bytes),
            "training_metrics": _sha256_bytes(metrics_bytes),
            "model_selection_evidence": _sha256_bytes(selection_bytes),
        }

    def kwargs(self, *, repo_root: Path, output_prefix: str = "governed/external/sample") -> dict[str, Any]:
        return {
            "dataset_slug": self.dataset_slug,
            "materialization_id": "materialization-0001",
            "producer": "pipeline.materialize_external_fitted_model",
            "source_model_path": self.source_model_path,
            "expected_source_model_sha256": self.model_sha256,
            "source_training_parameter_record_path": self.source_record_path,
            "source_training_metrics_path": self.source_metrics_path,
            "source_model_selection_evidence_path": self.source_selection_path,
            "expected_evidence_hashes": dict(self.expected_evidence_hashes),
            "runtime_compatibility": {
                "serialization_format": "joblib",
                "loader_strategy": "joblib_sklearn_predict",
                "load_safety_confirmed": True,
            },
            "educational_threshold": {"value": 0.2578, "scenario": "educational_validation_partition"},
            "final_test_completion": {"used_for_threshold_selection": False, "evaluation_count": 1},
            "operational_readiness": _operational_readiness_fail_closed(),
            "output_model_artifact_path": f"{output_prefix}/model.bin",
            "output_training_parameter_record_path": f"{output_prefix}/training-parameter-record.json",
            "output_training_metrics_path": f"{output_prefix}/training-metrics.json",
            "output_model_selection_evidence_path": f"{output_prefix}/model-selection-evidence.json",
            "repo_root": repo_root,
        }


def _isolated_repo_root(tmp_path: Path) -> Path:
    """A synthetic repo root carrying only the read-only S0157/S0181 schema
    files this materializer needs to resolve -- never the real repository,
    and never used to write generated outputs into the real tree."""
    repo_root = tmp_path / "repo-root"
    pipeline_dir = repo_root / "pipeline"
    pipeline_dir.mkdir(parents=True)
    for name in (
        "training-parameter-record.schema.json",
        "training-metrics.schema.json",
        "model-selection-evidence.schema.json",
        "external-fitted-model-materialization.schema.json",
    ):
        shutil.copyfile(REPO_ROOT / "pipeline" / name, pipeline_dir / name)
    return repo_root


# --- successful materialization ---------------------------------------------


def test_successful_materialization_is_schema_valid(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)

    result = materialize(**fixture.kwargs(repo_root=repo_root))

    assert result["status"] == "materialized"
    assert result["model_source_mode"] == "validated_external_fitted_model"
    assert result["dataset_identity"]["dataset_slug"] == DATASET_SLUG

    schema = json.loads(MATERIALIZATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)

    # Atlas-owned copied bytes actually exist and hash-match the result.
    output_model_path = repo_root / result["model_artifact_path"]
    assert output_model_path.is_file()
    assert _sha256_bytes(output_model_path.read_bytes()) == result["model_artifact_sha256"]
    assert result["model_artifact_sha256"] == fixture.model_sha256


def test_boundary_confirmations_all_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    result = materialize(**fixture.kwargs(repo_root=repo_root))
    assert result["status"] == "materialized"
    assert all(value is False for value in result["boundary_confirmations"].values())


# --- S0157 external profile validation --------------------------------------


def test_s0157_external_profile_schema_version_required(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    # Corrupt the source record to declare the *internal* profile instead.
    bad_record = dict(fixture.training_record)
    bad_record["schema_version"] = "training-parameter-record.v1"
    record_bytes = _write_json(fixture.source_record_path, bad_record)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["training_parameter_record"] = _sha256_bytes(record_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    reason = result["blocking_reasons"][0]
    assert reason["code"] in ("invalid_external_evidence_profile", "source_evidence_schema_invalid")


def test_s0157_schema_structurally_invalid_source_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    bad_metrics = dict(fixture.training_metrics)
    del bad_metrics["cross_validation_summary"]
    metrics_bytes = _write_json(fixture.source_metrics_path, bad_metrics)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["training_metrics"] = _sha256_bytes(metrics_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "source_evidence_schema_invalid"


# --- hash verification --------------------------------------------------------


def test_source_evidence_sha_mismatch_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["training_metrics"] = "0" * 64

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "source_evidence_hash_mismatch"
    assert result["blocking_reasons"][0]["field"] == "training_metrics"


def test_source_model_sha_mismatch_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_source_model_sha256"] = "0" * 64

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "source_model_hash_mismatch"


def test_destination_model_sha_verified_after_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    output_model_full = repo_root / kwargs["output_model_artifact_path"]

    real_sha256_file = materialize_external_fitted_model._sha256_file

    def _fake_sha256_file(path: Path) -> str | None:
        if path == output_model_full:
            return "0" * 64
        return real_sha256_file(path)

    monkeypatch.setattr(materialize_external_fitted_model, "_sha256_file", _fake_sha256_file)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "destination_model_hash_mismatch"


# --- identity / fingerprint consistency --------------------------------------


def test_dataset_identity_mismatch_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    mismatched_metrics = _training_metrics(dataset_slug="other-dataset-slug")
    metrics_bytes = _write_json(fixture.source_metrics_path, mismatched_metrics)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["training_metrics"] = _sha256_bytes(metrics_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_model_state_fingerprint_mismatch_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    mismatched_selection = _model_selection_evidence(model_state_fingerprint="b" * 64)
    selection_bytes = _write_json(fixture.source_selection_path, mismatched_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "model_state_fingerprint_mismatch"


# --- Project Spec S0186: selected-candidate consistency ---------------------


def test_multi_family_selection_evidence_materializes_when_selected_candidate_matches(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    multi_family_selection = _model_selection_evidence_multi_family(dataset_slug=fixture.dataset_slug)
    selection_bytes = _write_json(fixture.source_selection_path, multi_family_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "materialized"
    schema = json.loads(MATERIALIZATION_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(result)


def test_selected_candidate_id_mismatch_blocks_before_destination_writes(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    # candidate-003 (random_forest) exists in candidates[] but does not match
    # the training-record fixture's selected_model_id ("candidate-001").
    mismatched_selection = _model_selection_evidence_multi_family(
        dataset_slug=fixture.dataset_slug, selected_candidate_id="candidate-003"
    )
    selection_bytes = _write_json(fixture.source_selection_path, mismatched_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "selected_candidate_identity_mismatch"
    assert not (repo_root / kwargs["output_model_artifact_path"]).exists()
    assert not (repo_root / kwargs["output_training_parameter_record_path"]).exists()
    assert not (repo_root / kwargs["output_training_metrics_path"]).exists()
    assert not (repo_root / kwargs["output_model_selection_evidence_path"]).exists()


def test_selected_candidate_family_mismatch_blocks_before_destination_writes(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    # The selected candidate_id ("candidate-001") matches the training
    # record's selected_model_id, but this fixture reassigns that same
    # candidate_id to the logistic_regression family/class pair -- a
    # schema-valid pairing that disagrees with the training record's
    # hist_gradient_boosting family.
    tampered_candidates = _multi_family_candidates(selected_family_candidate_id="candidate-004")
    tampered_candidates.append(
        {
            "candidate_id": "candidate-001",
            "model_family": "logistic_regression",
            "estimator_identity": {"library": "scikit-learn", "class_name": "LogisticRegression"},
        }
    )
    tampered_selection = _model_selection_evidence_multi_family(dataset_slug=fixture.dataset_slug)
    tampered_selection["candidates"] = tampered_candidates
    selection_bytes = _write_json(fixture.source_selection_path, tampered_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "selected_candidate_family_mismatch"
    assert not (repo_root / kwargs["output_model_artifact_path"]).exists()
    assert not (repo_root / kwargs["output_training_parameter_record_path"]).exists()


def test_undeclared_selected_candidate_blocks_before_destination_writes(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    undeclared_selection = _model_selection_evidence_multi_family(
        dataset_slug=fixture.dataset_slug, selected_candidate_id="candidate-999-not-declared"
    )
    selection_bytes = _write_json(fixture.source_selection_path, undeclared_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "selected_candidate_not_uniquely_resolved"
    assert not (repo_root / kwargs["output_model_artifact_path"]).exists()


def test_no_training_call_or_model_deserialization_during_multi_family_materialization(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    multi_family_selection = _model_selection_evidence_multi_family(dataset_slug=fixture.dataset_slug)
    selection_bytes = _write_json(fixture.source_selection_path, multi_family_selection)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_evidence_hashes"]["model_selection_evidence"] = _sha256_bytes(selection_bytes)

    result = materialize(**kwargs)

    assert result["status"] == "materialized"
    assert all(value is False for value in result["boundary_confirmations"].values())


def test_resolve_and_check_selected_candidate_estimator_mismatch_blocks() -> None:
    """Direct unit test of the extracted consistency-check helper: under the
    Project Spec S0186 bounded vocabulary, model_family and estimator_identity
    are 1:1 paired per candidate, so a schema-valid end-to-end fixture cannot
    isolate an estimator-only mismatch (a family mismatch would always fire
    first). This exercises the estimator_identity comparison directly on
    already-loaded evidence dicts, independent of schema pairing."""
    training_record = _training_parameter_record(model_artifact_sha256="a" * 64)
    model_selection = _model_selection_evidence()
    model_selection["candidates"][0]["estimator_identity"] = {
        "library": "scikit-learn",
        "class_name": "SomeOtherClassifier",
    }

    with pytest.raises(materialize_external_fitted_model.MaterializationBlocked) as exc_info:
        materialize_external_fitted_model._resolve_and_check_selected_candidate(model_selection, training_record)

    assert exc_info.value.code == "selected_candidate_estimator_mismatch"


def test_resolve_and_check_selected_candidate_accepts_consistent_evidence() -> None:
    training_record = _training_parameter_record(model_artifact_sha256="a" * 64)
    model_selection = _model_selection_evidence()

    resolved = materialize_external_fitted_model._resolve_and_check_selected_candidate(
        model_selection, training_record
    )

    assert resolved["candidate_id"] == "candidate-001"


# --- missing required evidence -----------------------------------------------


def test_missing_required_selection_evidence_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["source_model_selection_evidence_path"] = fixture.source_dir / "does-not-exist.json"

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "missing_source_evidence"
    assert result["blocking_reasons"][0]["field"] == "model_selection_evidence"


# --- unsafe output paths ------------------------------------------------------


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "/etc/passwd",
        "../outside-repo/model.bin",
        "governed/../../escape/model.bin",
        "pipeline/training-runs/sample/model.bin",
        "external-models/sample/model.bin",
    ],
)
def test_unsafe_output_path_rejected(tmp_path: Path, unsafe_path: str) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["output_model_artifact_path"] = unsafe_path

    result = materialize(**kwargs)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "unsafe_output_path"


# --- blocked result reason stability ------------------------------------------


def test_blocked_result_reason_stability(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    kwargs = fixture.kwargs(repo_root=repo_root)
    kwargs["expected_source_model_sha256"] = "0" * 64

    first = materialize(**kwargs)
    second = materialize(**kwargs)

    assert first["blocking_reasons"] == second["blocking_reasons"]
    assert first["status"] == second["status"] == "blocked"


# --- no training / no model import / no inference -----------------------------


def test_no_forbidden_calls_in_module_source() -> None:
    source = inspect.getsource(materialize_external_fitted_model)
    forbidden_substrings = (
        "import joblib",
        "import sklearn",
        "import pickle",
        "pickle.load",
        ".fit(",
        ".fit_transform(",
        ".predict(",
        ".predict_proba(",
        "train_from_paths",
        "pipeline.training",
    )
    for substring in forbidden_substrings:
        assert substring not in source, f"forbidden call/import found: {substring}"


# --- compatibility with the already-applied S0180 bundle consumer -------------


def _minimal_execution_contract(*, dataset_id: str = DATASET_SLUG) -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "model_source_mode": "validated_external_fitted_model",
        "dataset_id": dataset_id,
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
    }


def test_materialization_result_generates_schema_valid_external_inference_bundle(tmp_path: Path) -> None:
    """The actual S0181 materialization result is accepted by S0180's
    external bundle branch without changing its governed provenance or
    fail-closed operational-readiness evidence."""
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    materialization_result = materialize(**fixture.kwargs(repo_root=repo_root))
    assert materialization_result["status"] == "materialized"

    execution_contract_path = repo_root / "contracts" / "sample" / "execution-contract.json"
    _write_json(execution_contract_path, _minimal_execution_contract())
    runtime_contract_path = repo_root / "contracts" / "sample" / "runtime-contract.json"
    _write_json(runtime_contract_path, {"contract_version": "runtime_contract.v1"})
    public_contract_path = repo_root / "contracts" / "sample" / "public-contract.json"
    _write_json(public_contract_path, {"contract_version": "public_contract.v1"})
    dataset_context_path = repo_root / "contracts" / "sample" / "dataset-context.json"
    _write_json(dataset_context_path, {"schema_version": "dataset-context.v1"})
    prepared_dataset_path = repo_root / "contracts" / "sample" / "prepared-dataset.json"
    _write_json(prepared_dataset_path, {"schema_version": "prepared-dataset.v1"})

    output_path = repo_root / "contracts" / "sample" / "inference-bundle.json"

    bundle_result = generate_inference_bundle.materialize_governed_inference_bundle(
        external_fitted_model_materialization_result=materialization_result,
        execution_contract_path=execution_contract_path,
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_dataset_path=prepared_dataset_path,
        output_path=output_path,
        prediction_type="number",
        repo_root=repo_root,
        dataset_slug=DATASET_SLUG,
        release_id="release-20260801-001",
        class_labels=["no", "yes"],
        probability_output=True,
        inference_bundle_schema_path=str(INFERENCE_BUNDLE_SCHEMA_PATH),
        # generate_inference_bundle._reference_for_path falls back to the
        # real, physical repository root (not the `repo_root` argument) when
        # no explicit *_ref is supplied -- supply explicit release-relative
        # refs so this isolated-tmp-path test does not block earlier on that
        # unrelated quirk.
        execution_contract_ref="contracts/sample/execution-contract.json",
        runtime_contract_ref="contracts/sample/runtime-contract.json",
        public_contract_ref="contracts/sample/public-contract.json",
        dataset_context_ref="contracts/sample/dataset-context.json",
        prepared_dataset_ref="contracts/sample/prepared-dataset.json",
    )

    assert bundle_result["status"] == "generated"
    assert bundle_result["model_provenance_origin"] == "validated_external_fitted_model"
    assert output_path.is_file()

    bundle = json.loads(output_path.read_text(encoding="utf-8"))
    schema = json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(bundle)

    assert bundle["model_provenance_origin"] == "validated_external_fitted_model"
    assert bundle["external_model_evidence"]["origin"] == "validated_external_fitted_model"
    assert bundle["external_model_evidence"]["model_family"] == "hist_gradient_boosting"
    assert bundle["runtime_execution"]["model_family"] == "hist_gradient_boosting"
    assert "training_evidence" not in bundle
    assert bundle["external_model_evidence"]["readiness"]["operational_validity"] == "unconfirmed"
    assert bundle["external_model_evidence"]["readiness"]["operational_threshold"] == {
        "status": "unresolved",
        "value": None,
    }
    assert bundle["external_model_evidence"]["readiness"]["operational_prediction_available"] is False


@pytest.mark.parametrize(
    "model_family",
    ["logistic_regression", "gradient_boosting", "random_forest", "hist_gradient_boosting"],
)
def test_inference_bundle_model_family_enums_preserve_supported_values(model_family: str) -> None:
    schema = json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    runtime_enum = schema["properties"]["runtime_execution"]["properties"]["model_family"]["enum"]
    descriptor_enum = schema["$defs"]["binary_result_semantics"]["properties"]["model_descriptor"][
        "properties"
    ]["model_family"]["enum"]

    assert model_family in runtime_enum
    assert model_family in descriptor_enum


def test_inference_bundle_model_family_enums_reject_unsupported_value() -> None:
    schema = json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    unsupported = "unsupported_model_family"

    assert unsupported not in schema["properties"]["runtime_execution"]["properties"]["model_family"]["enum"]
    assert unsupported not in schema["$defs"]["binary_result_semantics"]["properties"]["model_descriptor"][
        "properties"
    ]["model_family"]["enum"]


def test_materialization_result_field_shape_matches_bundle_consumer_requirements(tmp_path: Path) -> None:
    """Direct structural assertion (independent of the schema-gap test
    above): every field `_build_external_bundle` actually reads from a
    materialization result is present with the expected type."""
    repo_root = _isolated_repo_root(tmp_path)
    fixture = _SourceFixture(tmp_path)
    result = materialize(**fixture.kwargs(repo_root=repo_root))

    assert result["model_source_mode"] == "validated_external_fitted_model"
    assert isinstance(result["dataset_identity"]["dataset_slug"], str)
    evidence_refs = result["evidence_references"]
    for key in (
        "training_parameter_record_path",
        "training_metrics_path",
        "model_selection_evidence_path",
    ):
        assert isinstance(evidence_refs[key], str)
        assert (repo_root / evidence_refs[key]).is_file()
    assert isinstance(result["model_artifact_path"], str)
    assert isinstance(result["educational_threshold"]["value"], (int, float))
    assert isinstance(result["educational_threshold"]["scenario"], str)
    assert isinstance(result["final_test_completion"]["used_for_threshold_selection"], bool)
    assert isinstance(result["final_test_completion"]["evaluation_count"], int)
    for key in (
        "educational_final_model_complete",
        "educational_inference_demo_ready",
        "operational_validity",
        "operational_threshold",
        "operational_prediction_available",
    ):
        assert key in result["operational_readiness"]

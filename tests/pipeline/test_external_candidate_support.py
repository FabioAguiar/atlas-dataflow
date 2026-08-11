import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline.materialize_external_candidate_support import (  # noqa: E402
    materialize_external_candidate_support,
)


DATASET_SLUG = "pytest-external-dataset"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, data: dict) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True)
    path.write_text(text, encoding="utf-8")
    return _sha256_bytes(text.encode("utf-8"))


def _write_evidence_fixtures(tmp_repo: Path, *, dataset_slug: str = DATASET_SLUG) -> dict:
    training_record_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / dataset_slug / "run-001" / "training-parameter-record.json"
    training_metrics_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / dataset_slug / "run-001" / "training-metrics.json"
    model_selection_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / dataset_slug / "run-001" / "model-selection-evidence.json"

    record_sha256 = _write_json(training_record_path, {
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "dataset_identity": {"dataset_slug": dataset_slug},
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
    })
    metrics_sha256 = _write_json(training_metrics_path, {
        "schema_version": "training-metrics.external-fitted-model.v1",
        "evidence_identity": {"dataset_slug": dataset_slug},
    })
    selection_sha256 = _write_json(model_selection_path, {
        "schema_version": "model-selection-evidence.external-fitted-model.v1",
        "dataset_identity": {"dataset_slug": dataset_slug},
    })

    return {
        "evidence_references": {
            "training_parameter_record_path": str(training_record_path.relative_to(tmp_repo)),
            "training_metrics_path": str(training_metrics_path.relative_to(tmp_repo)),
            "model_selection_evidence_path": str(model_selection_path.relative_to(tmp_repo)),
        },
        "evidence_hashes": {
            "training_parameter_record_sha256": record_sha256,
            "training_metrics_sha256": metrics_sha256,
            "model_selection_evidence_sha256": selection_sha256,
        },
    }


def _materialization_result(evidence: dict, *, dataset_slug: str = DATASET_SLUG, status: str = "materialized", model_source_mode: str = "validated_external_fitted_model") -> dict:
    return {
        "status": status,
        "model_source_mode": model_source_mode,
        "dataset_identity": {"dataset_slug": dataset_slug},
        "model_state_fingerprint": "a" * 64,
        "operational_readiness": {
            "operational_validity": "unconfirmed",
            "operational_threshold": {"status": "unresolved", "value": None},
            "operational_prediction_available": False,
        },
        **evidence,
    }


def _execution_contract(*, dataset_slug: str = DATASET_SLUG, model_source_mode: str = "validated_external_fitted_model") -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": dataset_slug,
        "model_source_mode": model_source_mode,
        "target_column": "Churn",
        "feature_columns": ["feature_a", "feature_b"],
    }


def _dataset_context(*, dataset_slug: str = DATASET_SLUG) -> dict:
    return {"dataset_slug": dataset_slug, "title": "Pytest External Dataset"}


def _call(tmp_repo: Path, *, evidence=None, materialization_result=None, execution_contract=None, dataset_context=None, output_path="pipeline/external-fitted-model-runs/pytest-external-dataset/run-001/model-card.json", dataset_slug=DATASET_SLUG):
    evidence = evidence if evidence is not None else _write_evidence_fixtures(tmp_repo, dataset_slug=dataset_slug)
    return materialize_external_candidate_support(
        dataset_slug=dataset_slug,
        materialization_result=materialization_result if materialization_result is not None else _materialization_result(evidence, dataset_slug=dataset_slug),
        execution_contract=execution_contract if execution_contract is not None else _execution_contract(dataset_slug=dataset_slug),
        dataset_context=dataset_context if dataset_context is not None else _dataset_context(dataset_slug=dataset_slug),
        output_model_card_path=output_path,
        repo_root=tmp_repo,
    )


def test_valid_external_evidence_materializes_model_card(tmp_path):
    tmp_repo = tmp_path / "repo"
    result = _call(tmp_repo)

    assert result["status"] == "materialized"
    assert result["model_card_path"] == "pipeline/external-fitted-model-runs/pytest-external-dataset/run-001/model-card.json"
    output_file = tmp_repo / result["model_card_path"]
    assert output_file.is_file()

    model_card = json.loads(output_file.read_text(encoding="utf-8"))
    assert model_card["schema_version"] == "model-card.v1"
    assert model_card["model_source_mode"] == "validated_external_fitted_model"
    assert model_card["dataset_identity"]["dataset_slug"] == DATASET_SLUG
    assert model_card["external_model_identity"]["model_family"] == "hist_gradient_boosting"
    assert result["model_card_sha256"] == hashlib.sha256(output_file.read_bytes()).hexdigest()


def test_model_card_does_not_fabricate_atlas_training_run_identity(tmp_path):
    tmp_repo = tmp_path / "repo"
    result = _call(tmp_repo)
    model_card = json.loads((tmp_repo / result["model_card_path"]).read_text(encoding="utf-8"))

    assert "training_run_identity" not in model_card
    assert model_card["model_card_boundary_confirmations"]["atlas_training_run_identity_fabricated"] is False
    assert model_card["model_source_mode"] == "validated_external_fitted_model"


def test_model_card_embeds_no_model_bytes_raw_dataset_or_absolute_paths(tmp_path):
    tmp_repo = tmp_path / "repo"
    result = _call(tmp_repo)
    model_card_text = (tmp_repo / result["model_card_path"]).read_text(encoding="utf-8")
    model_card = json.loads(model_card_text)

    assert model_card["model_card_boundary_confirmations"]["model_bytes_embedded"] is False
    assert model_card["model_card_boundary_confirmations"]["raw_dataset_embedded"] is False
    assert str(tmp_repo) not in model_card_text
    assert "/home/" not in model_card_text
    assert "/workspace/" not in model_card_text


def test_hash_mismatch_fails_closed_before_output(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    evidence["evidence_hashes"]["training_metrics_sha256"] = "f" * 64

    result = _call(tmp_repo, evidence=evidence)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "referenced_evidence_hash_mismatch"
    assert not (tmp_repo / "pipeline" / "external-fitted-model-runs" / DATASET_SLUG / "run-001" / "model-card.json").exists()


def test_dataset_identity_mismatch_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    materialization_result = _materialization_result(evidence, dataset_slug="a-different-dataset")

    result = _call(tmp_repo, evidence=evidence, materialization_result=materialization_result)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_execution_contract_dataset_identity_mismatch_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    execution_contract = _execution_contract(dataset_slug="a-different-dataset")

    result = _call(tmp_repo, execution_contract=execution_contract)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_dataset_context_identity_mismatch_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    dataset_context = _dataset_context(dataset_slug="a-different-dataset")

    result = _call(tmp_repo, dataset_context=dataset_context)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_training_parameter_record_dataset_identity_mismatch_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    record_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / DATASET_SLUG / "run-001" / "training-parameter-record.json"
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_text = json.dumps({
        "schema_version": "training-parameter-record.external-fitted-model.v1",
        "dataset_identity": {"dataset_slug": "a-different-dataset"},
        "model_family": "hist_gradient_boosting",
        "estimator_identity": {"library": "scikit-learn", "class_name": "HistGradientBoostingClassifier"},
    }, indent=2, sort_keys=True)
    record_path.write_text(record_text, encoding="utf-8")
    record_sha256 = _sha256_bytes(record_text.encode("utf-8"))

    metrics_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / DATASET_SLUG / "run-001" / "training-metrics.json"
    metrics_sha256 = _write_json(metrics_path, {"schema_version": "training-metrics.external-fitted-model.v1"})
    selection_path = tmp_repo / "pipeline" / "external-fitted-model-runs" / DATASET_SLUG / "run-001" / "model-selection-evidence.json"
    selection_sha256 = _write_json(selection_path, {"schema_version": "model-selection-evidence.external-fitted-model.v1"})

    evidence = {
        "evidence_references": {
            "training_parameter_record_path": str(record_path.relative_to(tmp_repo)),
            "training_metrics_path": str(metrics_path.relative_to(tmp_repo)),
            "model_selection_evidence_path": str(selection_path.relative_to(tmp_repo)),
        },
        "evidence_hashes": {
            "training_parameter_record_sha256": record_sha256,
            "training_metrics_sha256": metrics_sha256,
            "model_selection_evidence_sha256": selection_sha256,
        },
    }

    result = _call(tmp_repo, evidence=evidence)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_internal_or_absent_model_source_mode_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    materialization_result = _materialization_result(evidence, model_source_mode="atlas_internal_training")

    result = _call(tmp_repo, evidence=evidence, materialization_result=materialization_result)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "invalid_model_source_mode"


def test_non_materialized_status_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    materialization_result = _materialization_result(evidence, status="blocked")

    result = _call(tmp_repo, evidence=evidence, materialization_result=materialization_result)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "materialization_not_materialized"


def test_execution_contract_missing_external_declaration_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    execution_contract = _execution_contract(model_source_mode="atlas_internal_training")

    result = _call(tmp_repo, execution_contract=execution_contract)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "execution_contract_model_source_mode_invalid"


def test_unsafe_output_path_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    result = _call(tmp_repo, output_path="../outside-repo/model-card.json")

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"


def test_unsafe_evidence_reference_path_fails_closed(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    evidence["evidence_references"]["training_parameter_record_path"] = "/etc/passwd"

    result = _call(tmp_repo, evidence=evidence)

    assert result["status"] == "blocked"
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"


def test_no_output_written_on_validation_failure(tmp_path):
    tmp_repo = tmp_path / "repo"
    evidence = _write_evidence_fixtures(tmp_repo)
    evidence["evidence_hashes"]["model_selection_evidence_sha256"] = "0" * 64

    result = _call(tmp_repo, evidence=evidence)

    assert result["status"] == "blocked"
    run_dir = tmp_repo / "pipeline" / "external-fitted-model-runs" / DATASET_SLUG / "run-001"
    assert not (run_dir / "model-card.json").exists()
    # No stray files anywhere else in the repo root either.
    assert list(tmp_repo.rglob("model-card.json")) == []


def test_module_does_not_import_model_deserialization_libraries():
    module_source = Path(REPO_ROOT / "pipeline" / "materialize_external_candidate_support.py").read_text(
        encoding="utf-8"
    )
    for forbidden in ("import joblib", "import pickle", "from joblib", "from pickle", "import sklearn", "from sklearn"):
        assert forbidden not in module_source


def test_module_never_calls_training_selection_threshold_or_inference_apis():
    module_source = Path(REPO_ROOT / "pipeline" / "materialize_external_candidate_support.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "train_from_paths",
        ".fit(",
        ".predict(",
        ".predict_proba(",
        "GridSearchCV",
        "RandomizedSearchCV",
        "optimize_threshold",
    ):
        assert forbidden not in module_source


def test_module_contains_no_dataset_slug_branch():
    module_source = Path(REPO_ROOT / "pipeline" / "materialize_external_candidate_support.py").read_text(
        encoding="utf-8"
    )
    assert "telco-customer-churn" not in module_source
    assert "telco" not in module_source.lower()


def test_no_external_absolute_root_persisted(tmp_path):
    tmp_repo = tmp_path / "repo"
    result = _call(tmp_repo)
    model_card = json.loads((tmp_repo / result["model_card_path"]).read_text(encoding="utf-8"))

    dumped = json.dumps(model_card)
    assert str(tmp_repo.resolve()) not in dumped

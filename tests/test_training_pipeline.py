import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import pipeline.assemble_candidate as assemble_candidate
import pipeline.training as training
from pipeline.training import (
    ANALYTICAL_VISUALIZATIONS_FILENAME,
    ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION,
    MODEL_ARTIFACT_FILENAME,
    MODEL_CARD_FILENAME,
    MODEL_CARD_INPUT_FILENAME,
    METRICS_ARTIFACT_FILENAME,
    NATIVE_MULTICLASS_METRIC_NAMES,
    NATIVE_MULTICLASS_MINIMUM_CLASS_COUNT,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _aggregate_feature_importance,
    _cross_check_authored_multiclass_class_order,
    _feature_importance_output_source_map,
    _load_json_file,
    _native_multiclass_confusion_matrix,
    _native_multiclass_metric_values,
    _native_multiclass_per_class_metrics,
    _native_multiclass_requested_metric_names,
    _require_valid_controlled_entrypoint_provenance,
    _stratified_three_way_split_indices,
    _target_distribution_chart_data,
    _validate_fixed_model_configuration,
    convert_model_card_input_to_model_card,
    materialize_training_run_from_prepared_metadata,
    prepare_training_invocation_readiness,
    train_from_paths,
)


FIXED_TRAINING_TIME = datetime(2026, 6, 26, 1, 7, 0, tzinfo=timezone.utc)


class _FixedDateTime:
    @classmethod
    def now(cls, tz=None):
        if tz is None:
            return FIXED_TRAINING_TIME.replace(tzinfo=None)
        return FIXED_TRAINING_TIME.astimezone(tz)


def _write_json(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_execution_contract() -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "training-pipeline-test",
        "target_column": "converted",
        "feature_columns": ["age", "segment", "balance"],
        "ignored_columns": ["operator_note"],
        "required_columns": ["age", "segment"],
        "optional_columns": ["balance"],
        "feature_definitions": {
            "age": {
                "type": "numeric",
                "domain_constraints": {"min": 18, "max": 80},
            },
            "segment": {
                "type": "categorical",
                "domain_constraints": {"values": ["retail", "smb", "enterprise"]},
            },
            "balance": {
                "type": "numeric",
                "domain_constraints": {"min": 0, "max": 100000},
            },
        },
        "missing_value_policy": {
            "age": "median",
            "segment": "mode",
            "balance": "median",
        },
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.5,
            "val_ratio": 0.25,
            "test_ratio": 0.25,
        },
        "random_seed": 42,
        "primary_metric": "accuracy",
        "secondary_metrics": ["f1"],
        "modeling_constraints": {
            "allowed_model_families": ["logistic_regression"],
            "no_automl": True,
            "max_training_time_seconds": 60,
        },
    }


def _valid_prepared_dataset() -> dict:
    rows = [
        {"dataset_id": "training-pipeline-test", "age": 24, "segment": "retail", "balance": 1000, "converted": 0},
        {"dataset_id": "training-pipeline-test", "age": 29, "segment": "smb", "balance": 2400, "converted": 1},
        {"dataset_id": "training-pipeline-test", "age": 36, "segment": "enterprise", "balance": 3600, "converted": 0},
        {"dataset_id": "training-pipeline-test", "age": 41, "segment": "retail", "balance": 5200, "converted": 1},
        {"dataset_id": "training-pipeline-test", "age": 48, "segment": "smb", "balance": 7600, "converted": 0},
        {"dataset_id": "training-pipeline-test", "age": 53, "segment": "enterprise", "balance": 9100, "converted": 1},
        {"dataset_id": "training-pipeline-test", "age": 61, "segment": "retail", "balance": 12000, "converted": 0},
        {"dataset_id": "training-pipeline-test", "age": 68, "segment": "smb", "balance": 15000, "converted": 1},
    ]
    return {"dataset_id": "training-pipeline-test", "rows": rows}


@pytest.fixture
def fixed_training_environment(monkeypatch, tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    repo_root.mkdir()
    monkeypatch.setattr(training, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(training, "datetime", _FixedDateTime)
    return repo_root


def _write_valid_inputs(tmp_path: Path) -> tuple[Path, Path]:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())
    return contract_path, dataset_path


def test_valid_training_inputs_produce_expected_artifacts(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)

    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    output_directory = fixed_training_environment / result.output_directory
    expected_artifacts = [
        MODEL_ARTIFACT_FILENAME,
        TRAINING_PARAMETER_RECORD_FILENAME,
        METRICS_ARTIFACT_FILENAME,
        MODEL_CARD_INPUT_FILENAME,
        MODEL_CARD_FILENAME,
    ]
    assert result.status == "trained"
    for artifact_name in expected_artifacts:
        artifact_path = output_directory / artifact_name
        assert artifact_path.exists(), artifact_name
        assert artifact_path.stat().st_size > 0, artifact_name

    parameter_record = json.loads(
        (output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text(encoding="utf-8")
    )
    assert parameter_record["training_parameters"]["feature_columns"] == ["age", "segment", "balance"]
    assert parameter_record["training_parameters"]["split_policy"]["strategy"] == "stratified"
    assert parameter_record["training_parameters"]["random_seed"] == 42
    assert parameter_record["controlled_entrypoint_provenance"]["entrypoint"] == (
        "pipeline.training.train_from_paths"
    )
    # produced_outputs/hashes are schema-bound (additionalProperties: false)
    # and must not gain a model_card_path/model_card_sha256 key (Project Spec
    # S0026) — model-card.json is tracked only via TrainingResult, not inside
    # this artifact.
    assert "model_card_path" not in parameter_record["produced_outputs"]
    assert "model_card_sha256" not in parameter_record["hashes"]

    model_card = json.loads((output_directory / MODEL_CARD_FILENAME).read_text(encoding="utf-8"))
    assert model_card["schema_version"] == "model-card.v1"
    assert model_card["artifact_kind"] == "model_card"
    assert model_card["prediction_target"] == "converted"
    assert model_card["input_features"] == ["age", "segment", "balance"]
    assert model_card["model_card_boundary_confirmations"]["release_publication_performed"] is False
    assert model_card["model_card_boundary_confirmations"]["profile_publication_performed"] is False


@pytest.mark.parametrize(
    ("mutate_contract", "mutate_dataset", "expected_code", "expected_field"),
    [
        (
            lambda contract: contract.pop("target_column"),
            lambda dataset: None,
            "missing_contract_field",
            "target_column",
        ),
        (
            lambda contract: None,
            lambda dataset: [row.pop("segment") for row in dataset["rows"]],
            "missing_dataset_column",
            "dataset_path",
        ),
        (
            lambda contract: contract["split_policy"].update({"train_ratio": 1.2}),
            lambda dataset: None,
            "invalid_split_policy",
            "split_policy.train_ratio",
        ),
    ],
)
def test_invalid_training_inputs_raise_structured_errors(
    fixed_training_environment: Path,
    tmp_path: Path,
    mutate_contract,
    mutate_dataset,
    expected_code: str,
    expected_field: str,
) -> None:
    contract = _valid_execution_contract()
    dataset = _valid_prepared_dataset()
    mutate_contract(contract)
    mutate_dataset(dataset)
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == expected_code
    assert exc.value.field == expected_field
    assert exc.value.to_dict()["status"] == "rejected"


@pytest.mark.parametrize(
    ("missing_contract", "missing_dataset", "expected_field"),
    [
        (True, False, "execution_contract_path"),
        (False, True, "dataset_path"),
    ],
)
def test_missing_input_files_raise_structured_errors(
    fixed_training_environment: Path,
    tmp_path: Path,
    missing_contract: bool,
    missing_dataset: bool,
    expected_field: str,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    if missing_contract:
        contract_path = tmp_path / "missing-execution-contract.json"
    if missing_dataset:
        dataset_path = tmp_path / "missing-prepared-dataset.json"

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "missing_required_input"
    assert exc.value.field == expected_field


def test_type_mismatch_between_contract_and_dataset_raises_structured_error(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    dataset = _valid_prepared_dataset()
    dataset["rows"][0]["age"] = "not-a-number"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "contract_dataset_type_mismatch"
    assert exc.value.field == "feature_definitions.age"
    assert "age" in str(exc.value)


def test_invalid_seed_raises_structured_error(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    contract["random_seed"] = "not-an-integer"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "invalid_contract_field"
    assert exc.value.field == "random_seed"


def test_same_inputs_and_seed_produce_same_on_disk_hashes(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)

    first = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )
    first_model_hash = _sha256_file(fixed_training_environment / first.serialized_model_path)
    first_parameter_record_hash = _sha256_file(
        fixed_training_environment / first.training_parameter_record_path
    )

    second = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert first_model_hash == _sha256_file(fixed_training_environment / second.serialized_model_path)
    assert first_parameter_record_hash == _sha256_file(
        fixed_training_environment / second.training_parameter_record_path
    )


def test_markerless_model_artifact_is_rejected_by_downstream_acceptance(
    fixed_training_environment: Path,
) -> None:
    output_directory = (
        fixed_training_environment
        / "pipeline"
        / "training-runs"
        / "training-pipeline-test"
        / "train-20260626T010700Z"
    )
    output_directory.mkdir(parents=True)
    (output_directory / MODEL_ARTIFACT_FILENAME).write_bytes(b"externally produced model bytes")
    markerless_record_path = _write_json(
        output_directory / TRAINING_PARAMETER_RECORD_FILENAME,
        {
            "schema_version": "training-parameter-record.v1",
            "record_kind": "training_parameter_record",
            "produced_outputs": {
                "serialized_model_path": (
                    "pipeline/training-runs/training-pipeline-test/"
                    "train-20260626T010700Z/model.pkl"
                ),
            },
        },
    )

    markerless_record = _load_json_file(markerless_record_path, "training_parameter_record_path")
    with pytest.raises(TrainingInputError) as exc:
        _require_valid_controlled_entrypoint_provenance(markerless_record)

    assert exc.value.code == "missing_controlled_entrypoint_provenance"
    assert exc.value.field == "controlled_entrypoint_provenance"


# ---------------------------------------------------------------------------
# Governed training bridge (Project Spec S0015):
# `prepare_training_invocation_readiness`
# ---------------------------------------------------------------------------


def _synthetic_execution_ready_contract() -> dict:
    return _valid_execution_contract()


def _synthetic_prepared_dataset() -> dict:
    return _valid_prepared_dataset()


def _synthetic_execution_contract_draft() -> dict:
    """A synthetic `execution_contract_draft.v1` shaped like
    `pipeline.contract_derivation.project_execution_contract_draft`'s output,
    built as a literal dict rather than imported, keeping this test file
    self-contained and decoupled from that module's exact call signature."""
    return {
        "artifact_type": "execution_contract_draft",
        "contract_version": "execution_contract_draft.v1",
        "draft_status": "not_execution_ready",
        "dataset_identity": {
            "dataset_slug": "telco-customer-churn",
            "dataset_source_ref": "data/raw/telco-customer-churn.csv",
        },
        "target_intent": {
            "target_column": "Churn",
            "observed_labels": ["No", "Yes"],
            "observed_target_distribution": {"No": 5174, "Yes": 1869},
            "positive_label_candidate": "Yes",
        },
        "ignored_columns": ["customerID"],
        "feature_columns": ["gender", "SeniorCitizen", "tenure", "TotalCharges"],
        "feature_definitions": {
            "SeniorCitizen": {"type_intent": "requires_review"},
        },
        "blank_value_policy_candidates": {
            "TotalCharges": "unresolved_pending_review",
        },
        "execution_readiness": {
            "is_execution_ready": False,
            "blocking_reasons": [
                "TotalCharges: blank-value handling is only a candidate policy "
                "('unresolved_pending_review'), not yet accepted — requires "
                "explicit resolution before execution-ready use",
                "SeniorCitizen: feature type/semantic classification requires "
                "explicit review before execution-ready use",
                "split_policy: not supplied by this draft projection; required "
                "by execution_contract.v1 before promotion to an official "
                "contract",
            ],
        },
        "execution_contract_draft_boundary_confirmations": {
            "is_execution_contract": False,
            "model_training_performed": False,
        },
        "generated_at": "2026-07-09T00:00:00+00:00",
    }


def test_readiness_reports_missing_execution_contract_path(tmp_path: Path) -> None:
    _, dataset_path = _write_valid_inputs(tmp_path)
    missing_contract_path = tmp_path / "missing-execution-contract.json"

    with pytest.raises(TrainingInputError) as exc:
        prepare_training_invocation_readiness(missing_contract_path, dataset_path)

    assert exc.value.code == "missing_required_input"
    assert exc.value.field == "execution_contract_path"


def test_readiness_reports_missing_dataset_path(tmp_path: Path) -> None:
    contract_path, _ = _write_valid_inputs(tmp_path)
    missing_dataset_path = tmp_path / "missing-prepared-dataset.json"

    with pytest.raises(TrainingInputError) as exc:
        prepare_training_invocation_readiness(contract_path, missing_dataset_path)

    assert exc.value.code == "missing_required_input"
    assert exc.value.field == "dataset_path"


def test_readiness_reports_execution_ready_contract_as_training_ready(
    tmp_path: Path,
) -> None:
    contract_path = _write_json(
        tmp_path / "execution-contract.json", _synthetic_execution_ready_contract()
    )
    dataset_path = _write_json(
        tmp_path / "prepared-dataset.json", _synthetic_prepared_dataset()
    )

    readiness = prepare_training_invocation_readiness(contract_path, dataset_path)

    assert readiness["execution_contract_identity"] == "execution_ready"
    assert readiness["is_training_ready"] is True
    assert readiness["blocking_reasons"] == []
    assert readiness["dataset_id"] == "training-pipeline-test"
    assert readiness["target_column"] == "converted"
    assert readiness["governed_entrypoint"] == "pipeline.training.train_from_paths"


def test_readiness_rejects_execution_contract_draft_as_not_training_ready(
    tmp_path: Path,
) -> None:
    contract_path = _write_json(
        tmp_path / "execution-contract-draft.json", _synthetic_execution_contract_draft()
    )
    dataset_path = _write_json(
        tmp_path / "prepared-dataset.json", _synthetic_prepared_dataset()
    )

    readiness = prepare_training_invocation_readiness(contract_path, dataset_path)

    assert readiness["execution_contract_identity"] == "execution_contract_draft"
    assert readiness["is_training_ready"] is False
    assert readiness["dataset_id"] == "telco-customer-churn"
    assert readiness["target_column"] == "Churn"
    assert any(
        "execution_contract_draft.v1" in reason for reason in readiness["blocking_reasons"]
    )


def test_readiness_surfaces_unresolved_draft_review_items(tmp_path: Path) -> None:
    contract_path = _write_json(
        tmp_path / "execution-contract-draft.json", _synthetic_execution_contract_draft()
    )
    dataset_path = _write_json(
        tmp_path / "prepared-dataset.json", _synthetic_prepared_dataset()
    )

    readiness = prepare_training_invocation_readiness(contract_path, dataset_path)

    assert readiness["is_training_ready"] is False
    assert (
        "TotalCharges: blank-value handling is only a candidate policy "
        "('unresolved_pending_review'), not yet accepted — requires explicit "
        "resolution before execution-ready use"
    ) in readiness["blocking_reasons"]
    assert (
        "SeniorCitizen: feature type/semantic classification requires explicit "
        "review before execution-ready use"
    ) in readiness["blocking_reasons"]


def test_readiness_rejects_unrecognized_contract_identity(tmp_path: Path) -> None:
    contract_path = _write_json(
        tmp_path / "execution-contract.json",
        {"contract_version": "bank-marketing-custom.v1", "dataset_id": "bank-marketing"},
    )
    dataset_path = _write_json(
        tmp_path / "prepared-dataset.json", _synthetic_prepared_dataset()
    )

    readiness = prepare_training_invocation_readiness(contract_path, dataset_path)

    assert readiness["execution_contract_identity"] == "unrecognized_contract_identity"
    assert readiness["is_training_ready"] is False
    assert readiness["blocking_reasons"]


# ---------------------------------------------------------------------------
# Governed Telco training run materialization (Project Spec S0026)
# ---------------------------------------------------------------------------


def test_train_from_paths_rejects_execution_contract_draft(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(
        tmp_path / "execution-contract-draft.json", _synthetic_execution_contract_draft()
    )
    dataset_path = _write_json(
        tmp_path / "prepared-dataset.json", _valid_prepared_dataset()
    )

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "execution_contract_not_training_ready"
    assert exc.value.field == "execution_contract_path"
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_train_from_paths_rejects_validated_external_fitted_model_source(
    fixed_training_environment: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Project Spec S0157: a validated_external_fitted_model contract must be
    rejected before estimator construction or fit -- monkeypatching
    _build_estimator to raise proves the rejection happens before any
    estimator is ever constructed, not just before a would-be successful
    training run."""
    monkeypatch.setattr(
        training,
        "_build_estimator",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("estimator must never be constructed for validated_external_fitted_model")
        ),
    )
    contract = _valid_execution_contract()
    contract["model_source_mode"] = "validated_external_fitted_model"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "external_fitted_model_not_trainable_by_atlas"
    assert exc.value.field == "model_source_mode"
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_train_from_paths_explicit_atlas_internal_training_still_trains(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    """An explicit atlas_internal_training declaration proceeds through the
    existing internal-training path unchanged (Project Spec S0157)."""
    contract = _valid_execution_contract()
    contract["model_source_mode"] = "atlas_internal_training"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())

    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result.status == "trained"


def test_train_from_paths_legacy_contract_without_model_source_mode_still_trains(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    """A legacy contract omitting model_source_mode entirely retains the
    current atlas_internal_training behavior unchanged (Project Spec
    S0157)."""
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    assert "model_source_mode" not in json.loads(contract_path.read_text(encoding="utf-8"))

    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result.status == "trained"


def test_customer_id_feature_column_is_rejected(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    contract["feature_columns"].append("customerID")
    contract["feature_definitions"]["customerID"] = {"type": "categorical"}
    dataset = _valid_prepared_dataset()
    for row in dataset["rows"]:
        row["customerID"] = "0002-ORFBO"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "prohibited_training_feature"
    assert exc.value.field == "feature_columns"


def test_boolean_feature_type_mismatch_is_rejected(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    contract["feature_columns"].append("is_active")
    contract["feature_definitions"]["is_active"] = {"type": "boolean"}
    contract["missing_value_policy"]["is_active"] = "constant"
    dataset = _valid_prepared_dataset()
    boolean_encodings = ["0", "1", "Yes", "No", "true", "false", "1", "0"]
    for row, encoding in zip(dataset["rows"], boolean_encodings):
        row["is_active"] = encoding
    dataset["rows"][0]["is_active"] = "maybe"
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "contract_dataset_type_mismatch"
    assert exc.value.field == "feature_definitions.is_active"


def test_boolean_feature_accepts_mixed_established_encodings(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    """SeniorCitizen ('0'/'1') and Partner/Dependents ('Yes'/'No') are both
    declared type: boolean in the real Telco execution contract but use
    different on-disk encodings (confirmed via discovery-evidence.json) —
    both conventions must be accepted, not just one."""
    contract = _valid_execution_contract()
    contract["feature_columns"].append("is_active")
    contract["feature_definitions"]["is_active"] = {"type": "boolean"}
    contract["missing_value_policy"]["is_active"] = "constant"
    dataset = _valid_prepared_dataset()
    boolean_encodings = ["0", "1", "Yes", "No", "true", "false", "1", "0"]
    for row, encoding in zip(dataset["rows"], boolean_encodings):
        row["is_active"] = encoding
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result.status == "trained"


def test_unresolved_missing_value_policy_blocks_training(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    del contract["missing_value_policy"]["balance"]
    dataset = _valid_prepared_dataset()
    # A single-space blank, matching the real TotalCharges blank encoding
    # confirmed in data/raw/telco-customer-churn.csv.
    dataset["rows"][0]["balance"] = " "
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc:
        train_from_paths(
            contract_path,
            dataset_path,
            dataset_slug="training-pipeline-test",
            run_id="train-20260626T010700Z",
        )

    assert exc.value.code == "unresolved_missing_value_policy"
    assert exc.value.field == "missing_value_policy.balance"


def test_resolved_missing_value_policy_allows_training(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    assert "balance" in contract["missing_value_policy"]
    dataset = _valid_prepared_dataset()
    dataset["rows"][0]["balance"] = " "
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result.status == "trained"


def _not_produced_prepared_data_metadata() -> dict:
    """Shaped like the real, currently unresolved
    pipeline/evidence/telco-customer-churn/prepared-data-metadata.json:
    prepared_candidate.produced is false pending human review of TotalCharges
    blanks, so no real prepared dataset artifact exists yet."""
    return {
        "schema_version": "prepared-data-metadata.v1",
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {"dataset_slug": "training-pipeline-test"},
        "prepared_candidate": {
            "produced": False,
            "reason_not_produced": "1 inferred rule(s) are pending human review.",
            "reference": None,
        },
        "unresolved_review_items": [
            {
                "transformation_type": "missing_value_handling",
                "description": "Review balance blank values.",
                "review_status": "inferred_pending_review",
            }
        ],
        "training_readiness": {
            "is_final_training_input": False,
            "is_training_ready": False,
            "reason": "No prepared candidate has been produced yet.",
        },
    }


def _produced_prepared_data_metadata(reference) -> dict:
    return {
        "schema_version": "prepared-data-metadata.v1",
        "producer": "pipeline/prepare_candidate.py",
        "dataset_identity": {"dataset_slug": "training-pipeline-test"},
        "prepared_candidate": {
            "produced": True,
            "reason_not_produced": None,
            "reference": reference,
        },
        "unresolved_review_items": [],
        "training_readiness": {
            "is_final_training_input": True,
            "is_training_ready": True,
            "reason": None,
        },
    }


def test_materialize_training_run_blocked_when_prepared_candidate_not_produced(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json", _not_produced_prepared_data_metadata()
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "blocked"
    assert result["materialization_boundary_confirmations"]["model_training_performed"] is False
    assert any("prepared_candidate.produced" in reason for reason in result["blocking_reasons"])
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_materialize_training_run_blocked_when_execution_contract_is_draft(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())
    contract_path = _write_json(
        tmp_path / "execution-contract-draft.json", _synthetic_execution_contract_draft()
    )
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(str(dataset_path)),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "blocked"
    assert any(
        "execution_contract_draft.v1" in reason or "execution-ready" in reason
        for reason in result["blocking_reasons"]
    )
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_materialize_training_run_succeeds_when_ready(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    prepared_reference = "pipeline/prepared/training-pipeline-test/prepared-dataset.json"
    resolved_dataset_path = fixed_training_environment / prepared_reference
    resolved_dataset_path.parent.mkdir(parents=True)
    _write_json(resolved_dataset_path, _valid_prepared_dataset())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(prepared_reference),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "trained"
    assert result["materialization_boundary_confirmations"]["training_run_materialized"] is True
    training_result = result["training_result"]
    assert (
        training_result["output_directory"]
        == "pipeline/training-runs/training-pipeline-test/train-20260626T010700Z/"
    )
    output_directory = (
        fixed_training_environment / Path(training_result["serialized_model_path"]).parent
    )
    assert (output_directory / MODEL_ARTIFACT_FILENAME).exists()
    assert (output_directory / METRICS_ARTIFACT_FILENAME).exists()
    assert (output_directory / MODEL_CARD_FILENAME).exists()


def test_materialize_training_run_accepts_s0030_object_reference(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    prepared_reference = "pipeline/prepared/training-pipeline-test/prepared-dataset.json"
    resolved_dataset_path = fixed_training_environment / prepared_reference
    resolved_dataset_path.parent.mkdir(parents=True)
    _write_json(resolved_dataset_path, _valid_prepared_dataset())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(
            {
                "path": prepared_reference,
                "row_count": len(_valid_prepared_dataset()["rows"]),
                "column_count": 5,
                "content_sha256": _sha256_file(resolved_dataset_path),
            }
        ),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "trained"
    assert result["prepared_dataset_reference"] == prepared_reference


def test_materialize_training_run_blocks_when_object_reference_file_missing(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    prepared_reference = "pipeline/prepared/training-pipeline-test/missing-dataset.json"
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(
            {
                "path": prepared_reference,
                "row_count": len(_valid_prepared_dataset()["rows"]),
                "column_count": 5,
                "content_sha256": "not-used-when-file-is-missing",
            }
        ),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "blocked"
    assert result["prepared_dataset_reference"] == prepared_reference
    assert any(
        f"prepared dataset reference path does not exist: {prepared_reference}" in reason
        for reason in result["blocking_reasons"]
    )
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_materialize_training_run_blocks_when_object_reference_hash_mismatches(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    prepared_reference = "pipeline/prepared/training-pipeline-test/prepared-dataset.json"
    resolved_dataset_path = fixed_training_environment / prepared_reference
    resolved_dataset_path.parent.mkdir(parents=True)
    _write_json(resolved_dataset_path, _valid_prepared_dataset())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(
            {
                "path": prepared_reference,
                "row_count": len(_valid_prepared_dataset()["rows"]),
                "column_count": 5,
                "content_sha256": "0" * 64,
            }
        ),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "blocked"
    assert any("content_sha256 mismatch" in reason for reason in result["blocking_reasons"])
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_materialize_training_run_blocks_when_reference_outside_prepared_boundary(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata("data/raw/telco-customer-churn.csv"),
    )

    result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )

    assert result["status"] == "blocked"
    assert result["prepared_dataset_reference"] is None
    assert any("outside the expected prepared dataset artifact boundary" in reason for reason in result["blocking_reasons"])
    assert not (fixed_training_environment / "pipeline" / "training-runs").exists()


def test_convert_model_card_input_to_model_card(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )
    model_card_input_path = fixed_training_environment / result.model_card_input_path
    converted_path = tmp_path / "converted-model-card.json"

    convert_model_card_input_to_model_card(model_card_input_path, converted_path)

    converted = json.loads(converted_path.read_text(encoding="utf-8"))
    assert converted["schema_version"] == "model-card.v1"
    assert converted["artifact_kind"] == "model_card"
    assert converted["prediction_target"] == "converted"
    assert converted["hashes"]["model_card_input_sha256"] == _sha256_file(model_card_input_path)


def test_convert_model_card_input_to_model_card_rejects_wrong_schema_version(
    tmp_path: Path,
) -> None:
    wrong_shape_path = _write_json(
        tmp_path / "not-a-model-card-input.json", {"schema_version": "model-selection-evidence.v1"}
    )

    with pytest.raises(TrainingInputError) as exc:
        convert_model_card_input_to_model_card(wrong_shape_path, tmp_path / "model-card.json")

    assert exc.value.code == "invalid_model_card_input"
    assert exc.value.field == "model_card_input_path"


def test_normalize_training_handoff_references_uses_real_training_result_paths(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    prepared_reference = "pipeline/prepared/training-pipeline-test/prepared-dataset.json"
    resolved_dataset_path = fixed_training_environment / prepared_reference
    resolved_dataset_path.parent.mkdir(parents=True)
    _write_json(resolved_dataset_path, _valid_prepared_dataset())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json",
        _produced_prepared_data_metadata(prepared_reference),
    )

    materialization_result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )
    assert materialization_result["status"] == "trained"

    normalized = assemble_candidate.normalize_training_handoff_references(
        materialization_result,
        repo_root=fixed_training_environment,
    )

    training_result = materialization_result["training_result"]
    assert normalized["source_status"] == "trained"
    assert normalized["rejected_roles"] == {}
    assert normalized["role_paths"] == {
        "training_parameter_record": training_result["training_parameter_record_path"],
        "model_artifact": training_result["serialized_model_path"],
        "training_metrics": training_result["metrics_path"],
        "model_card": training_result["model_card_path"],
        "visualizations": training_result["analytical_visualizations_path"],
    }


def test_normalize_training_handoff_references_rejects_blocked_training_result(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path = _write_json(tmp_path / "execution-contract.json", _valid_execution_contract())
    metadata_path = _write_json(
        tmp_path / "prepared-data-metadata.json", _not_produced_prepared_data_metadata()
    )

    materialization_result = materialize_training_run_from_prepared_metadata(
        contract_path,
        metadata_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )
    assert materialization_result["status"] == "blocked"

    normalized = assemble_candidate.normalize_training_handoff_references(
        materialization_result,
        repo_root=fixed_training_environment,
    )

    assert normalized["source_status"] == "blocked"
    assert normalized["role_paths"] == {}
    assert normalized["rejected_roles"] == {}


def test_normalize_training_handoff_references_rejects_incomplete_trained_result(
    fixed_training_environment: Path,
) -> None:
    normalized = assemble_candidate.normalize_training_handoff_references(
        {"status": "trained"},
        repo_root=fixed_training_environment,
    )

    assert normalized["source_status"] == "trained_without_training_result"
    assert normalized["role_paths"] == {}


def test_normalize_training_handoff_references_rejects_unsafe_paths_in_training_result(
    fixed_training_environment: Path,
) -> None:
    unsafe_training_result = {
        "status": "trained",
        "training_result": {
            "training_parameter_record_path": "/etc/passwd",
            "serialized_model_path": "../outside-repo/model.pkl",
            "metrics_path": "pipeline/examples/metrics.json",
            "model_card_path": "pipeline/training-runs/training-pipeline-test/train-missing/model-card.json",
        },
    }

    normalized = assemble_candidate.normalize_training_handoff_references(
        unsafe_training_result,
        repo_root=fixed_training_environment,
    )

    assert normalized["role_paths"] == {}
    assert normalized["rejected_roles"] == {
        "training_parameter_record": "absolute_path_rejected",
        "model_artifact": "parent_traversal_rejected",
        "training_metrics": "fixture_only_path_rejected",
        "model_card": "missing_reference",
        "visualizations": "missing_reference",
    }


# --- governed positive class during training (Project Spec S0108) ---
# Uses target labels ("active"/"churned") that sort so that the *wrong*
# legacy classes_[1] convention ("churned") would silently diverge from the
# reviewed positive class ("active", classes_[0]) if governance were not
# actually wired in -- this is the "reversed class order" scenario the spec
# requires to be handled correctly.

def _binary_result_semantics_block(positive_class_id: str = "active", event_label: str = "Active") -> dict:
    return {
        "schema_version": "binary-result-semantics.v1",
        "problem_type": "binary_classification",
        "positive_class": {"class_id": positive_class_id, "event_label": event_label},
        "primary_output": "positive_class_probability",
        "decision": {"threshold": 0.5},
        "interpretation": {
            "preset": "risk",
            "bands": [
                {"band_id": "low", "lower_bound": 0.0, "upper_bound": 0.35},
                {"band_id": "medium", "lower_bound": 0.35, "upper_bound": 0.65},
                {"band_id": "high", "lower_bound": 0.65, "upper_bound": 1.0},
            ],
        },
    }


def _reversed_label_execution_contract(result_semantics: dict | None = None) -> dict:
    contract = _valid_execution_contract()
    contract["target_column"] = "status"
    contract["primary_metric"] = "roc_auc"
    contract["secondary_metrics"] = []
    if result_semantics is not None:
        contract["result_semantics"] = result_semantics
    return contract


def _reversed_label_prepared_dataset() -> dict:
    rows = [
        {"dataset_id": "training-pipeline-test", "age": 24, "segment": "retail", "balance": 1000, "status": "churned"},
        {"dataset_id": "training-pipeline-test", "age": 29, "segment": "smb", "balance": 2400, "status": "active"},
        {"dataset_id": "training-pipeline-test", "age": 36, "segment": "enterprise", "balance": 3600, "status": "churned"},
        {"dataset_id": "training-pipeline-test", "age": 41, "segment": "retail", "balance": 5200, "status": "active"},
        {"dataset_id": "training-pipeline-test", "age": 48, "segment": "smb", "balance": 7600, "status": "churned"},
        {"dataset_id": "training-pipeline-test", "age": 53, "segment": "enterprise", "balance": 9100, "status": "active"},
        {"dataset_id": "training-pipeline-test", "age": 61, "segment": "retail", "balance": 12000, "status": "churned"},
        {"dataset_id": "training-pipeline-test", "age": 68, "segment": "smb", "balance": 15000, "status": "active"},
    ]
    return {"dataset_id": "training-pipeline-test", "rows": rows}


def _write_reversed_label_inputs(tmp_path: Path, result_semantics: dict | None = None) -> tuple[Path, Path]:
    contract_path = _write_json(
        tmp_path / "execution-contract.json", _reversed_label_execution_contract(result_semantics)
    )
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _reversed_label_prepared_dataset())
    return contract_path, dataset_path


def test_binary_classification_evidence_absent_result_semantics_preserves_legacy_fallback(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    # No result_semantics at all (historical/non-binary-reviewed contract):
    # the original classes_[1] convention must be preserved unchanged.
    contract_path, dataset_path = _write_reversed_label_inputs(tmp_path, result_semantics=None)
    result = train_from_paths(
        contract_path, dataset_path,
        dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    parameter_record = json.loads(
        (output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text(encoding="utf-8")
    )
    evidence = parameter_record["binary_classification_evidence"]
    assert evidence["problem_type"] == "binary_classification"
    assert evidence["ordered_class_labels"] == ["active", "churned"]
    assert evidence["positive_class_id"] == "churned"
    assert evidence["positive_class_probability_index"] == 1


def test_binary_classification_evidence_uses_governed_positive_class(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    # With a reviewed result_semantics present, the governed positive class
    # ("active", classes_[0]) must be used -- not the legacy classes_[1]
    # ("churned") convention -- even though "churned" is what the old
    # ordering-based fallback would have silently picked.
    contract_path, dataset_path = _write_reversed_label_inputs(
        tmp_path, result_semantics=_binary_result_semantics_block(positive_class_id="active")
    )
    result = train_from_paths(
        contract_path, dataset_path,
        dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    parameter_record = json.loads(
        (output_directory / TRAINING_PARAMETER_RECORD_FILENAME).read_text(encoding="utf-8")
    )
    evidence = parameter_record["binary_classification_evidence"]
    assert evidence["ordered_class_labels"] == ["active", "churned"]
    assert evidence["positive_class_id"] == "active"
    assert evidence["positive_class_probability_index"] == 0


def test_governed_positive_class_absent_from_model_classes_raises_deterministic_error(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_reversed_label_inputs(
        tmp_path, result_semantics=_binary_result_semantics_block(positive_class_id="left_the_company")
    )
    with pytest.raises(TrainingInputError) as exc_info:
        train_from_paths(
            contract_path, dataset_path,
            dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
        )
    assert exc_info.value.code == "positive_class_not_in_model_classes"


def test_model_selection_evidence_records_classification_evidence_per_candidate(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _reversed_label_execution_contract(
        result_semantics=_binary_result_semantics_block(positive_class_id="active")
    )
    contract["modeling_constraints"]["allowed_model_families"] = ["logistic_regression", "random_forest"]
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _reversed_label_prepared_dataset())

    result = train_from_paths(
        contract_path, dataset_path,
        dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    assert result.model_selection_evidence_produced is True
    output_directory = fixed_training_environment / result.output_directory
    from pipeline.training import MODEL_SELECTION_EVIDENCE_FILENAME
    selection_evidence = json.loads(
        (output_directory / MODEL_SELECTION_EVIDENCE_FILENAME).read_text(encoding="utf-8")
    )
    assert len(selection_evidence["candidates"]) == 2
    for candidate in selection_evidence["candidates"]:
        classification_evidence = candidate["classification_evidence"]
        assert classification_evidence["positive_class_id"] == "active"
        assert classification_evidence["ordered_class_labels"] == ["active", "churned"]


# ---------------------------------------------------------------------------
# Analytical visualizations generation (Project Spec S0128)
# ---------------------------------------------------------------------------

_ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH = (
    Path(__file__).parent.parent / "pipeline" / "analytical-visualizations.schema.json"
)


def _analytical_visualizations_schema() -> dict:
    return json.loads(_ANALYTICAL_VISUALIZATIONS_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_analytical_visualizations_artifact_generated_with_canonical_identity_and_hash(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    import jsonschema

    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    result = train_from_paths(
        contract_path,
        dataset_path,
        dataset_slug="training-pipeline-test",
        run_id="train-20260626T010700Z",
    )
    output_directory = fixed_training_environment / result.output_directory
    artifact_path = output_directory / ANALYTICAL_VISUALIZATIONS_FILENAME
    assert artifact_path.exists()
    assert result.analytical_visualizations_path == f"{result.output_directory}{ANALYTICAL_VISUALIZATIONS_FILENAME}"
    assert result.hashes["analytical_visualizations_sha256"] == _sha256_file(artifact_path)

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(_analytical_visualizations_schema()).validate(artifact)
    assert artifact["schema_version"] == ANALYTICAL_VISUALIZATIONS_SCHEMA_VERSION
    assert artifact["artifact_kind"] == "analytical_visualizations"

    charts_by_id = {chart["id"]: chart for chart in artifact["charts"]}
    assert set(charts_by_id) == {"target_distribution", "feature_importance"}

    # _valid_prepared_dataset(): 4 rows converted=0, 4 rows converted=1.
    target_data = charts_by_id["target_distribution"]["data"]
    assert target_data == [{"name": "0", "value": 4}, {"name": "1", "value": 4}]
    assert sum(point["value"] for point in target_data) == artifact["target_distribution_method"]["row_count"]
    assert artifact["target_distribution_method"]["population_kind"] == "prepared_dataset"
    assert artifact["target_distribution_method"]["target_column"] == "converted"

    # One-hot categorical levels must aggregate back into "segment", never
    # leak a transformed feature name such as "segment_retail".
    feature_names = {point["name"] for point in charts_by_id["feature_importance"]["data"]}
    assert feature_names <= {"age", "segment", "balance"}
    for point in charts_by_id["feature_importance"]["data"]:
        assert point["value"] >= 0.0

    # No raw rows, model bytes, or absolute local paths embedded.
    raw_text = artifact_path.read_text(encoding="utf-8")
    assert str(fixed_training_environment) not in raw_text
    assert "balance\": 1000" not in raw_text
    assert artifact["evidence_policy"]["model_bytes_embedded"] is False
    assert artifact["evidence_policy"]["raw_dataset_embedded"] is False
    assert artifact["evidence_policy"]["serialized_estimator_state_embedded"] is False
    assert artifact["evidence_policy"]["raw_transformed_matrices_embedded"] is False


def test_analytical_visualizations_deterministic_across_repeated_training(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)
    first = train_from_paths(
        contract_path, dataset_path, dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    second = train_from_paths(
        contract_path, dataset_path, dataset_slug="training-pipeline-test", run_id="train-20260626T010701Z",
    )
    first_artifact = json.loads(
        (fixed_training_environment / first.analytical_visualizations_path).read_text(encoding="utf-8")
    )
    second_artifact = json.loads(
        (fixed_training_environment / second.analytical_visualizations_path).read_text(encoding="utf-8")
    )
    assert first_artifact["charts"] == second_artifact["charts"]
    assert (
        first_artifact["feature_importance_method"]["model_family"]
        == second_artifact["feature_importance_method"]["model_family"]
    )


def test_random_forest_feature_importance_uses_native_estimator_importance(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    contract["modeling_constraints"]["allowed_model_families"] = ["random_forest"]
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", _valid_prepared_dataset())

    result = train_from_paths(
        contract_path, dataset_path, dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    artifact = json.loads(
        (fixed_training_environment / result.analytical_visualizations_path).read_text(encoding="utf-8")
    )
    assert artifact["feature_importance_method"]["model_family"] == "random_forest"
    assert artifact["feature_importance_method"]["source"] == "estimator.feature_importances_"


def test_logistic_regression_binary_feature_importance_uses_absolute_coefficients(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract_path, dataset_path = _write_valid_inputs(tmp_path)  # logistic_regression by default

    result = train_from_paths(
        contract_path, dataset_path, dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
    )
    artifact = json.loads(
        (fixed_training_environment / result.analytical_visualizations_path).read_text(encoding="utf-8")
    )
    assert artifact["feature_importance_method"]["model_family"] == "logistic_regression"
    assert artifact["feature_importance_method"]["source"] == "abs(estimator.coef_)"


def test_multiclass_logistic_regression_feature_importance_is_rejected(
    fixed_training_environment: Path,
    tmp_path: Path,
) -> None:
    contract = _valid_execution_contract()
    contract["target_column"] = "segment"
    contract["feature_columns"] = ["age", "balance"]
    contract["missing_value_policy"] = {"age": "median", "balance": "median"}
    contract["modeling_constraints"]["allowed_model_families"] = ["logistic_regression"]
    contract_path = _write_json(tmp_path / "execution-contract.json", contract)

    dataset = _valid_prepared_dataset()
    # "segment" already carries three classes (retail/smb/enterprise) in the
    # base fixture, giving a genuine multiclass logistic_regression fit.
    dataset_path = _write_json(tmp_path / "prepared-dataset.json", dataset)

    with pytest.raises(TrainingInputError) as exc_info:
        train_from_paths(
            contract_path, dataset_path, dataset_slug="training-pipeline-test", run_id="train-20260626T010700Z",
        )
    assert exc_info.value.code == "unsupported_estimator_for_feature_importance"


def test_target_distribution_rejects_missing_target_value() -> None:
    rows = [{"converted": "0"}, {"converted": None}]
    with pytest.raises(TrainingInputError) as exc_info:
        _target_distribution_chart_data(rows, "converted")
    assert exc_info.value.code == "missing_target_value_for_visualization"


def test_target_distribution_label_order_is_deterministic_and_sums_to_population() -> None:
    rows = [{"churn": "Yes"}, {"churn": "No"}, {"churn": "Yes"}, {"churn": "No"}, {"churn": "No"}]
    data, row_count = _target_distribution_chart_data(rows, "churn")
    assert data == [{"name": "No", "value": 3}, {"name": "Yes", "value": 2}]
    assert row_count == len(rows) == sum(point["value"] for point in data)


def test_feature_importance_output_source_map_rejects_unmappable_transformer_block() -> None:
    class _StubColumnTransformer:
        transformers_ = [("remainder", None, ["mystery_column"])]

    with pytest.raises(TrainingInputError) as exc_info:
        _feature_importance_output_source_map(_StubColumnTransformer())
    assert exc_info.value.code == "unmappable_transformed_feature"


def test_aggregate_feature_importance_rejects_zero_total() -> None:
    with pytest.raises(TrainingInputError) as exc_info:
        _aggregate_feature_importance(["a", "b"], [0.0, 0.0], ["a", "b"])
    assert exc_info.value.code == "zero_total_feature_importance"


def test_aggregate_feature_importance_rejects_non_finite_value() -> None:
    with pytest.raises(TrainingInputError) as exc_info:
        _aggregate_feature_importance(["a", "b"], [float("inf"), 1.0], ["a", "b"])
    assert exc_info.value.code == "non_finite_feature_importance"


def test_aggregate_feature_importance_truncates_to_top_ten_with_deterministic_ties() -> None:
    source_names = [f"feature-{index:02d}" for index in range(12)]
    raw_values = [1.0] * 12  # a full tie: descending value, then ascending name breaks it.
    data, total_source_feature_count, omitted_count = _aggregate_feature_importance(
        source_names, raw_values, source_names,
    )
    assert total_source_feature_count == 12
    assert omitted_count == 2
    assert len(data) == 10
    assert [point["name"] for point in data] == sorted(source_names)[:10]
    assert data == sorted(data, key=lambda point: (-point["value"], point["name"]))


def test_aggregate_feature_importance_aggregates_one_hot_levels_into_source_feature() -> None:
    # Three transformed one-hot columns for "segment" plus one numeric "age"
    # column must aggregate into exactly two source-feature entries.
    source_names = ["segment", "segment", "segment", "age"]
    raw_values = [0.1, 0.2, 0.05, 0.3]
    data, total_source_feature_count, omitted_count = _aggregate_feature_importance(
        source_names, raw_values, ["age", "segment"],
    )
    assert total_source_feature_count == 2
    assert omitted_count == 0
    values_by_name = {point["name"]: point["value"] for point in data}
    assert set(values_by_name) == {"age", "segment"}
    assert values_by_name["segment"] == pytest.approx(0.35 / 0.65)
    assert values_by_name["age"] == pytest.approx(0.3 / 0.65)


# --- Project Spec S0216: native multiclass fixed-configuration helper
# unit tests (isolated pure-function coverage, complementing the real,
# slower end-to-end run in tests/test_native_multiclass_training.py) ------


def _fixed_hgb_hyperparameters(**overrides):
    base = {
        "class_weight": None,
        "l2_regularization": 0.0,
        "learning_rate": 0.05,
        "max_iter": 250,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 40,
    }
    base.update(overrides)
    return base


def _fixed_hgb_modeling_constraints(**hyperparameter_overrides):
    return {
        "allowed_model_families": ["hist_gradient_boosting"],
        "no_automl": True,
        "selection_mode": "fixed_configuration",
        "fixed_model_configuration": {
            "model_family": "hist_gradient_boosting",
            "hyperparameters": _fixed_hgb_hyperparameters(**hyperparameter_overrides),
        },
    }


def test_native_multiclass_metric_names_are_the_bounded_seven():
    assert set(NATIVE_MULTICLASS_METRIC_NAMES) == {
        "accuracy", "balanced_accuracy", "f1_macro", "f1_weighted",
        "precision_macro", "recall_macro", "log_loss",
    }
    assert NATIVE_MULTICLASS_MINIMUM_CLASS_COUNT == 3


def test_validate_fixed_model_configuration_accepts_valid_hgb_configuration():
    model_family, hyperparameters = _validate_fixed_model_configuration(_fixed_hgb_modeling_constraints())
    assert model_family == "hist_gradient_boosting"
    assert hyperparameters["max_iter"] == 250


def test_validate_fixed_model_configuration_rejects_missing_fixed_model_configuration():
    constraints = {"allowed_model_families": ["hist_gradient_boosting"], "selection_mode": "fixed_configuration"}
    with pytest.raises(TrainingInputError):
        _validate_fixed_model_configuration(constraints)


def test_validate_fixed_model_configuration_rejects_family_not_solely_allowed():
    constraints = _fixed_hgb_modeling_constraints()
    constraints["allowed_model_families"] = ["hist_gradient_boosting", "gradient_boosting"]
    with pytest.raises(TrainingInputError):
        _validate_fixed_model_configuration(constraints)


def test_validate_fixed_model_configuration_rejects_unsupported_family():
    constraints = _fixed_hgb_modeling_constraints()
    constraints["allowed_model_families"] = ["gradient_boosting"]
    constraints["fixed_model_configuration"]["model_family"] = "gradient_boosting"
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_model_configuration(constraints)
    assert excinfo.value.code == "unsupported_model_family"


def test_validate_fixed_model_configuration_rejects_missing_required_hyperparameter():
    constraints = _fixed_hgb_modeling_constraints()
    del constraints["fixed_model_configuration"]["hyperparameters"]["learning_rate"]
    with pytest.raises(TrainingInputError):
        _validate_fixed_model_configuration(constraints)


def test_validate_fixed_model_configuration_rejects_unsupported_hyperparameter():
    constraints = _fixed_hgb_modeling_constraints()
    constraints["fixed_model_configuration"]["hyperparameters"]["n_estimators"] = 100
    with pytest.raises(TrainingInputError) as excinfo:
        _validate_fixed_model_configuration(constraints)
    assert excinfo.value.code == "unsupported_hyperparameter"


def test_stratified_three_way_split_indices_is_deterministic_stratified_and_complete():
    rows = []
    for label, count in (("a", 30), ("b", 20), ("c", 10)):
        rows.extend({"target": label} for _ in range(count))

    train_a, val_a, test_a = _stratified_three_way_split_indices(rows, "target", 0.7, 0.15, 0.15, 42)
    train_b, val_b, test_b = _stratified_three_way_split_indices(rows, "target", 0.7, 0.15, 0.15, 42)
    assert (train_a, val_a, test_a) == (train_b, val_b, test_b)

    all_indices = sorted(train_a + val_a + test_a)
    assert all_indices == list(range(len(rows)))
    assert set(train_a).isdisjoint(val_a)
    assert set(train_a).isdisjoint(test_a)
    assert set(val_a).isdisjoint(test_a)

    for label_indices in (train_a, val_a, test_a):
        labels = {rows[i]["target"] for i in label_indices}
        assert labels == {"a", "b", "c"}


def test_stratified_three_way_split_indices_different_seed_changes_assignment():
    rows = [{"target": "a"} for _ in range(20)] + [{"target": "b"} for _ in range(20)]
    split_1 = _stratified_three_way_split_indices(rows, "target", 0.7, 0.15, 0.15, 1)
    split_2 = _stratified_three_way_split_indices(rows, "target", 0.7, 0.15, 0.15, 2)
    assert split_1 != split_2


def test_stratified_three_way_split_indices_requires_at_least_two_classes():
    rows = [{"target": "a"} for _ in range(10)]
    with pytest.raises(ValueError):
        _stratified_three_way_split_indices(rows, "target", 0.7, 0.15, 0.15, 0)


def test_native_multiclass_requested_metric_names_rejects_unsupported_metric():
    contract = {"primary_metric": "roc_auc", "secondary_metrics": []}
    with pytest.raises(TrainingInputError):
        _native_multiclass_requested_metric_names(contract)


def test_native_multiclass_requested_metric_names_deduplicates_primary_and_secondary():
    contract = {"primary_metric": "f1_macro", "secondary_metrics": ["f1_macro", "accuracy"]}
    assert _native_multiclass_requested_metric_names(contract) == ["f1_macro", "accuracy"]


def test_native_multiclass_metric_values_computes_the_full_bounded_set():
    y_true = ["a", "a", "b", "b", "c", "c"]
    y_pred = ["a", "a", "b", "c", "c", "c"]
    y_proba = [
        [0.9, 0.05, 0.05], [0.8, 0.1, 0.1], [0.1, 0.8, 0.1],
        [0.1, 0.1, 0.8], [0.1, 0.1, 0.8], [0.05, 0.05, 0.9],
    ]
    values = _native_multiclass_metric_values(
        y_true=y_true, y_pred=y_pred, y_proba=y_proba, classes=["a", "b", "c"],
        metric_names=list(NATIVE_MULTICLASS_METRIC_NAMES),
    )
    assert set(values) == set(NATIVE_MULTICLASS_METRIC_NAMES)
    for name, value in values.items():
        assert isinstance(value, float)
        assert value == value  # not NaN
    assert values["accuracy"] == pytest.approx(5 / 6)


def test_native_multiclass_metric_values_rejects_unsupported_metric():
    with pytest.raises(TrainingInputError):
        _native_multiclass_metric_values(
            y_true=["a", "b"], y_pred=["a", "b"], y_proba=[[1, 0], [0, 1]],
            classes=["a", "b"], metric_names=["roc_auc"],
        )


def test_native_multiclass_per_class_metrics_covers_every_class_in_order():
    y_true = ["a", "a", "b", "b", "c", "c"]
    y_pred = ["a", "b", "b", "b", "c", "c"]
    entries = _native_multiclass_per_class_metrics(y_true=y_true, y_pred=y_pred, classes=["a", "b", "c"])
    assert [entry["class_id"] for entry in entries] == ["a", "b", "c"]
    for entry in entries:
        assert 0.0 <= entry["precision"] <= 1.0
        assert 0.0 <= entry["recall"] <= 1.0
        assert 0.0 <= entry["f1"] <= 1.0
        assert entry["support"] >= 0


def test_native_multiclass_confusion_matrix_rows_sum_to_one():
    y_true = ["a", "a", "b", "b", "c", "c"]
    y_pred = ["a", "a", "b", "c", "c", "c"]
    matrix = _native_multiclass_confusion_matrix(y_true=y_true, y_pred=y_pred, classes=["a", "b", "c"])
    assert len(matrix) == 3
    for row in matrix:
        assert len(row) == 3
        assert sum(row) == pytest.approx(1.0, abs=1e-9)
        assert all(0.0 <= value <= 1.0 for value in row)


def test_cross_check_authored_multiclass_class_order_passes_when_matching():
    full_contract = {
        "result_semantics": {
            "schema_version": "multiclass-result-semantics.v1",
            "problem_type": "multiclass_classification",
            "decision": {"strategy": "argmax"},
            "classes": [{"class_id": "a"}, {"class_id": "b"}, {"class_id": "c"}],
        }
    }
    _cross_check_authored_multiclass_class_order(full_contract, ["a", "b", "c"])


def test_cross_check_authored_multiclass_class_order_raises_on_mismatch():
    full_contract = {
        "result_semantics": {
            "schema_version": "multiclass-result-semantics.v1",
            "problem_type": "multiclass_classification",
            "decision": {"strategy": "argmax"},
            "classes": [{"class_id": "a"}, {"class_id": "b"}, {"class_id": "c"}],
        }
    }
    with pytest.raises(TrainingInputError) as excinfo:
        _cross_check_authored_multiclass_class_order(full_contract, ["b", "a", "c"])
    assert excinfo.value.code == "result_semantics_cross_artifact_mismatch"


def test_cross_check_authored_multiclass_class_order_is_a_noop_when_result_semantics_absent():
    _cross_check_authored_multiclass_class_order({}, ["a", "b", "c"])


def test_legacy_binary_train_candidate_models_path_unaffected_by_native_multiclass_functions():
    # Regression: the new S0216 fixed-configuration pipeline must never
    # extend the legacy multi-candidate selection path's own supported
    # family set -- S0216 does not generalize native multiclass model
    # selection, so hist_gradient_boosting must never become selectable
    # there.
    assert set(training.SUPPORTED_MODEL_FAMILIES) == {
        "logistic_regression", "gradient_boosting", "random_forest",
    }
    assert "hist_gradient_boosting" not in training.SUPPORTED_MODEL_FAMILIES

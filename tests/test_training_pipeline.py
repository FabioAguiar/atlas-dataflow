import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import pipeline.training as training
from pipeline.training import (
    MODEL_ARTIFACT_FILENAME,
    MODEL_CARD_INPUT_FILENAME,
    METRICS_ARTIFACT_FILENAME,
    TRAINING_PARAMETER_RECORD_FILENAME,
    TrainingInputError,
    _load_json_file,
    _require_valid_controlled_entrypoint_provenance,
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

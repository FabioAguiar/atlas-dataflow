import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.promote_contract import PromotionRejected, promote
from pipeline.validate_contract_consistency import check
from pipeline.derive_projections import DerivationFailed, derive
from pipeline.training import (
    CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION,
    TrainingInputError,
    _controlled_entrypoint_provenance_marker,
    _require_valid_controlled_entrypoint_provenance,
    _validate_contract_model_compatibility,
)

REPO_ROOT = Path(__file__).parent.parent


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_human_contract() -> dict:
    """Minimal well-formed human-facing contract with mixed types, optional field, and rejected field."""
    return {
        "promotion_boundary": {"promotion_authorized": True},
        "dataset_id": "pipeline-test-dataset",
        "target_field": {"name": "outcome"},
        "candidate_fields": [
            {
                "name": "age",
                "review_status": "approved",
                "field_type": "numeric",
                "sample_min": 18,
                "sample_max": 90,
                "missing_value_strategy": "mean",
            },
            {
                "name": "job",
                "review_status": "approved",
                "field_type": "categorical",
                "known_values": ["admin", "technician", "services"],
            },
            {
                "name": "has_loan",
                "review_status": "approved",
                "field_type": "boolean",
                "optional": True,
            },
            {
                "name": "noise",
                "review_status": "rejected",
                "field_type": "numeric",
            },
        ],
    }


def _valid_discovery_evidence(feature_columns: list, target_column: str) -> dict:
    """Minimal valid discovery evidence covering all feature columns and the target column."""
    _inferred = {
        "age": ("integer", 18, 90),
        "job": ("string", "admin", "technician"),
        "has_loan": ("boolean", False, True),
        target_column: ("integer", 0, 1),
    }
    fields = []
    for col in list(feature_columns) + [target_column]:
        inferred_type, sample_min, sample_max = _inferred.get(col, ("string", None, None))
        fields.append({
            "name": col,
            "inferred_type": inferred_type,
            "null_count": 0,
            "null_rate": 0.0,
            "cardinality": 10,
            "sample_min": sample_min,
            "sample_max": sample_max,
        })
    return {
        "schema_version": "dataset-discovery-evidence.v1",
        "producer": "pipeline/discovery_evidence.py",
        "dataset_metadata": {
            "name": "pipeline-test-dataset",
            "row_count": 10000,
            "column_count": len(fields),
            "source_path": "data/test.csv",
        },
        "field_observations": fields,
        "duplicated_rows_count": 0,
        "candidate_categorical_fields": ["job"],
        "candidate_target_columns": [{"name": target_column, "is_authoritative": False}],
        "generation_settings": {"seed": 42, "generator_version": "1.0.0"},
        "generated_at": "2026-06-24T00:00:00Z",
        "discovery_boundary_confirmations": {
            "contract_promotion_occurred": False,
            "model_training_occurred": False,
            "release_publication_occurred": False,
        },
        "evidence_policy": {
            "raw_logs_prohibited": True,
            "raw_runtime_prohibited": True,
            "raw_api_payloads_prohibited": True,
            "secrets_prohibited": True,
            "private_source_paths_prohibited": True,
            "reduced_and_sanitized": True,
        },
    }


def test_promote_output_is_valid_derive_input(tmp_path: Path) -> None:
    """promote() output written to a tmp file passes derive() without error."""
    human_path = _write_json(tmp_path, "human.json", _valid_human_contract())
    execution_contract = promote(human_path, repo_root=REPO_ROOT)
    contract_path = _write_json(tmp_path, "contract.json", execution_contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    assert (out_dir / "runtime-contract.json").exists()
    assert (out_dir / "public-contract.json").exists()


def test_pipeline_runtime_features_match_promotion_feature_columns(tmp_path: Path) -> None:
    """Feature names in the runtime projection match feature_columns from the promoted execution contract."""
    human_path = _write_json(tmp_path, "human.json", _valid_human_contract())
    execution_contract = promote(human_path, repo_root=REPO_ROOT)
    contract_path = _write_json(tmp_path, "contract.json", execution_contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text(encoding="utf-8"))
    runtime_names = {f["name"] for f in runtime["features"]}
    assert runtime_names == set(execution_contract["feature_columns"])


def test_pipeline_public_excludes_ignored_columns(tmp_path: Path) -> None:
    """A column with review_status rejected in the human contract is absent from the public projection."""
    human_path = _write_json(tmp_path, "human.json", _valid_human_contract())
    execution_contract = promote(human_path, repo_root=REPO_ROOT)
    assert "noise" in execution_contract["ignored_columns"]
    contract_path = _write_json(tmp_path, "contract.json", execution_contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    public = json.loads((out_dir / "public-contract.json").read_text(encoding="utf-8"))
    public_names = {f["name"] for f in public["features"]}
    assert "noise" not in public_names


def test_promote_then_check_and_derive_with_realistic_fixture(tmp_path: Path) -> None:
    """Full promote()→check()→derive() chain with a mixed-type fixture including optional column and explicit missing_value_strategy."""
    human_path = _write_json(tmp_path, "human.json", _valid_human_contract())
    execution_contract = promote(human_path, repo_root=REPO_ROOT)
    contract_path = _write_json(tmp_path, "contract.json", execution_contract)
    evidence = _valid_discovery_evidence(
        execution_contract["feature_columns"],
        execution_contract["target_column"],
    )
    evidence_path = _write_json(tmp_path, "evidence.json", evidence)
    check(contract_path, evidence_path, repo_root=REPO_ROOT)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    assert (out_dir / "runtime-contract.json").exists()
    assert (out_dir / "public-contract.json").exists()
    assert execution_contract["missing_value_policy"]["age"] == "mean"
    assert "has_loan" in execution_contract["optional_columns"]


def test_promoted_categorical_field_without_known_values_blocks_derive(tmp_path: Path) -> None:
    """Project Spec S0102: a human-facing contract field approved as
    categorical but with no reviewed known_values promotes fine (promote()
    has no readiness opinion), but the resulting execution contract's
    categorical feature never gets domain_constraints -- so the full
    promote()->derive() pipeline must raise DerivationFailed at the
    projection stage, end to end, not just at the unit level."""
    data = _valid_human_contract()
    for field in data["candidate_fields"]:
        if field["name"] == "job":
            field.pop("known_values", None)
    human_path = _write_json(tmp_path, "human.json", data)
    execution_contract = promote(human_path, repo_root=REPO_ROOT)
    assert "domain_constraints" not in execution_contract["feature_definitions"]["job"]
    contract_path = _write_json(tmp_path, "contract.json", execution_contract)
    out_dir = tmp_path / "out"
    with pytest.raises(DerivationFailed) as exc_info:
        derive(contract_path, out_dir, repo_root=REPO_ROOT)
    assert any("job" in e for e in exc_info.value.errors)
    assert not out_dir.exists()


def test_rejected_promotion_does_not_reach_derive(tmp_path: Path) -> None:
    """A contract with promotion_authorized: false raises PromotionRejected; derive() must never be called."""
    data = _valid_human_contract()
    data["promotion_boundary"]["promotion_authorized"] = False
    human_path = _write_json(tmp_path, "human.json", data)
    with pytest.raises(PromotionRejected):
        promote(human_path, repo_root=REPO_ROOT)
    out_dir = tmp_path / "out"
    assert not out_dir.exists()


class _FittedCompatibleModel:
    n_features_in_ = 3
    feature_names_in_ = ["age", "job", "has_loan"]
    classes_ = [0, 1]

    def predict(self, rows):
        return [0 for _ in rows]


def _minimal_training_contract() -> dict:
    return {
        "dataset_id": "pipeline-test-dataset",
        "target_column": "outcome",
        "feature_columns": ["age", "job", "has_loan"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.7,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
        },
        "random_seed": 42,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1"],
        "modeling_constraints": {
            "allowed_model_families": ["logistic_regression"],
        },
    }


def test_training_rejects_model_incompatible_with_contract_feature_count() -> None:
    """Contract/model compatibility errors name the contract field and model interface expectation."""
    model = _FittedCompatibleModel()
    model.n_features_in_ = 2

    with pytest.raises(TrainingInputError) as exc:
        _validate_contract_model_compatibility(
            contract=_minimal_training_contract(),
            model=model,
            task_type="classification",
        )

    assert exc.value.code == "contract_model_compatibility_failed"
    assert exc.value.field == "feature_columns:n_features_in_"
    assert "feature_columns" in str(exc.value)
    assert "n_features_in_" in str(exc.value)


def test_markerless_training_parameter_record_is_rejected_downstream() -> None:
    """Downstream artifact acceptance fails without controlled-entrypoint provenance."""
    with pytest.raises(TrainingInputError) as exc:
        _require_valid_controlled_entrypoint_provenance({
            "schema_version": "training-parameter-record.v1",
            "record_kind": "training_parameter_record",
        })

    assert exc.value.code == "missing_controlled_entrypoint_provenance"
    assert exc.value.field == "controlled_entrypoint_provenance"


def test_controlled_entrypoint_marker_is_structured_and_non_static(tmp_path: Path) -> None:
    """Controlled entrypoint provenance is derived from run inputs, not a static/path-only marker."""
    contract_path = _write_json(tmp_path, "contract.json", {"dataset_id": "pipeline-test-dataset"})
    dataset_path = _write_json(tmp_path, "dataset.json", {"dataset_id": "pipeline-test-dataset", "rows": []})
    output_directory = REPO_ROOT / "pipeline" / "training-runs" / "pipeline-test-dataset" / "train-20260626T003538Z"

    marker = _controlled_entrypoint_provenance_marker(
        contract_path=contract_path,
        dataset_path=dataset_path,
        output_directory=output_directory,
        training_timestamp="2026-06-26T00:35:38Z",
    )

    assert marker["marker_version"] == CONTROLLED_ENTRYPOINT_PROVENANCE_VERSION
    assert marker["marker_kind"] == "controlled_training_entrypoint"
    assert marker["entrypoint"] == "pipeline.training.train_from_paths"
    assert marker["run_id"] == "train-20260626T003538Z"
    assert len(marker["marker_id"]) == 64
    assert marker["marker_id"] not in {
        marker["run_id"],
        marker["output_directory"],
        marker["generated_at"],
    }
    assert _require_valid_controlled_entrypoint_provenance({
        "controlled_entrypoint_provenance": marker,
    }) == marker

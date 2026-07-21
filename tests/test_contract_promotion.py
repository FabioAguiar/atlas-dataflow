import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.promote_contract import PromotionRejected, promote

REPO_ROOT = Path(__file__).parent.parent
BANK_MARKETING_CONTRACT = (
    REPO_ROOT / "contracts" / "bank-marketing" / "human-facing-contract-draft.json"
)


def _write(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "contract.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_contract() -> dict:
    """Minimal well-formed human-facing contract ready for promotion."""
    return {
        "promotion_boundary": {"promotion_authorized": True},
        "dataset_id": "test-dataset",
        "target_field": {"name": "outcome"},
        "candidate_fields": [
            {
                "name": "age",
                "review_status": "approved",
                "field_type": "numeric",
                "sample_min": 18,
                "sample_max": 90,
            },
            {
                "name": "category",
                "review_status": "approved",
                "field_type": "categorical",
                "known_values": ["a", "b", "c"],
            },
            {
                "name": "rejected_field",
                "review_status": "rejected",
                "field_type": "numeric",
            },
        ],
    }


def test_valid_contract_produces_execution_contract(tmp_path: Path) -> None:
    path = _write(tmp_path, _valid_contract())
    result = promote(path, repo_root=REPO_ROOT)

    assert result["contract_version"] == "execution_contract.v1"
    assert result["dataset_id"] == "test-dataset"
    assert result["target_column"] == "outcome"
    assert "age" in result["feature_columns"]
    assert "category" in result["feature_columns"]
    assert "rejected_field" in result["ignored_columns"]
    assert "age" in result["feature_definitions"]
    assert result["feature_definitions"]["age"]["type"] == "numeric"
    assert "category" in result["feature_definitions"]
    assert result["feature_definitions"]["category"]["type"] == "categorical"
    assert result["feature_definitions"]["category"]["domain_constraints"] == {
        "values": ["a", "b", "c"]
    }


def test_execution_contract_conforms_to_schema(tmp_path: Path) -> None:
    import jsonschema

    schema = json.loads(
        (REPO_ROOT / "contracts" / "execution-contract.schema.json").read_text(encoding="utf-8")
    )
    path = _write(tmp_path, _valid_contract())
    result = promote(path, repo_root=REPO_ROOT)
    jsonschema.validate(result, schema)


def test_promotion_authorized_false_rejected(tmp_path: Path) -> None:
    """Reservation-01: gate must be honored for promotion_authorized: false."""
    data = _valid_contract()
    data["promotion_boundary"]["promotion_authorized"] = False
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("promotion_authorized" in e for e in exc_info.value.errors)


def test_bank_marketing_draft_rejected_at_gate(tmp_path: Path) -> None:
    """Reservation-01: the M22 bank-marketing draft must be rejected at the promotion gate."""
    assert BANK_MARKETING_CONTRACT.exists(), (
        f"Expected bank-marketing contract at {BANK_MARKETING_CONTRACT}"
    )
    with pytest.raises(PromotionRejected) as exc_info:
        promote(BANK_MARKETING_CONTRACT, repo_root=REPO_ROOT)

    assert any("promotion_authorized" in e for e in exc_info.value.errors)


def test_missing_target_field_name_rejected(tmp_path: Path) -> None:
    data = _valid_contract()
    del data["target_field"]
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("target_column" in e for e in exc_info.value.errors)


def test_empty_target_field_name_rejected(tmp_path: Path) -> None:
    data = _valid_contract()
    data["target_field"] = {"name": ""}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("target_column" in e for e in exc_info.value.errors)


def test_no_approved_fields_rejected(tmp_path: Path) -> None:
    """feature_columns must not resolve to an empty list (rejection-h)."""
    data = _valid_contract()
    for field in data["candidate_fields"]:
        field["review_status"] = "pending"
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("feature_columns" in e for e in exc_info.value.errors)


def test_invalid_field_type_rejected(tmp_path: Path) -> None:
    """rejection-a: field_type must be one of numeric, categorical, boolean."""
    data = _valid_contract()
    data["candidate_fields"][0]["field_type"] = "float"
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    errors = exc_info.value.errors
    assert any("age" in e and "field_type" in e for e in errors)
    assert any("float" in e for e in errors)


def test_invalid_transformation_rejected(tmp_path: Path) -> None:
    """rejection-b: allowed_transformations values must be in {log1p, sqrt, clip, passthrough}."""
    data = _valid_contract()
    data["policy"] = {"allowed_transformations": ["log1p", "pca"]}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("pca" in e for e in exc_info.value.errors)


def test_invalid_missing_value_strategy_rejected(tmp_path: Path) -> None:
    """rejection-c: missing_value_strategy must be in {mean, median, mode, constant, drop_row}."""
    data = _valid_contract()
    data["candidate_fields"][0]["missing_value_strategy"] = "interpolate"
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    errors = exc_info.value.errors
    assert any("age" in e and "missing_value_strategy" in e for e in errors)
    assert any("interpolate" in e for e in errors)


def test_invalid_categorical_encoding_policy_rejected(tmp_path: Path) -> None:
    """rejection-d: categorical_encoding_policy must be in {onehot, ordinal, target_encode, binary}."""
    data = _valid_contract()
    data["policy"] = {"categorical_encoding_policy": "label_encode"}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("label_encode" in e for e in exc_info.value.errors)


def test_invalid_numeric_handling_rejected(tmp_path: Path) -> None:
    """rejection-e: numeric_handling must be in {standardize, normalize, passthrough}."""
    data = _valid_contract()
    data["policy"] = {"numeric_handling": "robust_scale"}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("robust_scale" in e for e in exc_info.value.errors)


def test_invalid_primary_metric_rejected(tmp_path: Path) -> None:
    """rejection-f: primary_metric must be in {roc_auc, f1, accuracy, log_loss, pr_auc}."""
    data = _valid_contract()
    data["policy"] = {"primary_metric": "rmse"}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("rmse" in e for e in exc_info.value.errors)


def test_invalid_secondary_metric_rejected(tmp_path: Path) -> None:
    """rejection-f: secondary_metrics values must be valid metric identifiers."""
    data = _valid_contract()
    data["policy"] = {"secondary_metrics": ["f1", "mse"]}
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("mse" in e for e in exc_info.value.errors)


def test_split_policy_non_summing_ratios_rejected(tmp_path: Path) -> None:
    """gap-02: split_policy ratios that do not sum to 1.0 must be rejected."""
    data = _valid_contract()
    data["policy"] = {
        "split_policy": {"strategy": "stratified", "train_ratio": 0.8, "val_ratio": 0.1, "test_ratio": 0.2}
    }
    path = _write(tmp_path, data)

    with pytest.raises(PromotionRejected) as exc_info:
        promote(path, repo_root=REPO_ROOT)

    assert any("split_policy" in e for e in exc_info.value.errors)


def test_optional_field_defaults_applied_when_absent(tmp_path: Path) -> None:
    """decision-05: all optional execution contract fields receive documented defaults."""
    path = _write(tmp_path, _valid_contract())
    result = promote(path, repo_root=REPO_ROOT)

    assert result["random_seed"] is None
    assert result["secondary_metrics"] == []
    assert result["categorical_encoding_policy"] == "onehot"
    assert result["numeric_handling"] == "standardize"
    assert result["allowed_transformations"] == ["passthrough"]
    assert result["split_policy"] == {
        "strategy": "stratified",
        "train_ratio": 0.7,
        "val_ratio": 0.15,
        "test_ratio": 0.15,
    }
    assert result["primary_metric"] == "roc_auc"
    assert result["modeling_constraints"]["no_automl"] is True
    assert result["modeling_constraints"]["max_training_time_seconds"] is None
    assert result["modeling_constraints"]["allowed_model_families"] == [
        "logistic_regression", "gradient_boosting"
    ]


def test_declared_policy_values_override_defaults(tmp_path: Path) -> None:
    data = _valid_contract()
    data["policy"] = {
        "categorical_encoding_policy": "ordinal",
        "numeric_handling": "normalize",
        "allowed_transformations": ["log1p", "clip"],
        "primary_metric": "f1",
        "secondary_metrics": ["roc_auc"],
        "split_policy": {
            "strategy": "random",
            "train_ratio": 0.8,
            "val_ratio": 0.1,
            "test_ratio": 0.1,
        },
        "random_seed": 42,
    }
    path = _write(tmp_path, data)
    result = promote(path, repo_root=REPO_ROOT)

    assert result["categorical_encoding_policy"] == "ordinal"
    assert result["numeric_handling"] == "normalize"
    assert result["allowed_transformations"] == ["log1p", "clip"]
    assert result["primary_metric"] == "f1"
    assert result["secondary_metrics"] == ["roc_auc"]
    assert result["split_policy"]["strategy"] == "random"
    assert result["random_seed"] == 42


def test_missing_value_strategy_type_defaults_applied(tmp_path: Path) -> None:
    """decision-04-h: numeric defaults to median, categorical to mode, boolean to mode."""
    data = _valid_contract()
    data["candidate_fields"] = [
        {"name": "num_field", "review_status": "approved", "field_type": "numeric"},
        {"name": "cat_field", "review_status": "approved", "field_type": "categorical", "known_values": ["x"]},
        {"name": "bool_field", "review_status": "approved", "field_type": "boolean"},
    ]
    path = _write(tmp_path, data)
    result = promote(path, repo_root=REPO_ROOT)

    assert result["missing_value_policy"]["num_field"] == "median"
    assert result["missing_value_policy"]["cat_field"] == "mode"
    assert result["missing_value_policy"]["bool_field"] == "mode"


def test_explicit_missing_value_strategy_overrides_default(tmp_path: Path) -> None:
    data = _valid_contract()
    data["candidate_fields"][0]["missing_value_strategy"] = "mean"
    path = _write(tmp_path, data)
    result = promote(path, repo_root=REPO_ROOT)

    assert result["missing_value_policy"]["age"] == "mean"


def test_optional_field_included_in_optional_columns(tmp_path: Path) -> None:
    data = _valid_contract()
    data["candidate_fields"][0]["optional"] = True
    path = _write(tmp_path, data)
    result = promote(path, repo_root=REPO_ROOT)

    assert "age" in result["optional_columns"]
    assert "age" not in result["required_columns"]


def test_non_approved_fields_go_to_ignored_columns(tmp_path: Path) -> None:
    data = _valid_contract()
    path = _write(tmp_path, data)
    result = promote(path, repo_root=REPO_ROOT)

    assert "rejected_field" in result["ignored_columns"]
    assert "rejected_field" not in result["feature_columns"]


def test_input_contract_file_not_modified(tmp_path: Path) -> None:
    """constraint-01: the human-facing contract must not be modified as a side effect."""
    path = _write(tmp_path, _valid_contract())
    original_content = path.read_text(encoding="utf-8")
    promote(path, repo_root=REPO_ROOT)
    assert path.read_text(encoding="utf-8") == original_content


def test_input_contract_file_not_modified_on_rejection(tmp_path: Path) -> None:
    data = _valid_contract()
    data["promotion_boundary"]["promotion_authorized"] = False
    path = _write(tmp_path, data)
    original_content = path.read_text(encoding="utf-8")

    with pytest.raises(PromotionRejected):
        promote(path, repo_root=REPO_ROOT)

    assert path.read_text(encoding="utf-8") == original_content


def test_no_extra_fields_in_execution_contract(tmp_path: Path) -> None:
    """constraint-05: execution contract must not carry human-facing auxiliary fields."""
    import jsonschema

    schema = json.loads(
        (REPO_ROOT / "contracts" / "execution-contract.schema.json").read_text(encoding="utf-8")
    )
    path = _write(tmp_path, _valid_contract())
    result = promote(path, repo_root=REPO_ROOT)

    jsonschema.validate(result, schema)

    forbidden_keys = {"validation_hint", "review_status", "known_values", "review_note", "inferred_type"}
    for key in forbidden_keys:
        assert key not in result, f"auxiliary field '{key}' must not appear in execution contract"


# ---------------------------------------------------------------------------
# S0101: public_contract release manifest, validation, and promotion
# integrity -- generic manifest-driven promotion of the eighth required
# publisher artifact role, distinct from this file's other tests above
# (pipeline.promote_contract's human-facing-contract -> execution-contract
# promotion, an unrelated pipeline that happens to share the word
# "promotion").
# ---------------------------------------------------------------------------

from publisher import manifest as publisher_manifest  # noqa: E402
from publisher import promote as publisher_promote  # noqa: E402
from publisher import validate as publisher_validate  # noqa: E402

_S0101_DATASET_SLUG = "contract-promotion-dataset"
_S0101_RELEASE_ID = "release-20260714-001"
_S0101_REQUIRED_ROLES = (
    "contracts",
    "public_contract",
    "predictive_bundle",
    "model_artifact",
    "metrics",
    "model_card",
    "public_context",
    "visualizations",
    "manifest_input",
    "candidate_metadata",
)

_S0128_RUN_ID = "train-20260714T000000Z"

# Project Spec S0107: the model artifact is a private binary, never JSON.
_S0101_MODEL_ARTIFACT_BYTES = b"pytest-fixture-model-bytes-not-a-real-model"
_S0101_MODEL_ARTIFACT_SHA256 = hashlib.sha256(_S0101_MODEL_ARTIFACT_BYTES).hexdigest()
_S0101_MODEL_ARTIFACT_PATH = "models/model.pkl"


def _s0101_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _s0101_artifact_payload(role: str) -> dict:
    if role == "public_contract":
        return {
            "schema_version": "1.0.0",
            "features": [
                {
                    "name": "example_feature",
                    "label": "Example Feature",
                    "input_type": "number",
                    "optional": False,
                    "display_order": 1,
                }
            ],
        }
    if role == "visualizations":
        return {
            "schema_version": "analytical-visualizations.v1",
            "artifact_kind": "analytical_visualizations",
            "created_at": "2026-07-14T00:00:00Z",
            "training_run_identity": {
                "dataset_slug": _S0101_DATASET_SLUG,
                "run_id": _S0128_RUN_ID,
                "output_directory": f"pipeline/training-runs/{_S0101_DATASET_SLUG}/{_S0128_RUN_ID}/",
            },
            "charts": [
                {
                    "id": "target_distribution",
                    "title": "Target Distribution",
                    "type": "bar",
                    "x_label": "Churn",
                    "y_label": "Rows",
                    "data": [{"name": "No", "value": 3}, {"name": "Yes", "value": 1}],
                },
                {
                    "id": "feature_importance",
                    "title": "Feature Importance",
                    "type": "bar",
                    "x_label": "Feature",
                    "y_label": "Importance",
                    "data": [{"name": "example_feature", "value": 1.0}],
                },
            ],
            "target_distribution_method": {
                "population_kind": "prepared_dataset",
                "row_count": 4,
                "target_column": "example_target",
            },
            "feature_importance_method": {
                "model_family": "gradient_boosting",
                "source": "estimator.feature_importances_",
                "total_source_feature_count": 1,
                "omitted_source_feature_count": 0,
                "public_row_limit": 10,
            },
            "evidence_policy": {
                "raw_logs_prohibited": True,
                "raw_runtime_prohibited": True,
                "raw_api_payloads_prohibited": True,
                "secrets_prohibited": True,
                "raw_dataset_embedded": False,
                "model_bytes_embedded": False,
                "serialized_estimator_state_embedded": False,
                "raw_transformed_matrices_embedded": False,
                "notebook_state_embedded": False,
                "reduced_and_sanitized": True,
            },
        }
    payload = {
        "role": role,
        "dataset_identity": {"dataset_slug": _S0101_DATASET_SLUG},
        "release_identity": {"release_id": _S0101_RELEASE_ID},
        "availability_status": "real_dataflow_artifact",
        "placeholder_policy": {
            "fixtures_allowed": False,
            "placeholders_allowed": False,
            "missing_required_behavior": "reject",
        },
    }
    if role in {"metrics", "model_card", "predictive_bundle"}:
        payload["model_id"] = "contract-promotion-model-001"
    if role == "predictive_bundle":
        payload["runtime_contract_ref"] = "artifacts/contracts.json"
        payload["model_artifact"] = {
            "path": _S0101_MODEL_ARTIFACT_PATH,
            "sha256": _S0101_MODEL_ARTIFACT_SHA256,
        }
    if role == "public_context":
        payload["public_projection"] = {"safe_for_public": True}
    return payload


def _s0101_role_path(role: str) -> str:
    if role == "model_artifact":
        return _S0101_MODEL_ARTIFACT_PATH
    return f"artifacts/{role}.json"


def _s0101_prepare_tmp_repo(tmp_path: Path) -> tuple[Path, Path]:
    tmp_repo = tmp_path / "repo"
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
    ):
        src = REPO_ROOT / relative
        dst = tmp_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())

    candidate_dir = tmp_repo / "releases" / "candidates" / _S0101_DATASET_SLUG / _S0101_RELEASE_ID
    candidate_dir.mkdir(parents=True, exist_ok=True)
    artifact_roles = {}
    for role in _S0101_REQUIRED_ROLES:
        role_path = _s0101_role_path(role)
        artifact_roles[role] = {"role": role, "path": role_path, "required": True}
        if role == "model_artifact":
            (candidate_dir / role_path).parent.mkdir(parents=True, exist_ok=True)
            (candidate_dir / role_path).write_bytes(_S0101_MODEL_ARTIFACT_BYTES)
            continue
        _s0101_write_json(candidate_dir / role_path, _s0101_artifact_payload(role))

    candidate = {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {"dataset_slug": _S0101_DATASET_SLUG, "dataset_title": "Contract Promotion Dataset"},
        "release_identity": {
            "release_id": _S0101_RELEASE_ID,
            "release_version": "1.0.0",
            "created_at": "2026-07-14T00:00:00Z",
        },
        "source_run": {"run_id": "test-run", "producer": "pytest", "created_at": "2026-07-14T00:00:00Z"},
        "artifact_roles": artifact_roles,
        "candidate_metadata": {
            "assembled_by": "pytest",
            "assembled_at": "2026-07-14T00:00:00Z",
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": list(_S0101_REQUIRED_ROLES),
                "hash_policy": "publisher_calculates_hashes",
                "manifest_policy": "publisher_generates_manifest",
            },
        },
        "state_boundaries": {
            "pipeline_run_is_publishable": False,
            "candidate_is_published_release": False,
            "promotion_required": True,
            "registry_update_allowed_in_candidate": False,
            "public_upload_required": False,
            "web_administration_required": False,
            "database_publication_management_required": False,
            "runtime_consumes_temporary_pipeline_output": False,
        },
    }
    _s0101_write_json(candidate_dir / "release-candidate.json", candidate)
    return tmp_repo, candidate_dir


def test_promotion_copies_public_contract_and_no_undeclared_files(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    manifest_result = publisher_manifest.run(str(run_dir), repo_root=tmp_repo)
    promotion_result = publisher_promote.run(str(run_dir), repo_root=tmp_repo)

    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / _S0101_RELEASE_ID
    manifest_references = {a["role"]: a["reference"] for a in manifest_result["artifacts"]}
    assert manifest_references["public_contract"] != manifest_references["contracts"]

    declared_files = {release_dir / ref for ref in manifest_references.values()}
    declared_files.add(release_dir / "manifest.json")
    actual_files = {p for p in release_dir.rglob("*") if p.is_file()}
    assert actual_files == declared_files, "promotion must copy exactly the manifest-declared files"

    promoted_public_contract = release_dir / manifest_references["public_contract"]
    assert promoted_public_contract.is_file()
    promoted_data = json.loads(promoted_public_contract.read_text(encoding="utf-8"))
    assert promoted_data["schema_version"] == "1.0.0"
    assert promoted_data["features"]


def test_promoted_public_contract_hash_matches_manifest_and_verification_passes(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    publisher_manifest.run(str(run_dir), repo_root=tmp_repo)
    publisher_promote.run(str(run_dir), repo_root=tmp_repo)

    release_dir = tmp_repo / "releases" / _S0101_RELEASE_ID
    valid, errors = publisher_manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []


def test_manifest_generation_is_deterministic_for_public_contract(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    result_1 = publisher_validate.validate_candidate_file(candidate_dir, repo_root=tmp_repo)
    result_2 = publisher_validate.validate_candidate_file(candidate_dir, repo_root=tmp_repo)
    assert result_1["role_results"]["public_contract"]["status"] == "present"
    assert result_2["role_results"]["public_contract"]["status"] == "present"

    manifest_1, errors_1 = publisher_manifest.generate_manifest(candidate_dir)
    manifest_2, errors_2 = publisher_manifest.generate_manifest(candidate_dir)
    assert errors_1 == []
    assert errors_2 == []

    hashes_1 = {a["role"]: a["hash_value"] for a in manifest_1["artifacts"]}
    hashes_2 = {a["role"]: a["hash_value"] for a in manifest_2["artifacts"]}
    assert hashes_1["public_contract"] == hashes_2["public_contract"]


# ---------------------------------------------------------------------------
# S0107: release-bound model artifact packaging and manifest integrity --
# generic promotion of the ninth required publisher artifact role, through
# the same real validate -> manifest -> promote pipeline exercised above for
# public_contract (S0101).
# ---------------------------------------------------------------------------


def test_model_artifact_promotion_copies_model_and_hashes_match_end_to_end(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    validation_result = publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["required_artifact_role_results"]["model_artifact"]["status"] == "present"

    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    manifest_result = publisher_manifest.run(str(run_dir), repo_root=tmp_repo)
    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}
    assert manifest_roles["model_artifact"]["reference"] == _S0101_MODEL_ARTIFACT_PATH
    assert manifest_roles["model_artifact"]["hash_value"] == _S0101_MODEL_ARTIFACT_SHA256

    promotion_result = publisher_promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / _S0101_RELEASE_ID
    promoted_model_path = release_dir / manifest_roles["model_artifact"]["reference"]
    assert promoted_model_path.is_file()
    promoted_bytes = promoted_model_path.read_bytes()
    assert promoted_bytes == _S0101_MODEL_ARTIFACT_BYTES
    assert hashlib.sha256(promoted_bytes).hexdigest() == manifest_roles["model_artifact"]["hash_value"]

    bundle = json.loads(
        (release_dir / manifest_roles["predictive_bundle"]["reference"]).read_text(encoding="utf-8")
    )
    assert bundle["model_artifact"]["sha256"] == manifest_roles["model_artifact"]["hash_value"]
    assert bundle["model_artifact"]["path"] == manifest_roles["model_artifact"]["reference"]

    # Promotion copies exactly the manifest-declared files -- no undeclared
    # adjacent artifact (e.g. a stray copy under the candidate's own
    # models/ directory naming) leaks into the promoted release.
    declared_files = {release_dir / a["reference"] for a in manifest_result["artifacts"]}
    declared_files.add(release_dir / "manifest.json")
    actual_files = {p for p in release_dir.rglob("*") if p.is_file()}
    assert actual_files == declared_files

    valid, errors = publisher_manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []


# ---------------------------------------------------------------------------
# S0128: release-bound analytical visualizations artifact packaging and
# manifest integrity -- generic promotion of the tenth required publisher
# artifact role, through the same real validate -> manifest -> promote
# pipeline exercised above for public_contract (S0101) / model_artifact
# (S0107).
# ---------------------------------------------------------------------------


def test_visualizations_hash_in_manifest_and_required_hash_coverage(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    manifest_result = publisher_manifest.run(str(run_dir), repo_root=tmp_repo)

    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}
    assert "visualizations" in manifest_roles
    source_path = candidate_dir / "artifacts" / "visualizations.json"
    expected_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    assert manifest_roles["visualizations"]["hash_value"] == expected_hash
    assert manifest_roles["visualizations"]["hash_algorithm"] == "sha256"
    assert "visualizations" in manifest_result["required_hash_coverage"]["required_artifact_roles"]


def test_manifest_generation_is_deterministic_for_visualizations(tmp_path: Path) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    manifest_1, errors_1 = publisher_manifest.generate_manifest(candidate_dir)
    manifest_2, errors_2 = publisher_manifest.generate_manifest(candidate_dir)
    assert errors_1 == []
    assert errors_2 == []

    hashes_1 = {a["role"]: a["hash_value"] for a in manifest_1["artifacts"]}
    hashes_2 = {a["role"]: a["hash_value"] for a in manifest_2["artifacts"]}
    assert hashes_1["visualizations"] == hashes_2["visualizations"]


def test_manifest_hash_verification_detects_visualizations_mutation_after_generation(
    tmp_path: Path,
) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    publisher_manifest.run(str(run_dir), repo_root=tmp_repo)

    # Mutate the candidate's visualizations artifact after manifest
    # generation but before promotion.
    visualizations_path = candidate_dir / "artifacts" / "visualizations.json"
    mutated = json.loads(visualizations_path.read_text(encoding="utf-8"))
    mutated["charts"][0]["data"][0]["value"] = 999999
    _s0101_write_json(visualizations_path, mutated)

    valid, errors = publisher_manifest.verify(run_dir / "manifest.json", candidate_dir)
    assert valid is False
    assert any(error["code"] == "MANIFEST_HASH_MISMATCH" for error in errors)


def test_visualizations_promotion_copies_declared_file_and_no_undeclared_files(
    tmp_path: Path,
) -> None:
    tmp_repo, candidate_dir = _s0101_prepare_tmp_repo(tmp_path)

    publisher_validate.run(str(candidate_dir), repo_root=tmp_repo)
    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]
    manifest_result = publisher_manifest.run(str(run_dir), repo_root=tmp_repo)
    manifest_roles = {a["role"]: a for a in manifest_result["artifacts"]}

    promotion_result = publisher_promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    release_dir = tmp_repo / "releases" / _S0101_RELEASE_ID
    promoted_path = release_dir / manifest_roles["visualizations"]["reference"]
    assert manifest_roles["visualizations"]["reference"] == "artifacts/visualizations.json"
    assert promoted_path.is_file()
    promoted_data = json.loads(promoted_path.read_text(encoding="utf-8"))
    assert promoted_data["schema_version"] == "analytical-visualizations.v1"

    # Promotion copies exactly the manifest-declared files -- no undeclared
    # adjacent file leaks into the promoted release.
    declared_files = {release_dir / a["reference"] for a in manifest_result["artifacts"]}
    declared_files.add(release_dir / "manifest.json")
    actual_files = {p for p in release_dir.rglob("*") if p.is_file()}
    assert actual_files == declared_files

    valid, errors = publisher_manifest.verify(release_dir / "manifest.json", release_dir)
    assert valid is True
    assert errors == []
    assert errors == []

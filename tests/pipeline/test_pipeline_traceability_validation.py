import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pipeline.discovery_evidence import (
    build_dataset_modeling_intent,
    materialize_dataset_modeling_intent,
    materialize_discovery_evidence,
)
from pipeline.prepare_candidate import (
    materialize_prepared_data_metadata,
    materialize_review_only_preparation_recipe,
)


REPO_ROOT = Path(__file__).parent.parent.parent


@dataclass(frozen=True)
class ReducedValidationError:
    validator: str
    message: str
    path: tuple[str, ...]


def _load_schema(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _validation_errors(
    instance: dict,
    schema: dict,
    path: tuple[str, ...] = (),
) -> list[ReducedValidationError]:
    errors = []

    for field in schema.get("required", []):
        if field not in instance:
            errors.append(
                ReducedValidationError(
                    validator="required",
                    message=f"{field!r} is a required property",
                    path=path,
                )
            )

    for field, field_schema in schema.get("properties", {}).items():
        if field not in instance:
            continue
        value = instance[field]
        if "const" in field_schema and value != field_schema["const"]:
            errors.append(
                ReducedValidationError(
                    validator="const",
                    message=f"{field!r} does not match the required constant",
                    path=path + (field,),
                )
            )
        if isinstance(value, dict) and field_schema.get("type") == "object":
            errors.extend(_validation_errors(value, field_schema, path + (field,)))

    return sorted(errors, key=lambda error: error.path)


def _has_required_error(
    errors: list[ReducedValidationError],
    *,
    field: str,
    path: tuple[str, ...],
) -> bool:
    return any(
        error.validator == "required"
        and field in error.message
        and tuple(error.path) == path
        for error in errors
    )


def _run_evidence(**overrides) -> dict:
    evidence = {
        "schema_version": "run-evidence.v1",
        "run_identity": {
            "run_id": "run-20260620-001",
            "run_type": "candidate_assembly",
            "producer": "pipeline-build",
        },
        "run_inputs": {
            "input_ref": "inputs/example-dataset/source-contract-input.json",
            "input_hash": "a" * 64,
        },
        "run_outputs": {
            "output_ref": "releases/candidates/example-dataset/release-20260620-001",
            "output_hash": "b" * 64,
        },
        "run_timestamps": {
            "started_at": "2026-06-20T10:00:00Z",
            "completed_at": "2026-06-20T10:05:00Z",
        },
        "run_status": "accepted",
        "run_boundary_confirmations": {
            "is_release_candidate": False,
            "is_published_release": False,
            "is_active_release": False,
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
    evidence.update(overrides)
    return evidence


def _candidate_traceability(**overrides) -> dict:
    evidence = {
        "schema_version": "candidate-traceability.v1",
        "source_run_ref": {
            "run_id": "run-20260620-001",
            "run_evidence_ref": "evidence/M14/run-20260620-001.json",
            "producer": "pipeline-build",
            "run_type": "candidate_assembly",
        },
        "candidate_identity": {
            "dataset_slug": "example-dataset",
            "release_id": "release-20260620-001",
        },
        "candidate_artifacts": [
            {
                "artifact_role": "manifest_input",
                "artifact_name": "manifest-input.json",
                "artifact_hash": "c" * 64,
            }
        ],
        "validation_status": "publisher_validated",
        "traceability_boundary_confirmations": {
            "is_promotion_authorized": False,
            "is_active_release": False,
            "is_published_release": False,
            "raw_run_evidence_embedded": False,
        },
    }
    evidence.update(overrides)
    return evidence


def _validate_candidate_source_run(
    candidate: dict,
    run_evidence_by_ref: dict[str, dict],
) -> dict:
    source_ref = candidate["source_run_ref"]
    run_ref = source_ref["run_evidence_ref"]
    run_evidence = run_evidence_by_ref.get(run_ref)
    if run_evidence is None:
        return {"valid": False, "reason_code": "source_run_missing"}

    run_identity = run_evidence["run_identity"]
    if run_identity["run_id"] != source_ref["run_id"]:
        return {"valid": False, "reason_code": "source_run_id_mismatch"}
    if run_identity["producer"] != source_ref["producer"]:
        return {"valid": False, "reason_code": "source_run_producer_mismatch"}
    if run_evidence["run_status"] != "accepted":
        return {"valid": False, "reason_code": "source_run_not_accepted"}

    return {"valid": True, "reason_code": None}


def test_run_evidence_requires_run_id():
    schema = _load_schema("pipeline/run-evidence.schema.json")
    evidence = _run_evidence()
    del evidence["run_identity"]["run_id"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(errors, field="run_id", path=("run_identity",))


def test_candidate_traceability_requires_source_run_reference():
    schema = _load_schema("pipeline/candidate-traceability.schema.json")
    evidence = _candidate_traceability()
    del evidence["source_run_ref"]["run_evidence_ref"]

    errors = _validation_errors(evidence, schema)

    assert _has_required_error(
        errors,
        field="run_evidence_ref",
        path=("source_run_ref",),
    )


def test_candidate_without_resolvable_source_run_fails_reduced_check():
    candidate = _candidate_traceability()

    result = _validate_candidate_source_run(candidate, run_evidence_by_ref={})

    assert result == {"valid": False, "reason_code": "source_run_missing"}


def test_candidate_source_run_identity_mismatch_fails_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]
    run_evidence = _run_evidence()
    run_evidence["run_identity"]["run_id"] = "run-20260620-999"

    result = _validate_candidate_source_run(candidate, {run_ref: run_evidence})

    assert result == {"valid": False, "reason_code": "source_run_id_mismatch"}


def test_candidate_source_run_rejected_status_fails_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]
    run_evidence = _run_evidence(run_status="rejected")

    result = _validate_candidate_source_run(candidate, {run_ref: run_evidence})

    assert result == {"valid": False, "reason_code": "source_run_not_accepted"}


def test_candidate_source_run_match_passes_reduced_check():
    candidate = _candidate_traceability()
    run_ref = candidate["source_run_ref"]["run_evidence_ref"]

    result = _validate_candidate_source_run(candidate, {run_ref: _run_evidence()})

    assert result == {"valid": True, "reason_code": None}


def _copy_schema_to_tmp_repo(tmp_repo: Path, schema_name: str) -> None:
    pipeline_dir = tmp_repo / "pipeline"
    pipeline_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(
        REPO_ROOT / "pipeline" / schema_name,
        pipeline_dir / schema_name,
    )


def test_materialize_discovery_evidence_uses_repo_relative_source_and_counts_blanks(tmp_path):
    tmp_repo = tmp_path / "repo"
    (tmp_repo / "pipeline").mkdir(parents=True)
    (tmp_repo / "README.md").write_text("tmp repo\n", encoding="utf-8")
    (tmp_repo / "pipeline" / "discovery_evidence.py").write_text("", encoding="utf-8")
    _copy_schema_to_tmp_repo(tmp_repo, "dataset-discovery-evidence.schema.json")
    dataset_path = tmp_repo / "data" / "raw" / "telco-customer-churn.csv"
    dataset_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        "customerID,TotalCharges,Churn\n"
        "a, ,No\n"
        "b,10.5,Yes\n",
        encoding="utf-8",
    )

    evidence = materialize_discovery_evidence(
        dataset_relative_path="data/raw/telco-customer-churn.csv",
        output_relative_path="pipeline/evidence/telco-customer-churn/discovery-evidence.json",
        repo_root=tmp_repo,
        dataset_slug="telco-customer-churn",
        generated_at="2026-07-09T00:00:00+00:00",
    )

    written = json.loads(
        (
            tmp_repo
            / "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
        ).read_text(encoding="utf-8")
    )
    total_charges = next(
        field for field in evidence["field_observations"]
        if field["name"] == "TotalCharges"
    )

    assert written == evidence
    assert evidence["dataset_metadata"]["name"] == "telco-customer-churn"
    assert evidence["dataset_metadata"]["source_path"] == "data/raw/telco-customer-churn.csv"
    assert total_charges["null_count"] == 1
    assert total_charges["inferred_type"] == "float"
    assert any(
        candidate["name"] == "Churn" and candidate["is_authoritative"] is False
        for candidate in evidence["candidate_target_columns"]
    )
    assert not Path(evidence["dataset_metadata"]["source_path"]).is_absolute()


def test_materialize_review_only_preparation_recipe_records_pending_totalcharges_rule(tmp_path):
    tmp_repo = tmp_path / "repo"
    _copy_schema_to_tmp_repo(tmp_repo, "candidate-preparation-recipe.schema.json")
    dataset_path = tmp_repo / "data" / "raw" / "telco-customer-churn.csv"
    evidence_path = tmp_repo / "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
    dataset_path.parent.mkdir(parents=True)
    evidence_path.parent.mkdir(parents=True)
    dataset_path.write_text(
        "customerID,TotalCharges,Churn\n"
        "a, ,No\n"
        "b,10.5,Yes\n",
        encoding="utf-8",
    )
    evidence_path.write_text(
        json.dumps({"schema_version": "dataset-discovery-evidence.v1"}),
        encoding="utf-8",
    )

    recipe = materialize_review_only_preparation_recipe(
        discovery_evidence_relative_path=(
            "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
        ),
        dataset_relative_path="data/raw/telco-customer-churn.csv",
        output_relative_path="pipeline/evidence/telco-customer-churn/preparation-recipe.json",
        transformations=[
            {
                "transformation_type": "missing_value_handling",
                "description": (
                    "Review TotalCharges blank values; no transformation is applied."
                ),
                "source_columns": ["TotalCharges"],
                "target_columns": ["TotalCharges"],
                "reason": "Observed blank TotalCharges values during authoring.",
                "review_status": "inferred_pending_review",
            }
        ],
        preparation_rules_source="notebook:telco-preparation-review-transformations",
        repo_root=tmp_repo,
        generated_at="2026-07-09T00:00:00+00:00",
    )

    written = json.loads(
        (
            tmp_repo
            / "pipeline/evidence/telco-customer-churn/preparation-recipe.json"
        ).read_text(encoding="utf-8")
    )
    transformation = recipe["transformations"][0]

    assert written == recipe
    assert transformation["source_columns"] == ["TotalCharges"]
    assert transformation["review_status"] == "inferred_pending_review"
    assert recipe["candidate_output"]["produced"] is False
    assert recipe["candidate_output"]["row_count_after"] is None
    assert "pending human review" in recipe["candidate_output"]["reason_not_produced"]
    assert not any(recipe["preparation_boundary_confirmations"].values())


def _write_evidence_and_recipe(
    tmp_repo: Path,
    *,
    recipe_overrides: dict | None = None,
) -> None:
    evidence_path = tmp_repo / "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
    recipe_path = tmp_repo / "pipeline/evidence/telco-customer-churn/preparation-recipe.json"
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(
        json.dumps(
            {
                "schema_version": "dataset-discovery-evidence.v1",
                "dataset_metadata": {
                    "name": "telco-customer-churn",
                    "row_count": 7043,
                    "column_count": 21,
                    "source_path": "data/raw/telco-customer-churn.csv",
                },
            }
        ),
        encoding="utf-8",
    )
    recipe = {
        "schema_version": "candidate-preparation-recipe.v1",
        "transformations": [
            {
                "transformation_type": "missing_value_handling",
                "description": "Review TotalCharges blank values; no transformation is applied.",
                "source_columns": ["TotalCharges"],
                "target_columns": ["TotalCharges"],
                "reason": "Observed blank TotalCharges values during authoring.",
                "review_status": "inferred_pending_review",
            }
        ],
        "candidate_output": {
            "produced": False,
            "reason_not_produced": (
                "No transformation rules with review_status 'explicit' or "
                "'inferred_approved' were applied. 1 rule(s) are pending human review."
            ),
            "row_count_after": None,
            "column_count_after": None,
        },
    }
    if recipe_overrides:
        recipe.update(recipe_overrides)
    recipe_path.write_text(json.dumps(recipe), encoding="utf-8")


def test_materialize_prepared_data_metadata_pending_review_blocks_training_readiness(tmp_path):
    tmp_repo = tmp_path / "repo"
    _write_evidence_and_recipe(tmp_repo)

    metadata = materialize_prepared_data_metadata(
        dataset_slug="telco-customer-churn",
        raw_dataset_relative_path="data/raw/telco-customer-churn.csv",
        discovery_evidence_relative_path=(
            "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
        ),
        preparation_recipe_relative_path=(
            "pipeline/evidence/telco-customer-churn/preparation-recipe.json"
        ),
        output_relative_path="pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        repo_root=tmp_repo,
        prepared_candidate_relative_path="pipeline/prepared/telco-customer-churn/prepared-data.csv",
        generated_at="2026-07-09T00:00:00+00:00",
    )

    written = json.loads(
        (
            tmp_repo / "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json"
        ).read_text(encoding="utf-8")
    )

    assert written == metadata
    assert metadata["schema_version"] == "prepared-data-metadata.v1"
    assert metadata["dataset_identity"]["dataset_slug"] == "telco-customer-churn"
    assert metadata["prepared_candidate"]["produced"] is False
    assert metadata["prepared_candidate"]["reference"] is None
    assert metadata["ordered_prepared_columns"] is None
    assert metadata["applied_transformations_summary"] == []
    assert len(metadata["unresolved_review_items"]) == 1
    assert metadata["unresolved_review_items"][0]["source_columns"] == ["TotalCharges"]
    assert metadata["training_readiness"]["is_training_ready"] is False
    assert metadata["training_readiness"]["is_final_training_input"] is False
    assert "pending human review" in metadata["training_readiness"]["reason"]
    assert not any(metadata["materialization_boundary_confirmations"].values())
    assert not Path(metadata["dataset_identity"]["raw_dataset_ref"]["path"]).is_absolute()


def test_materialize_prepared_data_metadata_with_produced_candidate_is_training_ready(tmp_path):
    tmp_repo = tmp_path / "repo"
    _write_evidence_and_recipe(
        tmp_repo,
        recipe_overrides={
            "transformations": [
                {
                    "transformation_type": "missing_value_handling",
                    "description": "Drop rows with blank TotalCharges.",
                    "source_columns": ["TotalCharges"],
                    "target_columns": ["TotalCharges"],
                    "reason": "Explicitly approved after human review.",
                    "review_status": "explicit",
                }
            ],
            "candidate_output": {
                "produced": True,
                "reason_not_produced": None,
                "row_count_after": 2,
                "column_count_after": 3,
            },
        },
    )
    candidate_path = tmp_repo / "pipeline/prepared/telco-customer-churn/prepared-data.csv"
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(
        "customerID,TotalCharges,Churn\nb,10.5,Yes\nc,20.0,No\n",
        encoding="utf-8",
    )

    metadata = materialize_prepared_data_metadata(
        dataset_slug="telco-customer-churn",
        raw_dataset_relative_path="data/raw/telco-customer-churn.csv",
        discovery_evidence_relative_path=(
            "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
        ),
        preparation_recipe_relative_path=(
            "pipeline/evidence/telco-customer-churn/preparation-recipe.json"
        ),
        output_relative_path="pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        repo_root=tmp_repo,
        prepared_candidate_relative_path="pipeline/prepared/telco-customer-churn/prepared-data.csv",
        generated_at="2026-07-09T00:00:00+00:00",
    )

    assert metadata["prepared_candidate"]["produced"] is True
    assert metadata["prepared_candidate"]["reference"]["path"] == (
        "pipeline/prepared/telco-customer-churn/prepared-data.csv"
    )
    assert metadata["prepared_candidate"]["reference"]["row_count"] == 2
    assert metadata["ordered_prepared_columns"] == ["customerID", "TotalCharges", "Churn"]
    assert metadata["applied_transformations_summary"][0]["review_status"] == "explicit"
    assert metadata["unresolved_review_items"] == []
    assert metadata["training_readiness"]["is_training_ready"] is True
    assert metadata["training_readiness"]["is_final_training_input"] is False
    assert metadata["training_readiness"]["reason"] is None


def _telco_shaped_modeling_intent(**overrides) -> dict:
    kwargs = dict(
        dataset_slug="telco-customer-churn",
        dataset_source_ref="data/raw/telco-customer-churn.csv",
        authoring_notebook_ref="notebooks/datasets/telco-customer-churn/01_dataset_authoring.ipynb",
        columns=["customerID", "SeniorCitizen", "TotalCharges", "tenure", "Churn"],
        target_column="Churn",
        task_type="binary_classification",
        observed_labels=["No", "Yes"],
        positive_label_candidate="Yes",
        observed_target_distribution={"No": 5174, "Yes": 1869},
        identifier_columns=["customerID"],
        feature_review_notes={
            "TotalCharges": "Requires explicit blank-value handling before execution-contract projection.",
            "SeniorCitizen": "Raw representation is numeric (0/1) but the semantic domain is binary.",
        },
        feature_type_intent_overrides={"SeniorCitizen": "requires_review"},
        blank_value_policy_candidates={"TotalCharges": "unresolved_pending_review"},
        open_questions=["Final TotalCharges blank-value handling policy is not yet decided."],
        generated_at="2026-07-09T00:00:00+00:00",
    )
    kwargs.update(overrides)
    return build_dataset_modeling_intent(**kwargs)


def test_materialize_dataset_modeling_intent_writes_expected_repository_relative_path(tmp_path):
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
    )

    written = json.loads(
        (
            tmp_repo / "pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json"
        ).read_text(encoding="utf-8")
    )
    assert written == materialized
    assert materialized["artifact_type"] == "dataset_modeling_intent"
    assert materialized["contract_version"] == "dataset_modeling_intent.v1"


def test_materialize_dataset_modeling_intent_omits_absent_upstream_references(tmp_path):
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
        discovery_evidence_relative_path="pipeline/evidence/telco-customer-churn/discovery-evidence.json",
        preparation_recipe_relative_path="pipeline/evidence/telco-customer-churn/preparation-recipe.json",
        prepared_data_metadata_relative_path="pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        public_context_relative_path="contracts/telco-customer-churn/dataset-context.json",
    )

    assert materialized["authoring_source"]["reduced_discovery_evidence_ref"] is None
    assert materialized["authoring_source"]["preparation_recipe_ref"] is None
    assert materialized["authoring_source"]["prepared_data_metadata_ref"] is None
    assert materialized["authoring_source"]["public_context_ref"] is None
    assert materialized["unresolved_review_items"] == []
    assert materialized["blank_value_policy_candidates"]["TotalCharges"] == (
        "unresolved_pending_review"
    )


def test_materialize_dataset_modeling_intent_references_present_upstream_artifacts(tmp_path):
    tmp_repo = tmp_path / "repo"
    _write_evidence_and_recipe(tmp_repo)
    (tmp_repo / "pipeline/prepared/telco-customer-churn").mkdir(parents=True)
    (tmp_repo / "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json").write_text(
        "{}", encoding="utf-8"
    )
    (tmp_repo / "contracts/telco-customer-churn").mkdir(parents=True)
    (tmp_repo / "contracts/telco-customer-churn/dataset-context.json").write_text(
        "{}", encoding="utf-8"
    )

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
        discovery_evidence_relative_path="pipeline/evidence/telco-customer-churn/discovery-evidence.json",
        preparation_recipe_relative_path="pipeline/evidence/telco-customer-churn/preparation-recipe.json",
        prepared_data_metadata_relative_path="pipeline/prepared/telco-customer-churn/prepared-data-metadata.json",
        public_context_relative_path="contracts/telco-customer-churn/dataset-context.json",
    )

    assert materialized["authoring_source"]["reduced_discovery_evidence_ref"] == (
        "pipeline/evidence/telco-customer-churn/discovery-evidence.json"
    )
    assert materialized["authoring_source"]["preparation_recipe_ref"] == (
        "pipeline/evidence/telco-customer-churn/preparation-recipe.json"
    )
    assert materialized["authoring_source"]["prepared_data_metadata_ref"] == (
        "pipeline/prepared/telco-customer-churn/prepared-data-metadata.json"
    )
    assert materialized["authoring_source"]["public_context_ref"] == (
        "contracts/telco-customer-churn/dataset-context.json"
    )


def test_materialize_dataset_modeling_intent_keeps_totalcharges_unresolved_when_recipe_pending(
    tmp_path,
):
    tmp_repo = tmp_path / "repo"
    _write_evidence_and_recipe(tmp_repo)

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
        preparation_recipe_relative_path="pipeline/evidence/telco-customer-churn/preparation-recipe.json",
    )

    assert materialized["blank_value_policy_candidates"]["TotalCharges"] == (
        "unresolved_pending_review"
    )
    assert len(materialized["unresolved_review_items"]) == 1
    assert materialized["unresolved_review_items"][0]["source_columns"] == ["TotalCharges"]
    assert materialized["unresolved_review_items"][0]["review_status"] == (
        "inferred_pending_review"
    )


def test_materialize_dataset_modeling_intent_reflects_recipe_approved_review_status(tmp_path):
    tmp_repo = tmp_path / "repo"
    _write_evidence_and_recipe(
        tmp_repo,
        recipe_overrides={
            "transformations": [
                {
                    "transformation_type": "missing_value_handling",
                    "description": "Drop rows with blank TotalCharges.",
                    "source_columns": ["TotalCharges"],
                    "target_columns": ["TotalCharges"],
                    "reason": "Explicitly approved after human review.",
                    "review_status": "explicit",
                }
            ],
        },
    )

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
        preparation_recipe_relative_path="pipeline/evidence/telco-customer-churn/preparation-recipe.json",
    )

    assert materialized["blank_value_policy_candidates"]["TotalCharges"] == "explicit"
    assert materialized["unresolved_review_items"] == []


def test_materialize_dataset_modeling_intent_excludes_identifier_from_features_and_sets_evidence_policy(
    tmp_path,
):
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir()

    materialized = materialize_dataset_modeling_intent(
        _telco_shaped_modeling_intent(),
        output_relative_path="pipeline/evidence/telco-customer-churn/dataset-modeling-intent.json",
        repo_root=tmp_repo,
    )

    assert "customerID" not in materialized["initial_feature_candidates"]
    assert materialized["target_intent"]["target_column"] == "Churn"
    assert materialized["target_intent"]["positive_label_candidate"] == "Yes"
    assert materialized["evidence_policy"] == {
        "raw_logs_prohibited": True,
        "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True,
        "secrets_prohibited": True,
        "private_source_paths_prohibited": True,
        "reduced_and_sanitized": True,
    }
    assert not any(materialized["modeling_intent_boundary_confirmations"].values())

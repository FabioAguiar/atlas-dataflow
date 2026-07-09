import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pipeline.discovery_evidence import materialize_discovery_evidence
from pipeline.prepare_candidate import materialize_review_only_preparation_recipe


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

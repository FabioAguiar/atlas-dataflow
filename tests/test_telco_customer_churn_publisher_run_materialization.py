"""Focused Publisher Run materialization regression coverage for the
Telco Customer Churn Atlas-native migration (Project Spec S0260).

Uses only temporary filesystem fixtures and current generic Atlas-native
binary v5 primitives -- never the real notebook, the real raw Telco dataset,
network access, or the external `dataset-study-telco-customer-churn` study.
Builds a coherent Telco-shaped native binary v5 candidate lineage
(`training-parameter-record.v5` + `training-metrics.v5` +
`analytical-visualizations.v5` + `inference_bundle.v1` + binary
runtime/public contracts) and proves it can reach
`assemble_candidate.assemble_release_candidate` acceptance,
`publisher.validate.materialize_validation_run` materialization with an
accepted, manifest-generated Publisher Run, and a completed, promotion-
eligible `validated_run.materialize_validated_run_terminal_result` outcome
declaring `model_source_mode=atlas_internal_training`. Also proves a
fail-closed cross-artifact mismatch (positive-class) is rejected by
`publisher.validate`, and that no real repository run/candidate/publisher
directory is ever created.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

DATASET_SLUG = "telco-customer-churn"

# Telco already has real, historical candidate directories under the real
# repository tree -- captured here, at module import time (before any
# fixture in this file runs), so the "no real directory created" assertion
# below can detect a *new* entry rather than assuming the tree starts empty.
_REAL_TELCO_CANDIDATE_ROOT = REPO_ROOT / "releases" / "candidates" / DATASET_SLUG
_REAL_TELCO_CANDIDATE_DIRS_BEFORE = (
    {p.name for p in _REAL_TELCO_CANDIDATE_ROOT.iterdir() if p.is_dir()}
    if _REAL_TELCO_CANDIDATE_ROOT.is_dir()
    else set()
)

from pipeline import assemble_candidate, generate_inference_bundle, release_identity, training, validated_run  # noqa: E402
from publisher import validate as publisher_validate  # noqa: E402

FEATURE_COLUMNS = [
    "gender",
    "SeniorCitizen",
    "Partner",
    "Dependents",
    "tenure",
    "PhoneService",
    "MultipleLines",
    "InternetService",
    "OnlineSecurity",
    "OnlineBackup",
    "DeviceProtection",
    "TechSupport",
    "StreamingTV",
    "StreamingMovies",
    "Contract",
    "PaperlessBilling",
    "PaymentMethod",
    "MonthlyCharges",
    "TotalCharges",
]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _hgb_hyperparameters(**overrides) -> dict:
    base = {
        "class_weight": None,
        "l2_regularization": 1.0,
        "learning_rate": 0.03,
        "max_iter": 200,
        "max_leaf_nodes": 7,
        "min_samples_leaf": 40,
        "max_depth": 3,
    }
    base.update(overrides)
    return base


def _fixed_binary_contract() -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": DATASET_SLUG,
        "target_column": "Churn",
        "feature_columns": list(FEATURE_COLUMNS),
        "ignored_columns": ["customerID"],
        "required_columns": list(FEATURE_COLUMNS),
        "optional_columns": [],
        "feature_definitions": {
            "gender": {"type": "categorical"},
            "SeniorCitizen": {"type": "boolean"},
            "Partner": {"type": "boolean"},
            "Dependents": {"type": "boolean"},
            "tenure": {"type": "numeric"},
            "PhoneService": {"type": "boolean"},
            "MultipleLines": {"type": "categorical"},
            "InternetService": {"type": "categorical"},
            "OnlineSecurity": {"type": "categorical"},
            "OnlineBackup": {"type": "categorical"},
            "DeviceProtection": {"type": "categorical"},
            "TechSupport": {"type": "categorical"},
            "StreamingTV": {"type": "categorical"},
            "StreamingMovies": {"type": "categorical"},
            "Contract": {"type": "categorical"},
            "PaperlessBilling": {"type": "boolean"},
            "PaymentMethod": {"type": "categorical"},
            "MonthlyCharges": {"type": "numeric"},
            "TotalCharges": {"type": "numeric"},
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "stratified", "train_ratio": 0.7, "val_ratio": 0.15, "test_ratio": 0.15},
        "random_seed": 0,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "pr_auc"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": _hgb_hyperparameters(),
            },
        },
        "result_semantics": {
            "schema_version": "binary-result-semantics.v1",
            "problem_type": "binary_classification",
            "positive_class": {"class_id": "Yes", "event_label": "Churn"},
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
        },
    }


def _synthetic_telco_shaped_dataset(row_count: int = 300, seed: int = 0) -> dict:
    import random

    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        tenure = rng.randint(0, 72)
        monthly_charges = round(rng.uniform(18.0, 120.0), 2)
        total_charges = round(monthly_charges * max(tenure, 1) + rng.uniform(-20, 20), 2)
        score = (
            (72 - tenure) * 0.02
            + (monthly_charges - 60.0) * 0.01
            + rng.uniform(-1.5, 1.5)
        )
        label = "Yes" if score > 1.0 else "No"
        row = {
            "dataset_id": DATASET_SLUG,
            "gender": rng.choice(["Male", "Female"]),
            "SeniorCitizen": rng.choice([0, 1]),
            "Partner": rng.choice(["Yes", "No"]),
            "Dependents": rng.choice(["Yes", "No"]),
            "tenure": tenure,
            "PhoneService": rng.choice(["Yes", "No"]),
            "MultipleLines": rng.choice(["Yes", "No", "No phone service"]),
            "InternetService": rng.choice(["DSL", "Fiber optic", "No"]),
            "OnlineSecurity": rng.choice(["Yes", "No", "No internet service"]),
            "OnlineBackup": rng.choice(["Yes", "No", "No internet service"]),
            "DeviceProtection": rng.choice(["Yes", "No", "No internet service"]),
            "TechSupport": rng.choice(["Yes", "No", "No internet service"]),
            "StreamingTV": rng.choice(["Yes", "No", "No internet service"]),
            "StreamingMovies": rng.choice(["Yes", "No", "No internet service"]),
            "Contract": rng.choice(["Month-to-month", "One year", "Two year"]),
            "PaperlessBilling": rng.choice(["Yes", "No"]),
            "PaymentMethod": rng.choice(["Electronic check", "Mailed check", "Bank transfer", "Credit card"]),
            "MonthlyCharges": monthly_charges,
            "TotalCharges": total_charges,
            "Churn": label,
        }
        rows.append(row)
    return {"dataset_id": DATASET_SLUG, "rows": rows}


@pytest.fixture(scope="module")
def _tmp_repo_root(tmp_path_factory):
    tmp_repo = tmp_path_factory.mktemp("telco_binary_v5_native_repo")
    original_repo_root = training._repo_root
    training._repo_root = lambda: tmp_repo
    yield tmp_repo
    training._repo_root = original_repo_root


@pytest.fixture(scope="module")
def telco_v5_native_run(_tmp_repo_root):
    tmp_repo = _tmp_repo_root
    contract = _fixed_binary_contract()
    contract_path = tmp_repo / "contracts" / DATASET_SLUG / "execution-contract.json"
    _write_json(contract_path, contract)

    prepared_dataset_path = tmp_repo / "pipeline" / "prepared" / DATASET_SLUG / "prepared-data.json"
    _write_json(prepared_dataset_path, _synthetic_telco_shaped_dataset())

    result = training.train_from_paths(contract_path, prepared_dataset_path, dataset_slug=DATASET_SLUG)
    return {
        "tmp_repo": tmp_repo,
        "contract_path": contract_path,
        "prepared_dataset_path": prepared_dataset_path,
        "result": result,
    }


class TestTelcoNativeBinaryV5TrainingRun:
    def test_status_and_model_family(self, telco_v5_native_run):
        result = telco_v5_native_run["result"]
        assert result.status == "trained"
        assert result.model_family == "hist_gradient_boosting"

    def test_training_parameter_record_is_real_v5_with_frozen_hyperparameters(self, telco_v5_native_run):
        tmp_repo = telco_v5_native_run["tmp_repo"]
        result = telco_v5_native_run["result"]
        record = json.loads((tmp_repo / result.training_parameter_record_path).read_text())
        assert record["schema_version"] == "training-parameter-record.v5"
        assert record["classification_evidence"]["positive_class_id"] == "Yes"
        assert record["training_parameters"]["hyperparameters"] == _hgb_hyperparameters()
        assert record["training_parameters"]["random_seed"] == 0


@pytest.fixture(scope="module")
def telco_v5_native_bundle(telco_v5_native_run):
    tmp_repo = telco_v5_native_run["tmp_repo"]
    result = telco_v5_native_run["result"]

    runtime_contract_path = tmp_repo / "contracts" / DATASET_SLUG / "runtime-contract.json"
    _write_json(runtime_contract_path, {
        "schema_version": "1.0.0",
        "features": [{"name": name, "type": "numeric", "required": True} for name in FEATURE_COLUMNS],
    })
    public_contract_path = tmp_repo / "contracts" / DATASET_SLUG / "public-contract.json"
    _write_json(public_contract_path, {
        "schema_version": "1.0.0",
        "features": [
            {"name": name, "label": name, "input_type": "number", "optional": False, "display_order": index + 1}
            for index, name in enumerate(FEATURE_COLUMNS)
        ],
    })
    dataset_context_path = tmp_repo / "contracts" / DATASET_SLUG / "dataset-context.json"
    _write_json(dataset_context_path, {
        "schema_version": "1.0.0",
        "dataset_slug": DATASET_SLUG,
        "title": "Telco Customer Churn",
        "predict_views": [],
    })
    prepared_data_metadata_path = tmp_repo / "pipeline" / "prepared" / DATASET_SLUG / "prepared-data-metadata.json"
    _write_json(prepared_data_metadata_path, {
        "schema_version": "prepared-data-metadata.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "prepared_candidate": {
            "produced": True,
            "reference": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.json",
        },
        "training_readiness": {"is_training_ready": True},
        "unresolved_review_items": [],
    })

    training_run_materialization_result = {
        "artifact_type": "training_run_materialization_result",
        "contract_version": "training_run_materialization_result.v1",
        "status": "trained",
        "training_result": result.to_summary(),
    }

    # Project Spec S0263: reserve release-YYYYMMDD-001 for this run's own
    # date first, so the generic pipeline.release_identity allocator is
    # forced to select -002 -- proving collision-safe reexecution rather
    # than ever reusing the internal branch's fixed -001 provisional
    # fallback as the candidate authority.
    run_id = Path(result.output_directory.rstrip("/")).name
    date_part = run_id[len("train-"):len("train-") + 8]
    (tmp_repo / "releases" / f"release-{date_part}-001").mkdir(parents=True, exist_ok=True)
    allocated_release_id = release_identity.allocate_release_id(run_id, tmp_repo)
    assert allocated_release_id == f"release-{date_part}-002"

    bundle_output_path = tmp_repo / "pipeline" / "inference-bundles" / DATASET_SLUG / "inference-bundle.json"
    bundle_result = generate_inference_bundle.materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        execution_contract_path=telco_v5_native_run["contract_path"],
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_data_metadata_path=prepared_data_metadata_path,
        output_path=bundle_output_path,
        prediction_type="number",
        repo_root=tmp_repo,
        dataset_slug=DATASET_SLUG,
        class_labels=["No", "Yes"],
        probability_output=True,
        execution_contract_ref=f"contracts/{DATASET_SLUG}/execution-contract.json",
        runtime_contract_ref=f"contracts/{DATASET_SLUG}/runtime-contract.json",
        public_contract_ref=f"contracts/{DATASET_SLUG}/public-contract.json",
        dataset_context_ref=f"contracts/{DATASET_SLUG}/dataset-context.json",
        inference_bundle_schema_path=str(REPO_ROOT / "contracts" / "inference-bundle.schema.json"),
        model_package_reference="models/model.pkl",
        release_id=allocated_release_id,
    )

    assert bundle_result["status"] == "generated", bundle_result

    bundle = json.loads(bundle_output_path.read_text())
    assert bundle["release_context"]["release_id"] == allocated_release_id

    return {
        **telco_v5_native_run,
        "bundle_result": bundle_result,
        "bundle_output_path": bundle_output_path,
        "release_id": allocated_release_id,
        "runtime_contract_path": runtime_contract_path,
        "public_contract_path": public_contract_path,
        "dataset_context_path": dataset_context_path,
        "prepared_data_metadata_path": prepared_data_metadata_path,
    }


def test_inference_bundle_is_real_valid_v1_sourced_from_v5(telco_v5_native_bundle):
    bundle = json.loads(telco_v5_native_bundle["bundle_output_path"].read_text())
    assert bundle["result_semantics"]["schema_version"] == "binary-result-semantics.v1"
    assert bundle["result_semantics"]["positive_class"] == {"class_id": "Yes", "event_label": "Churn"}
    assert bundle["result_semantics"]["model_descriptor"]["model_family"] == "hist_gradient_boosting"


def test_collision_safe_allocator_selects_dash_002_with_dash_001_reserved(telco_v5_native_bundle):
    """Project Spec S0263: with release-YYYYMMDD-001 already reserved for
    this run's date, pipeline.release_identity.allocate_release_id selects
    -002, and that -002 identity -- not the internal branch's fixed -001
    provisional fallback -- is the one actually written to the bundle."""
    release_id = telco_v5_native_bundle["release_id"]
    assert release_id.endswith("-002")

    bundle = json.loads(telco_v5_native_bundle["bundle_output_path"].read_text())
    assert bundle["release_context"]["release_id"] == release_id
    assert telco_v5_native_bundle["bundle_result"]["provisional_release_id"] == release_id


@pytest.fixture(scope="module")
def telco_v5_native_candidate(telco_v5_native_bundle):
    tmp_repo = telco_v5_native_bundle["tmp_repo"]
    result = telco_v5_native_bundle["result"]
    release_id = telco_v5_native_bundle["release_id"]

    discovery_evidence_path = tmp_repo / "pipeline" / "evidence" / DATASET_SLUG / "discovery-evidence.json"
    _write_json(discovery_evidence_path, {
        "schema_version": "discovery-evidence.v1",
        "dataset_metadata": {
            "name": DATASET_SLUG,
            "source_path": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.json",
        },
        "generation_settings": {"seed": 0},
    })

    preparation_recipe_path = tmp_repo / "pipeline" / "authoring" / DATASET_SLUG / "preparation-recipe.json"
    _write_json(preparation_recipe_path, {
        "schema_version": "candidate-preparation-recipe.v1",
        "dataset_slug": DATASET_SLUG,
        "source_data_ref": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.json",
        "ordered_input_columns": FEATURE_COLUMNS + ["Churn"],
        "transformations": [],
        "deterministic": True,
    })

    artifact_references = {
        "discovery_evidence": str(discovery_evidence_path.relative_to(tmp_repo)),
        "execution_contract": str(telco_v5_native_bundle["contract_path"].relative_to(tmp_repo)),
        "runtime_contract": str(telco_v5_native_bundle["runtime_contract_path"].relative_to(tmp_repo)),
        "public_contract": str(telco_v5_native_bundle["public_contract_path"].relative_to(tmp_repo)),
        "preparation_recipe": str(preparation_recipe_path.relative_to(tmp_repo)),
        "prepared_data_metadata": str(telco_v5_native_bundle["prepared_data_metadata_path"].relative_to(tmp_repo)),
        "training_parameter_record": result.training_parameter_record_path,
        "model_artifact": result.serialized_model_path,
        "training_metrics": result.metrics_path,
        "model_card": result.model_card_path,
        "public_context": str(telco_v5_native_bundle["dataset_context_path"].relative_to(tmp_repo)),
        "visualizations": result.analytical_visualizations_path,
        "inference_bundle": str(telco_v5_native_bundle["bundle_output_path"].relative_to(tmp_repo)),
    }

    readiness = assemble_candidate.build_release_candidate_handoff_readiness(
        artifact_references, repo_root=tmp_repo
    )
    assert readiness["is_release_candidate_input_ready"], readiness["blocking_reasons"]

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=release_id,
        source_run_id=Path(result.output_directory.rstrip("/")).name,
        artifact_references=artifact_references,
        repo_root=tmp_repo,
        release_version="1.0.0-rc.1",
        dataset_title="Telco Customer Churn",
    )

    assert candidate_input["artifact_inputs"]["training_parameter_record"]["contract_version"] == (
        "training-parameter-record.v5"
    )
    assert candidate_input["artifact_inputs"]["training_metrics"]["contract_version"] == "training-metrics.v5"
    assert candidate_input["artifact_inputs"]["visualizations"]["contract_version"] == (
        "analytical-visualizations.v5"
    )
    assert candidate_input["artifact_inputs"]["training_parameter_record"]["source_stage"] == "M24"

    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/validation/release-candidate-validation.schema.json",
        "publisher/evidence/publication-validation-evidence.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
        "pipeline/validated-run-terminal-result.schema.json",
    ):
        src = REPO_ROOT / relative
        dst = tmp_repo / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    candidate_output_dir = tmp_repo / "releases" / "candidates"
    assembly_result = assemble_candidate.assemble_release_candidate(
        candidate_input, candidate_output_dir, repo_root=tmp_repo,
    )

    return {
        **telco_v5_native_bundle,
        "candidate_input": candidate_input,
        "assembly_result": assembly_result,
    }


class TestTelcoNativeBinaryV5CandidateAssemblyAndPublisher:
    def test_candidate_assembly_accepted(self, telco_v5_native_candidate):
        assembly_result = telco_v5_native_candidate["assembly_result"]
        assert assembly_result["status"] == "accepted", assembly_result

    def test_candidate_carries_the_collision_safe_dash_002_release_id(self, telco_v5_native_candidate):
        release_id = telco_v5_native_candidate["release_id"]
        assert release_id.endswith("-002")
        assert telco_v5_native_candidate["candidate_input"]["release_identity"]["release_id"] == release_id

        candidate_dir = Path(telco_v5_native_candidate["assembly_result"]["candidate_dir"])
        predictive_bundle = json.loads((candidate_dir / "predictions" / "bundle.json").read_text())
        assert predictive_bundle["release_context"]["release_id"] == release_id

    def test_release_candidate_carries_binary_result_semantics(self, telco_v5_native_candidate):
        candidate_dir = Path(telco_v5_native_candidate["assembly_result"]["candidate_dir"])
        predictive_bundle = json.loads((candidate_dir / "predictions" / "bundle.json").read_text())
        assert predictive_bundle["result_semantics"]["problem_type"] == "binary_classification"
        assert predictive_bundle["result_semantics"]["model_descriptor"]["model_family"] == (
            "hist_gradient_boosting"
        )


@pytest.fixture(scope="module")
def telco_v5_publisher_run(telco_v5_native_candidate):
    tmp_repo = telco_v5_native_candidate["tmp_repo"]
    assembly_result = telco_v5_native_candidate["assembly_result"]

    materialization_result = publisher_validate.materialize_validation_run(
        assembly_result, repo_root=tmp_repo,
    )

    return {
        **telco_v5_native_candidate,
        "materialization_result": materialization_result,
    }


class TestTelcoPublisherRunMaterialization:
    """Section M (Project Spec S0260): materialize_validation_run reaches an
    accepted, manifest-generated Publisher Run, and the resulting terminal
    result can complete and become promotion-eligible."""

    def test_publisher_run_materialized_and_accepted(self, telco_v5_publisher_run):
        result = telco_v5_publisher_run["materialization_result"]
        assert result["materialization_status"] == "materialized", result
        assert result["validation_outcome"] == "accepted", result

    def test_publisher_run_manifest_generated(self, telco_v5_publisher_run):
        result = telco_v5_publisher_run["materialization_result"]
        assert result["manifest_generated"] is True, result

    def test_publisher_run_directory_carries_validation_result_and_manifest(self, telco_v5_publisher_run):
        tmp_repo = telco_v5_publisher_run["tmp_repo"]
        result = telco_v5_publisher_run["materialization_result"]
        run_dir = tmp_repo / result["run_dir"]
        assert run_dir.is_dir()
        assert (run_dir / "validation-result.json").is_file()
        assert (run_dir / "manifest.json").is_file()

    def test_validated_run_terminal_result_completes_and_is_promotion_eligible(self, telco_v5_publisher_run):
        tmp_repo = telco_v5_publisher_run["tmp_repo"]
        result = telco_v5_publisher_run["materialization_result"]
        candidate_dir = Path(telco_v5_publisher_run["assembly_result"]["candidate_dir"])

        def _durable_ref(relative_path):
            return {"path": relative_path, "sha256": generate_inference_bundle._sha256_file(tmp_repo / relative_path)}

        release_candidate_relative_path = str(
            (candidate_dir / "release-candidate.json").relative_to(tmp_repo)
        )
        durable_references = {
            "materialization_result": None,
            "inference_bundle": _durable_ref(
                str(telco_v5_publisher_run["bundle_output_path"].relative_to(tmp_repo))
            ),
            "release_candidate": _durable_ref(release_candidate_relative_path),
            "publisher_validation_result": _durable_ref(f"{result['run_dir']}/validation-result.json"),
            "manifest": _durable_ref(result["manifest_path"]),
            "operational_readiness_source": None,
        }

        terminal_result = validated_run.materialize_validated_run_terminal_result(
            run_id=Path(telco_v5_publisher_run["result"].output_directory.rstrip("/")).name,
            dataset_slug=DATASET_SLUG,
            model_source_mode="atlas_internal_training",
            status="completed",
            durable_references=durable_references,
            structural_validation={"validation_outcome": result["validation_outcome"]},
            manifest_outcome={"manifest_generated": True, "manifest_path": result["manifest_path"]},
            operational_readiness={
                "operational_validity": "not_applicable",
                "operational_threshold": {"status": "not_applicable", "value": None},
                "operational_prediction_available": False,
            },
            reasons=None,
            repo_root=tmp_repo,
        )

        assert terminal_result["status"] == "completed"
        assert terminal_result["promotion_eligibility"] is True
        assert terminal_result["model_source_mode"] == "atlas_internal_training"

    def test_no_real_repository_candidate_directory_created(self):
        # Telco already has real, historical candidate directories under the
        # real repository tree (unrelated to this fixture suite) -- compare
        # against the snapshot captured at module import time rather than
        # assuming the tree starts empty.
        after = (
            {p.name for p in _REAL_TELCO_CANDIDATE_ROOT.iterdir() if p.is_dir()}
            if _REAL_TELCO_CANDIDATE_ROOT.is_dir()
            else set()
        )
        assert after == _REAL_TELCO_CANDIDATE_DIRS_BEFORE

    def test_no_real_repository_training_run_directory_created_for_this_fixture(self, telco_v5_native_run):
        real_training_runs_root = REPO_ROOT / "pipeline" / "training-runs" / DATASET_SLUG
        fixture_run_id = Path(telco_v5_native_run["result"].output_directory.rstrip("/")).name
        assert not (real_training_runs_root / fixture_run_id).exists()


# ===========================================================================
# Fail-closed cross-artifact mismatch: a v5 candidate whose metrics artifact
# disagrees with the rest of the lineage on positive_class_id must never
# reach an accepted Publisher Run.
# ===========================================================================


def _mutated_candidate_copy(candidate_dir: Path, destination: Path, *, relative_path: str, mutator) -> Path:
    shutil.copytree(candidate_dir, destination)
    target = destination / relative_path
    data = json.loads(target.read_text(encoding="utf-8"))
    mutator(data)
    target.write_text(json.dumps(data), encoding="utf-8")
    return destination


def _rejection_safe_details(result: dict) -> set:
    return {reason["safe_detail"] for reason in result["rejection_reasons"] if "safe_detail" in reason}


def test_metrics_positive_class_mismatch_rejected(telco_v5_native_candidate, tmp_path):
    candidate_dir = Path(telco_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-metrics-positive-class",
        relative_path="metrics/metrics.json",
        mutator=lambda data: data["classification_evidence"].__setitem__("positive_class_id", "No"),
    )

    # publisher.validate.materialize_validation_run calls this exact same
    # structural-validation boundary internally (never a different check) --
    # a rejected candidate here can never reach an accepted, manifest-
    # generated Publisher Run through materialize_validation_run either.
    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert result["valid"] is False
    assert "native_binary_v5_positive_class_mismatch" in _rejection_safe_details(result)

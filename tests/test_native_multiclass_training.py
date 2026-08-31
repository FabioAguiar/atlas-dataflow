"""
Project Spec S0216: Native Multiclass Training Run and Evidence
Materialization Contract.

Proves Atlas-native HGB fixed-configuration multiclass training end-to-end
using the real, local, gitignored Dry Bean raw dataset
(data/raw/dry-bean/dataset.csv) inside a temporary Atlas workspace: real
model training, real training-parameter-record.v2/training-metrics.v2/
analytical-visualizations.v2 evidence artifacts, governed inference-bundle
generation, release-candidate assembly, publisher structural validation,
temporary manifest/promotion/registry activation (contained entirely inside
the temporary workspace), and public metrics/visualizations projection.

No official release or real registry mutation is performed by any test in
this module -- every promotion/registry call below is scoped to its own
tmp_path repository, never the real repository. Also proves the legacy
binary/Telco native training path (selection_mode absent or
evaluate_allowed_families) remains completely unaffected.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import jsonschema
import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate, contract_derivation, discovery_evidence, generate_inference_bundle, training
from publisher import manifest as publisher_manifest
from publisher import validate as publisher_validate
from publisher import promote as publisher_promote
from registry import update as registry_update

sys.path.insert(0, str(REPO_ROOT / "api"))
import public_metrics_loader  # noqa: E402
import public_visualizations_loader  # noqa: E402


DRY_BEAN_RAW_PATH = REPO_ROOT / "data" / "raw" / "dry-bean" / "dataset.csv"

DRY_BEAN_FEATURE_COLUMNS = [
    "Area", "Perimeter", "MajorAxisLength", "MinorAxisLength", "AspectRatio",
    "Eccentricity", "ConvexArea", "EquivDiameter", "Extent", "Solidity",
    "Roundness", "Compactness", "ShapeFactor1", "ShapeFactor2", "ShapeFactor3", "ShapeFactor4",
]
# Deterministic under the known label set: plain alphabetical order, which
# is exactly the order sklearn's HistGradientBoostingClassifier.classes_
# produces for string labels -- authored here, then asserted against the
# real fitted model's own classes_ below (Project Spec S0216 Desired
# Change Z: the notebook/authoring layer must never silently reorder).
DRY_BEAN_ORDERED_CLASS_IDS = ["BARBUNYA", "BOMBAY", "CALI", "DERMASON", "HOROZ", "SEKER", "SIRA"]

DATASET_SLUG = "dry-bean"

pytestmark = pytest.mark.skipif(
    not DRY_BEAN_RAW_PATH.is_file(),
    reason=(
        "data/raw/dry-bean/dataset.csv is a local, gitignored raw input "
        "required for this real native multiclass end-to-end run"
    ),
)


def _load_schema(relative_path: str) -> dict:
    return json.loads((REPO_ROOT / relative_path).read_text(encoding="utf-8"))


def _dry_bean_training_policy_intent() -> dict:
    return {
        "review_status": "approved",
        "numeric_handling": "passthrough",
        "categorical_encoding_policy": "onehot",
        "allowed_transformations": ["passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.70,
            "val_ratio": 0.15,
            "test_ratio": 0.15,
        },
        "primary_metric": "f1_macro",
        "secondary_metrics": ["balanced_accuracy", "f1_weighted", "recall_macro", "accuracy", "log_loss"],
        "modeling_constraints": {
            "allowed_model_families": ["hist_gradient_boosting"],
            "no_automl": True,
            "selection_mode": "fixed_configuration",
            "fixed_model_configuration": {
                "model_family": "hist_gradient_boosting",
                "hyperparameters": {
                    "class_weight": None,
                    "l2_regularization": 0.0,
                    "learning_rate": 0.05,
                    "max_iter": 250,
                    "max_leaf_nodes": 15,
                    "min_samples_leaf": 40,
                },
            },
        },
    }


def _dry_bean_semantic_intent() -> dict:
    field_role_decisions = [
        {
            "field_name": name,
            "role": "feature",
            "include_in_features": True,
            "missing_value_intent": {"policy": "no_missing_expected"},
        }
        for name in DRY_BEAN_FEATURE_COLUMNS
    ]
    field_role_decisions.append({
        "field_name": "Class",
        "role": "target",
        "include_in_features": False,
        "exclusion_reason": "Governed multiclass target.",
    })
    return {
        "schema_version": "dataset-semantic-intent.v2",
        "artifact_type": "dataset_semantic_intent",
        "dataset_identity": {"dataset_slug": DATASET_SLUG, "dataset_logical_name": "Dry Bean"},
        "authoring_generation_id": "dry-bean-authoring-v1",
        "governing_capability_profile": {
            "capability_profile_id": "multiclass-predictive-classification",
            "capability_profile_version": "v1",
        },
        "field_role_decisions": field_role_decisions,
        "target_semantics": {
            "target_field_name": "Class",
            "task_type": "multiclass_classification",
            "classes": [
                {"class_id": class_id, "display_label": class_id.title()}
                for class_id in DRY_BEAN_ORDERED_CLASS_IDS
            ],
            "is_final_training_configuration": False,
        },
        "authored_public_meaning": {
            "human_reviewed": True,
            "safe_projection_intent": "Estimate dry bean variety from reviewed geometric shape measurements.",
        },
        "semantic_boundary_confirmations": {
            "observed_source_statistics_embedded": False,
            "scientific_conclusions_embedded": False,
            "training_outcome_embedded": False,
            "release_state_embedded": False,
            "model_bytes_embedded": False,
        },
        "generated_at": "2026-08-18T00:00:00+00:00",
    }


def _build_dry_bean_execution_contract() -> dict:
    raw_discovery_evidence = discovery_evidence.generate_discovery_evidence(
        DRY_BEAN_RAW_PATH, seed=42, generated_at="2026-08-18T00:00:00+00:00"
    )
    multiclass_result_semantics_intent = discovery_evidence.build_multiclass_result_semantics_intent(
        review_status="approved",
        problem_type="multiclass_classification",
        primary_output="predicted_class",
        probability_output="class_probabilities",
        decision_strategy="argmax",
    )
    modeling_intent = discovery_evidence.build_dataset_modeling_intent(
        dataset_slug=DATASET_SLUG,
        dataset_source_ref="data/raw/dry-bean/dataset.csv",
        authoring_notebook_ref="notebooks/datasets/dry-bean/dataset_integration.ipynb",
        columns=DRY_BEAN_FEATURE_COLUMNS + ["Class"],
        target_column="Class",
        task_type="classification",
        observed_labels=DRY_BEAN_ORDERED_CLASS_IDS,
        positive_label_candidate=None,
        observed_target_distribution={},
        identifier_columns=[],
        training_policy_intent=_dry_bean_training_policy_intent(),
        multiclass_result_semantics_intent=multiclass_result_semantics_intent,
        generated_at="2026-08-18T00:00:00+00:00",
    )
    semantic_intent = _dry_bean_semantic_intent()
    contract = contract_derivation._build_execution_contract(
        modeling_intent, raw_discovery_evidence, None, semantic_intent=semantic_intent
    )
    return contract


class TestExecutionContractMaterializesFixedConfigurationPolicy:
    def test_contract_carries_reviewed_training_policy_verbatim(self):
        contract = _build_dry_bean_execution_contract()
        assert contract["numeric_handling"] == "passthrough"
        assert contract["categorical_encoding_policy"] == "onehot"
        assert contract["allowed_transformations"] == ["passthrough"]
        assert contract["split_policy"] == {
            "strategy": "stratified", "train_ratio": 0.70, "val_ratio": 0.15, "test_ratio": 0.15,
        }
        assert contract["primary_metric"] == "f1_macro"
        assert contract["secondary_metrics"] == [
            "balanced_accuracy", "f1_weighted", "recall_macro", "accuracy", "log_loss",
        ]
        assert contract["modeling_constraints"]["selection_mode"] == "fixed_configuration"
        assert contract["modeling_constraints"]["allowed_model_families"] == ["hist_gradient_boosting"]

    def test_contract_validates_against_real_schema(self):
        contract = _build_dry_bean_execution_contract()
        schema = _load_schema("contracts/execution-contract.schema.json")
        jsonschema.validate(contract, schema)

    def test_contract_result_semantics_class_order_is_alphabetical(self):
        contract = _build_dry_bean_execution_contract()
        result_semantics = contract["result_semantics"]
        assert result_semantics["schema_version"] == "multiclass-result-semantics.v1"
        assert [entry["class_id"] for entry in result_semantics["classes"]] == DRY_BEAN_ORDERED_CLASS_IDS
        assert result_semantics["decision"]["strategy"] == "argmax"

    def test_unapproved_training_policy_is_rejected_not_silently_defaulted(self):
        raw_discovery_evidence = discovery_evidence.generate_discovery_evidence(DRY_BEAN_RAW_PATH, seed=42)
        policy = _dry_bean_training_policy_intent()
        policy["review_status"] = "pending_review"
        modeling_intent = discovery_evidence.build_dataset_modeling_intent(
            dataset_slug=DATASET_SLUG,
            dataset_source_ref="data/raw/dry-bean/dataset.csv",
            authoring_notebook_ref="notebooks/datasets/dry-bean/dataset_integration.ipynb",
            columns=DRY_BEAN_FEATURE_COLUMNS + ["Class"],
            target_column="Class",
            task_type="classification",
            observed_labels=DRY_BEAN_ORDERED_CLASS_IDS,
            positive_label_candidate=None,
            observed_target_distribution={},
            identifier_columns=[],
            training_policy_intent=policy,
        )
        with pytest.raises(contract_derivation.TrainingPolicyValidationError):
            contract_derivation._build_execution_contract(modeling_intent, raw_discovery_evidence, None)


class TestLegacyBinaryDerivationDefaultsUnchanged:
    def test_no_training_policy_intent_preserves_legacy_defaults(self):
        raw_discovery_evidence = discovery_evidence.generate_discovery_evidence(DRY_BEAN_RAW_PATH, seed=42)
        modeling_intent = discovery_evidence.build_dataset_modeling_intent(
            dataset_slug=DATASET_SLUG,
            dataset_source_ref="data/raw/dry-bean/dataset.csv",
            authoring_notebook_ref="notebooks/datasets/dry-bean/dataset_integration.ipynb",
            columns=DRY_BEAN_FEATURE_COLUMNS + ["Class"],
            target_column="Class",
            task_type="classification",
            observed_labels=DRY_BEAN_ORDERED_CLASS_IDS,
            positive_label_candidate=None,
            observed_target_distribution={},
            identifier_columns=[],
        )
        contract = contract_derivation._build_execution_contract(modeling_intent, raw_discovery_evidence, None)
        assert contract["numeric_handling"] == "standardize"
        assert contract["primary_metric"] == "roc_auc"
        assert "selection_mode" not in contract["modeling_constraints"]


@pytest.fixture(scope="module")
def _dry_bean_tmp_repo_root(tmp_path_factory):
    """Patch pipeline.training._repo_root to a temporary Atlas workspace for
    the whole module's fixture chain -- both pipeline.training.train_from_paths
    and pipeline.generate_inference_bundle's reused
    pipeline.training._prepared_dataset_metadata_blocking_reasons import
    resolve repository-relative paths via this same module-level function,
    so it must stay patched until every downstream fixture (bundle,
    candidate, active release) in this module has finished, not just the
    training run itself. Restored once, at module teardown."""
    tmp_repo = tmp_path_factory.mktemp("dry_bean_native_repo")
    original_repo_root = training._repo_root
    training._repo_root = lambda: tmp_repo
    yield tmp_repo
    training._repo_root = original_repo_root


@pytest.fixture(scope="module")
def dry_bean_native_run(_dry_bean_tmp_repo_root):
    """Build the full native multiclass authoring chain in a real temporary
    Atlas workspace and run governed training exactly once, real HGB model
    fit on the real Dry Bean data. Session-shared across this module's
    assertions purely for wall-clock efficiency; every assertion below is
    read-only against the already-produced artifacts.
    """
    tmp_repo = _dry_bean_tmp_repo_root

    contract = _build_dry_bean_execution_contract()
    contract_path = tmp_repo / "contracts" / DATASET_SLUG / "execution-contract.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2, sort_keys=True), encoding="utf-8")

    prepared_dataset_path = tmp_repo / "pipeline" / "prepared" / DATASET_SLUG / "prepared-data.csv"
    prepared_dataset_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DRY_BEAN_RAW_PATH, prepared_dataset_path)

    result = training.train_from_paths(
        contract_path, prepared_dataset_path, dataset_slug=DATASET_SLUG
    )

    return {
        "tmp_repo": tmp_repo,
        "contract": contract,
        "contract_path": contract_path,
        "prepared_dataset_path": prepared_dataset_path,
        "result": result,
    }


class TestNativeMulticlassTrainingRun:
    def test_status_and_model_family(self, dry_bean_native_run):
        result = dry_bean_native_run["result"]
        assert result.status == "trained"
        assert result.model_family == "hist_gradient_boosting"
        assert result.model_selection_evidence_produced is False
        assert result.model_selection_evidence_path is None

    def test_real_model_exposes_seven_classes_in_alphabetical_order(self, dry_bean_native_run):
        model = dry_bean_native_run["result"].model
        classes = list(model.named_steps["model"].classes_)
        assert [str(c) for c in classes] == DRY_BEAN_ORDERED_CLASS_IDS

    def test_real_predict_proba_sums_to_one_and_agrees_with_predict(self, dry_bean_native_run):
        tmp_repo = dry_bean_native_run["tmp_repo"]
        result = dry_bean_native_run["result"]
        model = result.model
        import pandas as pd

        sample = pd.read_csv(dry_bean_native_run["prepared_dataset_path"]).head(20)
        features = sample[DRY_BEAN_FEATURE_COLUMNS]
        probabilities = model.predict_proba(features)
        predictions = model.predict(features)
        classes = list(model.named_steps["model"].classes_)

        for row_index in range(len(features)):
            row_probs = probabilities[row_index]
            assert abs(sum(row_probs) - 1.0) < 1e-6
            argmax_class = classes[int(row_probs.argmax())]
            assert argmax_class == predictions[row_index]

    def test_training_parameter_record_v2_validates_and_carries_fixed_finalization_evidence(
        self, dry_bean_native_run
    ):
        tmp_repo = dry_bean_native_run["tmp_repo"]
        result = dry_bean_native_run["result"]
        schema = _load_schema("pipeline/training-parameter-record.schema.json")
        record = json.loads((tmp_repo / result.training_parameter_record_path).read_text())
        jsonschema.validate(record, schema)

        assert record["schema_version"] == "training-parameter-record.v2"
        params = record["training_parameters"]
        assert params["selection_mode"] == "fixed_configuration"
        assert params["model_selection_performed"] is False
        assert params["initial_fit"] == {"fit_partition": "train"}
        assert params["validation_evaluation"] == {
            "partition": "validation", "used_for_model_selection": False,
            "used_for_hyperparameter_selection": False,
        }
        assert params["final_fit"] == {"fit_partitions": ["train", "validation"]}
        assert params["final_test"]["evaluation_count"] == 1
        assert params["final_test"]["used_for_fitting"] is False
        assert params["final_test"]["used_for_model_selection"] is False

        classification_evidence = record["classification_evidence"]
        assert classification_evidence["ordered_class_ids"] == DRY_BEAN_ORDERED_CLASS_IDS
        for index, column in enumerate(classification_evidence["probability_columns"]):
            assert column["probability_index"] == index
            assert column["class_id"] == DRY_BEAN_ORDERED_CLASS_IDS[index]

        split_sizes = params["split_sizes"]
        assert (
            split_sizes["training_rows"] + split_sizes["validation_rows"] + split_sizes["test_rows"] == 13611
        )
        assert split_sizes["final_fit_rows"] == split_sizes["training_rows"] + split_sizes["validation_rows"]

    def test_training_metrics_v2_validates_and_separates_validation_from_final_test(
        self, dry_bean_native_run
    ):
        tmp_repo = dry_bean_native_run["tmp_repo"]
        result = dry_bean_native_run["result"]
        schema = _load_schema("pipeline/training-metrics.schema.json")
        metrics = json.loads((tmp_repo / result.metrics_path).read_text())
        jsonschema.validate(metrics, schema)

        assert metrics["schema_version"] == "training-metrics.v2"
        assert metrics["classification_evidence"]["ordered_class_ids"] == DRY_BEAN_ORDERED_CLASS_IDS

        final_test = metrics["final_test_evaluation"]
        assert final_test["completed"] is True
        assert final_test["evaluation_count"] == 1
        assert final_test["sealed_before_finalization"] is True
        assert final_test["used_for_fitting"] is False
        assert final_test["used_for_model_selection"] is False

        validation = metrics["validation_evaluation"]
        assert validation["used_for_model_selection"] is False
        assert validation["used_for_fitting"] is False

        final_metric_names = {item["name"] for item in final_test["metrics"]}
        assert {"f1_macro", "balanced_accuracy", "f1_weighted", "recall_macro", "accuracy", "log_loss"}.issubset(
            final_metric_names
        )
        for item in final_test["metrics"]:
            assert isinstance(item["value"], (int, float))
            assert item["value"] == item["value"]  # not NaN

        # A real, non-trivial fitted classifier on a well-separated
        # geometric dataset should score well above chance.
        final_accuracy = next(m["value"] for m in final_test["metrics"] if m["name"] == "accuracy")
        assert final_accuracy > 0.85

        per_class = final_test["per_class_metrics"]
        assert [entry["class_id"] for entry in per_class] == DRY_BEAN_ORDERED_CLASS_IDS
        for entry in per_class:
            assert 0.0 <= entry["precision"] <= 1.0
            assert 0.0 <= entry["recall"] <= 1.0
            assert 0.0 <= entry["f1"] <= 1.0
            assert entry["support"] >= 0

    def test_analytical_visualizations_v2_validates_with_feature_importance_and_confusion_matrix(
        self, dry_bean_native_run
    ):
        tmp_repo = dry_bean_native_run["tmp_repo"]
        result = dry_bean_native_run["result"]
        schema = _load_schema("pipeline/analytical-visualizations.schema.json")
        viz = json.loads((tmp_repo / result.analytical_visualizations_path).read_text())
        jsonschema.validate(viz, schema)

        assert viz["schema_version"] == "analytical-visualizations.v2"
        chart_ids = {chart["id"] for chart in viz["charts"]}
        assert chart_ids == {"target_distribution", "feature_importance"}

        feature_importance_chart = next(c for c in viz["charts"] if c["id"] == "feature_importance")
        assert len(feature_importance_chart["data"]) <= 10
        assert all(point["value"] >= 0 for point in feature_importance_chart["data"])

        method = viz["feature_importance_method"]
        assert method["model_family"] == "hist_gradient_boosting"
        assert method["source"] == "sklearn.inspection.permutation_importance"

        confusion_matrix = viz["confusion_matrix"]
        assert confusion_matrix["ordered_class_ids"] == DRY_BEAN_ORDERED_CLASS_IDS
        assert confusion_matrix["row_axis"] == "true_class"
        assert confusion_matrix["column_axis"] == "predicted_class"
        for row in confusion_matrix["matrix"]:
            assert abs(sum(row) - 1.0) < 1e-6
            assert all(0.0 <= value <= 1.0 for value in row)

    def test_no_model_selection_evidence_artifact_is_produced(self, dry_bean_native_run):
        tmp_repo = dry_bean_native_run["tmp_repo"]
        result = dry_bean_native_run["result"]
        run_dir = tmp_repo / result.output_directory
        assert not (run_dir / "model-selection-evidence.json").exists()


@pytest.fixture(scope="module")
def dry_bean_native_bundle(dry_bean_native_run):
    tmp_repo = dry_bean_native_run["tmp_repo"]
    result = dry_bean_native_run["result"]

    runtime_contract_path = tmp_repo / "contracts" / DATASET_SLUG / "runtime-contract.json"
    runtime_contract_path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "features": [{"name": name, "type": "numeric", "required": True} for name in DRY_BEAN_FEATURE_COLUMNS],
    }))
    public_contract_path = tmp_repo / "contracts" / DATASET_SLUG / "public-contract.json"
    public_contract_path.write_text(json.dumps({
        "schema_version": "1.0.0",
        "features": [
            {
                "name": name, "label": name, "input_type": "number", "optional": False, "display_order": index + 1,
            }
            for index, name in enumerate(DRY_BEAN_FEATURE_COLUMNS)
        ],
    }))
    dataset_context_path = tmp_repo / "contracts" / DATASET_SLUG / "dataset-context.json"
    dataset_context_path.write_text(json.dumps({
        "schema_version": "dataset-context.v1",
        "dataset_slug": DATASET_SLUG,
        "dataset_title": "Dry Bean",
    }))

    prepared_data_metadata_path = tmp_repo / "pipeline" / "prepared" / DATASET_SLUG / "prepared-data-metadata.json"
    prepared_data_metadata_path.write_text(json.dumps({
        "schema_version": "prepared-data-metadata.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "prepared_candidate": {
            "produced": True,
            "reference": "pipeline/prepared/dry-bean/prepared-data.csv",
        },
        "training_readiness": {"is_training_ready": True},
        "unresolved_review_items": [],
    }))

    run_id = Path(result.output_directory.rstrip("/")).name
    provisional_release_id = generate_inference_bundle._derive_provisional_release_id(run_id)

    training_run_materialization_result = {
        "artifact_type": "training_run_materialization_result",
        "contract_version": "training_run_materialization_result.v1",
        "status": "trained",
        "training_result": result.to_summary(),
    }

    bundle_output_path = tmp_repo / "pipeline" / "inference-bundles" / DATASET_SLUG / "inference-bundle.json"
    bundle_result = generate_inference_bundle.materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        execution_contract_path=dry_bean_native_run["contract_path"],
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_data_metadata_path=prepared_data_metadata_path,
        output_path=bundle_output_path,
        prediction_type="string",
        repo_root=tmp_repo,
        dataset_slug=DATASET_SLUG,
        class_labels=DRY_BEAN_ORDERED_CLASS_IDS,
        probability_output=True,
        execution_contract_ref=f"contracts/{DATASET_SLUG}/execution-contract.json",
        runtime_contract_ref=f"contracts/{DATASET_SLUG}/runtime-contract.json",
        public_contract_ref=f"contracts/{DATASET_SLUG}/public-contract.json",
        dataset_context_ref=f"contracts/{DATASET_SLUG}/dataset-context.json",
        inference_bundle_schema_path=str(REPO_ROOT / "contracts" / "inference-bundle.schema.json"),
        model_package_reference="models/model.pkl",
        release_id=provisional_release_id,
    )

    return {
        **dry_bean_native_run,
        "bundle_result": bundle_result,
        "bundle_output_path": bundle_output_path,
        "release_id": provisional_release_id,
        "runtime_contract_path": runtime_contract_path,
        "public_contract_path": public_contract_path,
        "dataset_context_path": dataset_context_path,
        "prepared_data_metadata_path": prepared_data_metadata_path,
    }


class TestNativeMulticlassInferenceBundle:
    def test_bundle_is_generated_and_schema_valid(self, dry_bean_native_bundle):
        assert dry_bean_native_bundle["bundle_result"]["status"] == "generated", dry_bean_native_bundle["bundle_result"]
        schema = _load_schema("contracts/inference-bundle.schema.json")
        bundle = json.loads(dry_bean_native_bundle["bundle_output_path"].read_text())
        jsonschema.validate(bundle, schema)

    def test_bundle_runtime_execution_uses_hist_gradient_boosting(self, dry_bean_native_bundle):
        bundle = json.loads(dry_bean_native_bundle["bundle_output_path"].read_text())
        assert bundle["runtime_execution"]["model_family"] == "hist_gradient_boosting"

    def test_bundle_runtime_execution_is_explicitly_in_process(self, dry_bean_native_bundle):
        # Project Spec S0285: native multiclass generation declares the
        # canonical in-process execution strategy.
        bundle = json.loads(dry_bean_native_bundle["bundle_output_path"].read_text())
        assert bundle["runtime_execution"]["execution_strategy"] == "in_process"

    def test_bundle_result_semantics_is_multiclass_argmax_with_real_class_order(self, dry_bean_native_bundle):
        bundle = json.loads(dry_bean_native_bundle["bundle_output_path"].read_text())
        result_semantics = bundle["result_semantics"]
        assert result_semantics["schema_version"] == "multiclass-result-semantics.v1"
        assert result_semantics["problem_type"] == "multiclass_classification"
        assert result_semantics["decision"]["strategy"] == "argmax"
        assert [c["class_id"] for c in result_semantics["classes"]] == DRY_BEAN_ORDERED_CLASS_IDS
        assert bundle["output_schema"]["class_labels"] == DRY_BEAN_ORDERED_CLASS_IDS
        assert bundle["output_schema"]["probability_output"] is True

    def test_bundle_carries_training_evidence_not_external(self, dry_bean_native_bundle):
        bundle = json.loads(dry_bean_native_bundle["bundle_output_path"].read_text())
        assert "training_evidence" in bundle
        assert "external_model_evidence" not in bundle
        assert bundle.get("model_provenance_origin") is None


@pytest.fixture(scope="module")
def dry_bean_native_candidate(dry_bean_native_bundle, tmp_path_factory):
    tmp_repo = dry_bean_native_bundle["tmp_repo"]
    result = dry_bean_native_bundle["result"]
    release_id = dry_bean_native_bundle["release_id"]

    # Built directly via the pure, side-effect-free generate_discovery_evidence
    # (never materialize_discovery_evidence's own repo_root resolution,
    # which falls back to searching this installed package's real
    # repository location -- not the safely isolated tmp_repo -- whenever
    # tmp_repo itself lacks repository marker files).
    discovery_evidence_path = tmp_repo / "pipeline" / "evidence" / DATASET_SLUG / "discovery-evidence.json"
    discovery_evidence_path.parent.mkdir(parents=True, exist_ok=True)
    real_evidence = discovery_evidence.generate_discovery_evidence(DRY_BEAN_RAW_PATH, seed=42)
    real_evidence["dataset_metadata"]["name"] = DATASET_SLUG
    real_evidence["dataset_metadata"]["source_path"] = "data/raw/dry-bean/dataset.csv"
    discovery_evidence_path.write_text(json.dumps(real_evidence, indent=2), encoding="utf-8")

    preparation_recipe_path = tmp_repo / "pipeline" / "authoring" / DATASET_SLUG / "preparation-recipe.json"
    preparation_recipe_path.parent.mkdir(parents=True, exist_ok=True)
    preparation_recipe_path.write_text(json.dumps({
        "schema_version": "candidate-preparation-recipe.v1",
        "dataset_slug": DATASET_SLUG,
        "source_data_ref": "data/raw/dry-bean/dataset.csv",
        "ordered_input_columns": DRY_BEAN_FEATURE_COLUMNS + ["Class"],
        "transformations": [],
        "deterministic": True,
    }), encoding="utf-8")

    artifact_references = {
        "discovery_evidence": str(discovery_evidence_path.relative_to(tmp_repo)),
        "execution_contract": str(dry_bean_native_bundle["contract_path"].relative_to(tmp_repo)),
        "runtime_contract": str(dry_bean_native_bundle["runtime_contract_path"].relative_to(tmp_repo)),
        "public_contract": str(dry_bean_native_bundle["public_contract_path"].relative_to(tmp_repo)),
        "preparation_recipe": str(preparation_recipe_path.relative_to(tmp_repo)),
        "prepared_data_metadata": str(dry_bean_native_bundle["prepared_data_metadata_path"].relative_to(tmp_repo)),
        "training_parameter_record": result.training_parameter_record_path,
        "model_artifact": result.serialized_model_path,
        "training_metrics": result.metrics_path,
        "model_card": result.model_card_path,
        "public_context": str(dry_bean_native_bundle["dataset_context_path"].relative_to(tmp_repo)),
        "visualizations": result.analytical_visualizations_path,
        "inference_bundle": str(dry_bean_native_bundle["bundle_output_path"].relative_to(tmp_repo)),
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
        dataset_title="Dry Bean",
    )

    assert candidate_input["artifact_inputs"]["training_parameter_record"]["contract_version"] == (
        "training-parameter-record.v2"
    )
    assert candidate_input["artifact_inputs"]["training_metrics"]["contract_version"] == "training-metrics.v2"
    assert candidate_input["artifact_inputs"]["visualizations"]["contract_version"] == (
        "analytical-visualizations.v2"
    )
    assert candidate_input["artifact_inputs"]["training_parameter_record"]["source_stage"] == "M24"

    # Publisher structural schema-conformance requires the real publisher
    # contract/schema files to exist under this temporary repo root.
    for relative in (
        "publisher/release-candidate.operational-note.json",
        "publisher/release-manifest.schema.json",
        "publisher/validation/release-candidate-validation.schema.json",
        "publisher/evidence/publication-validation-evidence.schema.json",
        "contracts/public-contract.schema.json",
        "pipeline/analytical-visualizations.schema.json",
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
        **dry_bean_native_bundle,
        "candidate_input": candidate_input,
        "assembly_result": assembly_result,
    }


class TestNativeMulticlassCandidateAssemblyAndPublisher:
    def test_candidate_assembly_accepted_by_publisher_structural_validation(self, dry_bean_native_candidate):
        assembly_result = dry_bean_native_candidate["assembly_result"]
        assert assembly_result["status"] == "accepted", assembly_result

    def test_release_candidate_json_carries_multiclass_result_semantics(self, dry_bean_native_candidate):
        candidate_dir = Path(dry_bean_native_candidate["assembly_result"]["candidate_dir"])
        predictive_bundle = json.loads((candidate_dir / "predictions" / "bundle.json").read_text())
        assert predictive_bundle["result_semantics"]["problem_type"] == "multiclass_classification"


@pytest.fixture(scope="module")
def dry_bean_active_release(dry_bean_native_candidate):
    """Temporary manifest generation, promotion, and registry activation --
    entirely contained inside this module's own tmp_path repository, never
    the real registry/releases directories (Project Spec S0216 Desired
    Change AJ)."""
    tmp_repo = dry_bean_native_candidate["tmp_repo"]
    release_id = dry_bean_native_candidate["release_id"]

    registry_dir = tmp_repo / "registry"
    registry_dir.mkdir(parents=True, exist_ok=True)
    (registry_dir / "datasets.json").write_text(json.dumps({
        "schema_version": "atlas.dataflow.registry.v1",
        "conventions": {
            "dataset_slug": {"pattern": "^[a-z0-9]+(?:-[a-z0-9]+)*$", "description": "Stable dataset identifier."},
            "release_id": {"pattern": "^release-[0-9]{8}-[0-9]{3}$", "description": "Stable release identifier."},
            "active_release": {"description": "Release currently served for the dataset."},
        },
        "datasets": [],
    }, indent=2), encoding="utf-8")

    validation_result = publisher_validate.run(
        str(Path(dry_bean_native_candidate["assembly_result"]["candidate_dir"])), repo_root=tmp_repo
    )
    assert validation_result["validation_outcome"] == "accepted", validation_result

    run_dirs = sorted((tmp_repo / "publisher" / "runs").iterdir())
    run_dir = run_dirs[-1]

    manifest_result = publisher_manifest.run(str(run_dir), repo_root=tmp_repo)
    assert manifest_result["schema_version"] == "release-manifest.v1"

    promotion_result = publisher_promote.run(str(run_dir), repo_root=tmp_repo)
    assert promotion_result["promotion_outcome"] == "promoted"

    registry_result = registry_update.run(str(run_dir), repo_root=tmp_repo)
    assert registry_result["update_applied"] is True

    return {
        **dry_bean_native_candidate,
        "releases_root": tmp_repo / "releases",
    }


class TestNativeMulticlassPublicProjection:
    def test_public_metrics_projection_succeeds(self, dry_bean_active_release):
        projected = public_metrics_loader.load_public_metrics(
            dry_bean_active_release["release_id"], releases_root=dry_bean_active_release["releases_root"]
        )
        evaluation = projected["evaluation"]
        assert "f1_macro" in evaluation["metrics"]
        assert evaluation["metrics"]["f1_macro"] > 0.85
        per_class = evaluation.get("per_class_metrics")
        assert per_class is not None
        assert [entry["class_id"] for entry in per_class] == DRY_BEAN_ORDERED_CLASS_IDS

    def test_public_visualizations_projection_succeeds_with_confusion_matrix(self, dry_bean_active_release):
        projected = public_visualizations_loader.load_public_visualizations(
            dry_bean_active_release["release_id"], releases_root=dry_bean_active_release["releases_root"]
        )
        chart_ids = {chart["id"] for chart in projected["charts"]}
        assert chart_ids == {"target_distribution", "feature_importance"}
        confusion_matrix = projected.get("confusion_matrix")
        assert confusion_matrix is not None
        assert confusion_matrix["ordered_class_ids"] == DRY_BEAN_ORDERED_CLASS_IDS
        for row in confusion_matrix["matrix"]:
            assert abs(sum(row) - 1.0) < 1e-6
        dataset_statistics = projected.get("dataset_statistics")
        assert dataset_statistics is not None
        assert dataset_statistics["instance_count"] == 13611

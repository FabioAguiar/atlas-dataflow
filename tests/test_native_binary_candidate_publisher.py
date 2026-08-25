"""Focused tests for Atlas-native binary v5 candidate assembly and publisher
compatibility (Project Spec S0259).

Covers, using only synthetic Atlas-owned fixtures (never a real dataset,
never `dataset-study-*`, and never a write under the real repository
`releases/candidates/` or `publisher/runs/` trees):

  * `pipeline/assemble_candidate.py`'s native `training-parameter-record.v5`
    provenance recognition (source_stage stays M24, never external, requires
    paired `training-metrics.v5`/`analytical-visualizations.v5`, mixed
    versions fail closed);
  * a synthetic but real-schema end-to-end candidate (real
    `training-parameter-record.v5`, `training-metrics.v5`,
    `analytical-visualizations.v5`, `inference_bundle.v1`, produced by a real
    governed training run against a synthetic dataset) reaching
    `assemble_candidate.assemble_release_candidate` acceptance and
    `publisher.validate` `valid=true`;
  * `publisher/validate.py`'s native binary-v5 predictive-bundle/metrics/
    visualizations compatibility checks, including positive-class and
    model-family cross-artifact mismatches.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate, generate_inference_bundle, training  # noqa: E402
from publisher import validate as publisher_validate  # noqa: E402

DATASET_SLUG = "synthetic-binary-v5-fixture"
FEATURE_COLUMNS = ["input_a", "input_b"]


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# Section A: native training-parameter-record.v5 candidate provenance
# recognition (pipeline/assemble_candidate.py), using lightweight governed
# placeholder artifacts -- build_release_candidate_input never inspects
# artifact content beyond schema_version for these roles.
# ===========================================================================


def _write_handoff_governed_artifacts(repo_root: Path) -> dict:
    paths = {
        "discovery_evidence": "governed-artifacts/m22/discovery-evidence.json",
        "execution_contract": "governed-artifacts/m23/execution-contract.json",
        "runtime_contract": "governed-artifacts/m23/runtime-contract.json",
        "public_contract": "governed-artifacts/m23/public-contract.json",
        "preparation_recipe": "governed-artifacts/m22/preparation-recipe.json",
        "prepared_data_metadata": "governed-artifacts/m23/prepared-data-metadata.json",
        "training_parameter_record": "governed-artifacts/m24/training-parameter-record.json",
        "model_artifact": "governed-artifacts/m24/model.pkl",
        "training_metrics": "governed-artifacts/m24/metrics.json",
        "model_card": "governed-artifacts/m24/model-card.json",
        "public_context": "governed-artifacts/m23/public-context.json",
        "visualizations": "governed-artifacts/m24/visualizations.json",
        "inference_bundle": "governed-artifacts/m25/bundle.json",
    }
    for role, relative in paths.items():
        _write_json(repo_root / relative, {"role": role, "governed": True})
    return paths


_VALID_PUBLIC_CONTRACT = {
    "schema_version": "1.0.0",
    "features": [
        {"name": "input_a", "label": "Input A", "input_type": "number", "optional": False, "display_order": 1},
    ],
}


def _finish_inference_bundle_reference(repo_root: Path, paths: dict) -> None:
    model_artifact_sha256 = generate_inference_bundle._sha256_file(repo_root / paths["model_artifact"])
    _write_json(repo_root / paths["inference_bundle"], {
        "role": "inference_bundle",
        "schema_version": "inference_bundle.v1",
        "model_artifact": {"path": "models/model.pkl", "sha256": model_artifact_sha256},
    })


def _write_v5_binary_governed_artifacts(
    repo_root: Path,
    *,
    training_metrics_version: str = "training-metrics.v5",
    visualizations_version: str = "analytical-visualizations.v5",
) -> dict:
    paths = _write_handoff_governed_artifacts(repo_root)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(repo_root / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    _write_json(repo_root / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v5",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "classification_evidence": {
            "problem_type": "binary_classification",
            "result_semantics_schema_version": "binary-result-semantics.v1",
            "ordered_class_labels": ["no", "yes"],
            "positive_class_id": "yes",
            "positive_class_probability_index": 1,
            "threshold": 0.5,
        },
    })
    _write_json(repo_root / paths["training_metrics"], {"schema_version": training_metrics_version})
    _write_json(repo_root / paths["model_card"], {"schema_version": "model-card-input.v5"})
    _write_json(repo_root / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(repo_root / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(repo_root / paths["visualizations"], {"schema_version": visualizations_version})
    _finish_inference_bundle_reference(repo_root, paths)
    return paths


def _build_v5_candidate_input(tmp_path: Path, **overrides):
    tmp_repo = tmp_path / "repo"
    paths = _write_v5_binary_governed_artifacts(tmp_repo, **overrides)
    return assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id="release-20260819-001",
        source_run_id="native-binary-v5-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )


def test_native_v5_provenance_recognized_explicitly(tmp_path):
    candidate_input = _build_v5_candidate_input(tmp_path)

    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["contract_version"] == "training-parameter-record.v5"
    tm = candidate_input["artifact_inputs"]["training_metrics"]
    assert tm["contract_version"] == "training-metrics.v5"


def test_native_v5_provenance_keeps_source_stage_m24(tmp_path):
    candidate_input = _build_v5_candidate_input(tmp_path)

    assert candidate_input["artifact_inputs"]["training_parameter_record"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["training_metrics"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_card"]["source_stage"] == "M24"
    assert candidate_input["artifact_inputs"]["model_artifact"]["source_stage"] == "M24"


def test_native_v5_provenance_never_external_or_manual_governed_input(tmp_path):
    candidate_input = _build_v5_candidate_input(tmp_path)

    for artifact_input in candidate_input["artifact_inputs"]["internal_evidence_references"]:
        assert artifact_input["source_stage"] != "manual_governed_input"
        assert artifact_input["role"] != "external_model_evidence"


def test_native_v5_carries_real_v5_visualizations_version(tmp_path):
    candidate_input = _build_v5_candidate_input(tmp_path)

    assert (
        candidate_input["artifact_inputs"]["visualizations"]["contract_version"]
        == "analytical-visualizations.v5"
    )


def test_v5_record_requires_paired_v5_metrics_v1_pairing_rejects(tmp_path):
    with pytest.raises(ValueError, match="training_metrics"):
        _build_v5_candidate_input(tmp_path, training_metrics_version="training-metrics.v1")


def test_v5_record_requires_paired_v5_metrics_v2_pairing_rejects(tmp_path):
    with pytest.raises(ValueError, match="training_metrics"):
        _build_v5_candidate_input(tmp_path, training_metrics_version="training-metrics.v2")


def test_v5_visualization_reservation_fails_closed_against_v1_substitution(tmp_path):
    with pytest.raises(ValueError, match="visualizations"):
        _build_v5_candidate_input(tmp_path, visualizations_version="analytical-visualizations.v1")


def test_v5_visualization_reservation_fails_closed_against_v4_substitution(tmp_path):
    with pytest.raises(ValueError, match="visualizations"):
        _build_v5_candidate_input(tmp_path, visualizations_version="analytical-visualizations.v4")


def test_legacy_internal_v1_binary_provenance_remains_unchanged(tmp_path):
    tmp_repo = tmp_path / "repo"
    paths = _write_handoff_governed_artifacts(tmp_repo)
    for role in ("execution_contract", "runtime_contract", "prepared_data_metadata"):
        _write_json(tmp_repo / paths[role], {"role": role, "schema_version": f"{role}.v1"})
    _write_json(tmp_repo / paths["training_parameter_record"], {
        "schema_version": "training-parameter-record.v1",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
    })
    _write_json(tmp_repo / paths["training_metrics"], {"schema_version": "training-metrics.v1"})
    _write_json(tmp_repo / paths["model_card"], {"schema_version": "model-card.v1"})
    _write_json(tmp_repo / paths["public_context"], {"role": "public_context", "schema_version": "x"})
    _write_json(tmp_repo / paths["public_contract"], _VALID_PUBLIC_CONTRACT)
    _write_json(tmp_repo / paths["visualizations"], {"schema_version": "analytical-visualizations.v1"})
    _finish_inference_bundle_reference(tmp_repo, paths)

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id="release-20260819-001",
        source_run_id="internal-run-20260819T000000Z",
        artifact_references=paths,
        repo_root=tmp_repo,
    )
    tpr = candidate_input["artifact_inputs"]["training_parameter_record"]
    assert tpr["source_stage"] == "M24"
    assert tpr["contract_version"] == "training-parameter-record.v1"


# ===========================================================================
# Section B: a synthetic but real-schema end-to-end candidate -- real
# training-parameter-record.v5/training-metrics.v5/analytical-
# visualizations.v5/inference_bundle.v1, produced by a real governed
# training run against a synthetic dataset (never a real UCI/Telco dataset).
# ===========================================================================


def _hgb_hyperparameters(**overrides) -> dict:
    base = {
        "class_weight": None,
        "l2_regularization": 0.0,
        "learning_rate": 0.1,
        "max_iter": 60,
        "max_leaf_nodes": 15,
        "min_samples_leaf": 5,
    }
    base.update(overrides)
    return base


def _fixed_binary_contract() -> dict:
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": DATASET_SLUG,
        "target_column": "outcome",
        "feature_columns": list(FEATURE_COLUMNS),
        "ignored_columns": ["record_ref"],
        "required_columns": list(FEATURE_COLUMNS),
        "optional_columns": [],
        "feature_definitions": {
            "input_a": {"type": "numeric"},
            "input_b": {"type": "numeric"},
        },
        "missing_value_policy": {},
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {"strategy": "stratified", "train_ratio": 0.6, "val_ratio": 0.2, "test_ratio": 0.2},
        "random_seed": 13,
        "primary_metric": "roc_auc",
        "secondary_metrics": ["f1", "accuracy", "log_loss", "pr_auc"],
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
            "positive_class": {"class_id": "yes", "event_label": "Responded"},
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


def _synthetic_binary_dataset(row_count: int = 200, seed: int = 0) -> dict:
    import random

    rng = random.Random(seed)
    rows = []
    for index in range(row_count):
        input_a = rng.uniform(0, 100)
        input_b = rng.uniform(0, 50)
        score = 0.05 * input_a - 0.03 * input_b + rng.uniform(-2, 2)
        label = "yes" if score > 2 else "no"
        rows.append({
            "dataset_id": DATASET_SLUG,
            "record_ref": f"row-{index:04d}",
            "input_a": round(input_a, 4),
            "input_b": round(input_b, 4),
            "outcome": label,
        })
    return {"dataset_id": DATASET_SLUG, "rows": rows}


@pytest.fixture(scope="module")
def _tmp_repo_root(tmp_path_factory):
    tmp_repo = tmp_path_factory.mktemp("binary_v5_native_repo")
    original_repo_root = training._repo_root
    training._repo_root = lambda: tmp_repo
    yield tmp_repo
    training._repo_root = original_repo_root


@pytest.fixture(scope="module")
def binary_v5_native_run(_tmp_repo_root):
    tmp_repo = _tmp_repo_root
    contract = _fixed_binary_contract()
    contract_path = tmp_repo / "contracts" / DATASET_SLUG / "execution-contract.json"
    _write_json(contract_path, contract)

    prepared_dataset_path = tmp_repo / "pipeline" / "prepared" / DATASET_SLUG / "prepared-data.json"
    _write_json(prepared_dataset_path, _synthetic_binary_dataset())

    result = training.train_from_paths(contract_path, prepared_dataset_path, dataset_slug=DATASET_SLUG)
    return {
        "tmp_repo": tmp_repo,
        "contract_path": contract_path,
        "prepared_dataset_path": prepared_dataset_path,
        "result": result,
    }


class TestNativeBinaryV5TrainingRun:
    def test_status_and_model_family(self, binary_v5_native_run):
        result = binary_v5_native_run["result"]
        assert result.status == "trained"
        assert result.model_family == "hist_gradient_boosting"

    def test_training_parameter_record_is_real_v5(self, binary_v5_native_run):
        tmp_repo = binary_v5_native_run["tmp_repo"]
        result = binary_v5_native_run["result"]
        record = json.loads((tmp_repo / result.training_parameter_record_path).read_text())
        assert record["schema_version"] == "training-parameter-record.v5"
        assert record["classification_evidence"]["positive_class_id"] == "yes"


@pytest.fixture(scope="module")
def binary_v5_native_bundle(binary_v5_native_run):
    tmp_repo = binary_v5_native_run["tmp_repo"]
    result = binary_v5_native_run["result"]

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
        "schema_version": "dataset-context.v1",
        "dataset_slug": DATASET_SLUG,
        "dataset_title": "Synthetic Binary V5 Fixture",
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
        execution_contract_path=binary_v5_native_run["contract_path"],
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_data_metadata_path=prepared_data_metadata_path,
        output_path=bundle_output_path,
        prediction_type="string",
        repo_root=tmp_repo,
        dataset_slug=DATASET_SLUG,
        class_labels=["no", "yes"],
        probability_output=True,
        execution_contract_ref=f"contracts/{DATASET_SLUG}/execution-contract.json",
        runtime_contract_ref=f"contracts/{DATASET_SLUG}/runtime-contract.json",
        public_contract_ref=f"contracts/{DATASET_SLUG}/public-contract.json",
        dataset_context_ref=f"contracts/{DATASET_SLUG}/dataset-context.json",
        inference_bundle_schema_path=str(REPO_ROOT / "contracts" / "inference-bundle.schema.json"),
        model_package_reference="models/model.pkl",
        release_id=provisional_release_id,
    )

    assert bundle_result["status"] == "generated", bundle_result

    return {
        **binary_v5_native_run,
        "bundle_result": bundle_result,
        "bundle_output_path": bundle_output_path,
        "release_id": provisional_release_id,
        "runtime_contract_path": runtime_contract_path,
        "public_contract_path": public_contract_path,
        "dataset_context_path": dataset_context_path,
        "prepared_data_metadata_path": prepared_data_metadata_path,
    }


def test_inference_bundle_is_real_valid_v1_sourced_from_v5(binary_v5_native_bundle):
    bundle = json.loads(binary_v5_native_bundle["bundle_output_path"].read_text())
    assert bundle["result_semantics"]["schema_version"] == "binary-result-semantics.v1"
    assert bundle["result_semantics"]["positive_class"] == {"class_id": "yes", "event_label": "Responded"}
    assert bundle["result_semantics"]["model_descriptor"]["model_family"] == "hist_gradient_boosting"


@pytest.fixture(scope="module")
def binary_v5_native_candidate(binary_v5_native_bundle):
    tmp_repo = binary_v5_native_bundle["tmp_repo"]
    result = binary_v5_native_bundle["result"]
    release_id = binary_v5_native_bundle["release_id"]

    discovery_evidence_path = tmp_repo / "pipeline" / "evidence" / DATASET_SLUG / "discovery-evidence.json"
    _write_json(discovery_evidence_path, {
        "schema_version": "discovery-evidence.v1",
        "dataset_metadata": {
            "name": DATASET_SLUG,
            "source_path": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.json",
        },
    })

    preparation_recipe_path = tmp_repo / "pipeline" / "authoring" / DATASET_SLUG / "preparation-recipe.json"
    _write_json(preparation_recipe_path, {
        "schema_version": "candidate-preparation-recipe.v1",
        "dataset_slug": DATASET_SLUG,
        "source_data_ref": f"pipeline/prepared/{DATASET_SLUG}/prepared-data.json",
        "ordered_input_columns": FEATURE_COLUMNS + ["outcome"],
        "transformations": [],
        "deterministic": True,
    })

    artifact_references = {
        "discovery_evidence": str(discovery_evidence_path.relative_to(tmp_repo)),
        "execution_contract": str(binary_v5_native_bundle["contract_path"].relative_to(tmp_repo)),
        "runtime_contract": str(binary_v5_native_bundle["runtime_contract_path"].relative_to(tmp_repo)),
        "public_contract": str(binary_v5_native_bundle["public_contract_path"].relative_to(tmp_repo)),
        "preparation_recipe": str(preparation_recipe_path.relative_to(tmp_repo)),
        "prepared_data_metadata": str(binary_v5_native_bundle["prepared_data_metadata_path"].relative_to(tmp_repo)),
        "training_parameter_record": result.training_parameter_record_path,
        "model_artifact": result.serialized_model_path,
        "training_metrics": result.metrics_path,
        "model_card": result.model_card_path,
        "public_context": str(binary_v5_native_bundle["dataset_context_path"].relative_to(tmp_repo)),
        "visualizations": result.analytical_visualizations_path,
        "inference_bundle": str(binary_v5_native_bundle["bundle_output_path"].relative_to(tmp_repo)),
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
        dataset_title="Synthetic Binary V5 Fixture",
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
        **binary_v5_native_bundle,
        "candidate_input": candidate_input,
        "assembly_result": assembly_result,
    }


class TestNativeBinaryV5CandidateAssemblyAndPublisher:
    def test_candidate_assembly_accepted(self, binary_v5_native_candidate):
        assembly_result = binary_v5_native_candidate["assembly_result"]
        assert assembly_result["status"] == "accepted", assembly_result

    def test_publisher_validate_accepts_candidate(self, binary_v5_native_candidate):
        candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
        result = publisher_validate.validate_candidate_file(candidate_dir)
        assert result["valid"] is True, result["rejection_reasons"]

    def test_release_candidate_carries_binary_result_semantics(self, binary_v5_native_candidate):
        candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
        predictive_bundle = json.loads((candidate_dir / "predictions" / "bundle.json").read_text())
        assert predictive_bundle["result_semantics"]["problem_type"] == "binary_classification"
        assert predictive_bundle["result_semantics"]["model_descriptor"]["model_family"] == (
            "hist_gradient_boosting"
        )


# ===========================================================================
# Section B2 (Project Spec S0263): generic collision-safe explicit
# release_id propagation. Reuses the real synthetic binary-v5 training run
# and the already-accepted -001 candidate from `binary_v5_native_candidate`
# (which reserves release-YYYYMMDD-001 for this run's real date) to force
# `pipeline.release_identity.allocate_release_id` to select -002, then
# proves the internal-training branch of
# `generate_inference_bundle.materialize_governed_inference_bundle` honors
# that explicit -002 identity exactly, through the bundle and into a fresh
# accepted candidate's own lineage. Nothing here is Telco-specific -- this
# reuses the same generic synthetic dataset/training fixtures as the rest
# of this module.
# ===========================================================================


@pytest.fixture(scope="module")
def binary_v5_collision_safe_bundle(binary_v5_native_candidate):
    from pipeline import release_identity

    tmp_repo = binary_v5_native_candidate["tmp_repo"]
    result = binary_v5_native_candidate["result"]
    run_id = Path(result.output_directory.rstrip("/")).name
    reserved_release_id = binary_v5_native_candidate["release_id"]
    assert reserved_release_id.endswith("-001")

    allocated_release_id = release_identity.allocate_release_id(run_id, tmp_repo)
    assert allocated_release_id == reserved_release_id[: -len("-001")] + "-002"

    runtime_contract_path = binary_v5_native_candidate["runtime_contract_path"]
    public_contract_path = binary_v5_native_candidate["public_contract_path"]
    dataset_context_path = binary_v5_native_candidate["dataset_context_path"]
    prepared_data_metadata_path = binary_v5_native_candidate["prepared_data_metadata_path"]

    training_run_materialization_result = {
        "artifact_type": "training_run_materialization_result",
        "contract_version": "training_run_materialization_result.v1",
        "status": "trained",
        "training_result": result.to_summary(),
    }

    bundle_output_path = (
        tmp_repo / "pipeline" / "inference-bundles" / DATASET_SLUG / "inference-bundle-collision-safe.json"
    )
    bundle_result = generate_inference_bundle.materialize_governed_inference_bundle(
        training_run_materialization_result=training_run_materialization_result,
        execution_contract_path=binary_v5_native_candidate["contract_path"],
        runtime_contract_path=runtime_contract_path,
        public_contract_path=public_contract_path,
        dataset_context_path=dataset_context_path,
        prepared_data_metadata_path=prepared_data_metadata_path,
        output_path=bundle_output_path,
        prediction_type="string",
        repo_root=tmp_repo,
        dataset_slug=DATASET_SLUG,
        class_labels=["no", "yes"],
        probability_output=True,
        execution_contract_ref=f"contracts/{DATASET_SLUG}/execution-contract.json",
        runtime_contract_ref=str(runtime_contract_path.relative_to(tmp_repo)),
        public_contract_ref=str(public_contract_path.relative_to(tmp_repo)),
        dataset_context_ref=str(dataset_context_path.relative_to(tmp_repo)),
        inference_bundle_schema_path=str(REPO_ROOT / "contracts" / "inference-bundle.schema.json"),
        model_package_reference="models/model.pkl",
        release_id=allocated_release_id,
    )
    assert bundle_result["status"] == "generated", bundle_result

    return {
        **binary_v5_native_candidate,
        "collision_safe_release_id": allocated_release_id,
        "collision_safe_bundle_result": bundle_result,
        "collision_safe_bundle_output_path": bundle_output_path,
    }


def test_explicit_collision_safe_release_id_honored_in_bundle(binary_v5_collision_safe_bundle):
    fixture = binary_v5_collision_safe_bundle
    allocated_release_id = fixture["collision_safe_release_id"]

    assert fixture["collision_safe_bundle_result"]["provisional_release_id"] == allocated_release_id
    bundle = json.loads(fixture["collision_safe_bundle_output_path"].read_text())
    assert bundle["release_context"]["release_id"] == allocated_release_id


def test_explicit_collision_safe_release_id_propagates_to_candidate_lineage(binary_v5_collision_safe_bundle):
    fixture = binary_v5_collision_safe_bundle
    tmp_repo = fixture["tmp_repo"]
    result = fixture["result"]
    allocated_release_id = fixture["collision_safe_release_id"]

    discovery_evidence_path = tmp_repo / "pipeline" / "evidence" / DATASET_SLUG / "discovery-evidence.json"
    preparation_recipe_path = tmp_repo / "pipeline" / "authoring" / DATASET_SLUG / "preparation-recipe.json"
    assert discovery_evidence_path.is_file()
    assert preparation_recipe_path.is_file()

    artifact_references = {
        "discovery_evidence": str(discovery_evidence_path.relative_to(tmp_repo)),
        "execution_contract": str(fixture["contract_path"].relative_to(tmp_repo)),
        "runtime_contract": str(fixture["runtime_contract_path"].relative_to(tmp_repo)),
        "public_contract": str(fixture["public_contract_path"].relative_to(tmp_repo)),
        "preparation_recipe": str(preparation_recipe_path.relative_to(tmp_repo)),
        "prepared_data_metadata": str(fixture["prepared_data_metadata_path"].relative_to(tmp_repo)),
        "training_parameter_record": result.training_parameter_record_path,
        "model_artifact": result.serialized_model_path,
        "training_metrics": result.metrics_path,
        "model_card": result.model_card_path,
        "public_context": str(fixture["dataset_context_path"].relative_to(tmp_repo)),
        "visualizations": result.analytical_visualizations_path,
        "inference_bundle": str(fixture["collision_safe_bundle_output_path"].relative_to(tmp_repo)),
    }

    candidate_input = assemble_candidate.build_release_candidate_input(
        dataset_slug=DATASET_SLUG,
        release_id=allocated_release_id,
        source_run_id=Path(result.output_directory.rstrip("/")).name,
        artifact_references=artifact_references,
        repo_root=tmp_repo,
        release_version="1.0.0-rc.2",
        dataset_title="Synthetic Binary V5 Fixture",
    )
    assert candidate_input["release_identity"]["release_id"] == allocated_release_id

    candidate_output_dir = tmp_repo / "releases" / "candidates"
    assembly_result = assemble_candidate.assemble_release_candidate(
        candidate_input, candidate_output_dir, repo_root=tmp_repo,
    )
    assert assembly_result["status"] == "accepted", assembly_result

    candidate_dir = Path(assembly_result["candidate_dir"])
    predictive_bundle = json.loads((candidate_dir / "predictions" / "bundle.json").read_text())
    assert predictive_bundle["release_context"]["release_id"] == allocated_release_id


# ===========================================================================
# Section C: publisher cross-artifact rejections -- mutated copies of the
# real, already-accepted v5 candidate directory (never a hand-fabricated
# schema-invalid document).
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


def test_metrics_positive_class_mismatch_rejected(binary_v5_native_candidate, tmp_path):
    candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-metrics-positive-class",
        relative_path="metrics/metrics.json",
        mutator=lambda data: data["classification_evidence"].__setitem__("positive_class_id", "no"),
    )

    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert result["valid"] is False
    assert "native_binary_v5_positive_class_mismatch" in _rejection_safe_details(result)


def test_visualizations_positive_class_mismatch_rejected(binary_v5_native_candidate, tmp_path):
    candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-visualizations-positive-class",
        relative_path="visualizations/visualizations.json",
        mutator=lambda data: data["classification_evidence"].__setitem__("positive_class_id", "no"),
    )

    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert result["valid"] is False
    assert "native_binary_v5_positive_class_mismatch" in _rejection_safe_details(result)


def test_visualizations_model_family_mismatch_rejected(binary_v5_native_candidate, tmp_path):
    candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-visualizations-model-family",
        relative_path="visualizations/visualizations.json",
        mutator=lambda data: data["feature_importance_method"].__setitem__(
            "model_family", "gradient_boosting"
        ),
    )

    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert result["valid"] is False
    assert "native_binary_v5_model_family_mismatch" in _rejection_safe_details(result)


def test_visualizations_feature_importance_method_mismatch_rejected(binary_v5_native_candidate, tmp_path):
    candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-visualizations-method",
        relative_path="visualizations/visualizations.json",
        mutator=lambda data: data["feature_importance_method"].__setitem__("method", "gradient_boosting"),
    )

    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert result["valid"] is False
    assert "native_binary_v5_feature_importance_method_mismatch" in _rejection_safe_details(result)


def test_legacy_v1_candidate_never_reaches_v5_compatibility_checks(binary_v5_native_candidate, tmp_path):
    """A v1-style metrics artifact (never declaring training-metrics.v5) must
    never trigger the v5 dispatch -- it is bounded to real v5 artifacts."""
    candidate_dir = Path(binary_v5_native_candidate["assembly_result"]["candidate_dir"])
    mutated_dir = _mutated_candidate_copy(
        candidate_dir,
        tmp_path / "mutated-metrics-schema-version",
        relative_path="metrics/metrics.json",
        mutator=lambda data: data.__setitem__("schema_version", "training-metrics.v1"),
    )

    result = publisher_validate.validate_candidate_file(mutated_dir)
    assert "native_binary_v5_positive_class_mismatch" not in _rejection_safe_details(result)
    assert "native_binary_v5_metrics_schema_version_missing" not in _rejection_safe_details(result)

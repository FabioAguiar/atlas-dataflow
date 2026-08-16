import hashlib
import json
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")
sklearn = pytest.importorskip("sklearn")
joblib = pytest.importorskip("joblib")

from sklearn.linear_model import LogisticRegression  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from pipeline.derive_external_analytical_visualization_evidence import (  # noqa: E402
    derive_external_analytical_visualization_evidence,
)

DATASET_SLUG = "derivation-test-dataset"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _counts(labels: list[str]) -> dict:
    return {"No": labels.count("No"), "Yes": labels.count("Yes")}


def _build_environment(
    tmp_path: Path,
    *,
    feature_order=("f1", "f2", "f3"),
    n_rows: int = 150,
    fit_model: bool = True,
    model_family: str = "logistic_regression",
    model_class_name: str = "LogisticRegression",
    target_labels=("No", "Yes"),
    target_encoding=None,
):
    repo_root = tmp_path / "repo"
    external_root = tmp_path / "external"
    repo_root.mkdir()
    external_root.mkdir()

    rng = np.random.RandomState(0)
    x_frame = pd.DataFrame({f: rng.rand(n_rows) for f in feature_order})
    y = (x_frame[feature_order[0]] > 0.5).astype(int)

    pipe = Pipeline([("clf", LogisticRegression())])
    if fit_model:
        pipe.fit(x_frame, y)

    negative_label, positive_label = target_labels
    validation_frame = x_frame.copy()
    validation_frame["Target"] = y.map({0: negative_label, 1: positive_label})
    validation_path = external_root / "validation.csv"
    validation_frame.to_csv(validation_path, index=False)
    validation_sha256 = _sha(validation_path)

    validation_labels = validation_frame["Target"].tolist()
    train_labels = [negative_label] * 60 + [positive_label] * 40
    test_labels = [negative_label] * 10 + [positive_label] * 10

    def label_counts(labels: list[str]) -> dict:
        return {negative_label: labels.count(negative_label), positive_label: labels.count(positive_label)}

    split_manifest = {
        "dataset_slug": DATASET_SLUG,
        "stratify_by": "Target",
        "partition_paths": {"train": "train.csv", "validation": "validation.csv", "test": "test.csv"},
        "partition_sha256": {"train": "a" * 64, "validation": validation_sha256, "test": "b" * 64},
        "row_counts": {
            "train": len(train_labels),
            "validation": len(validation_labels),
            "test": len(test_labels),
        },
        "class_counts": {
            "train": label_counts(train_labels),
            "validation": label_counts(validation_labels),
            "test": label_counts(test_labels),
        },
    }

    run_relative = f"pipeline/external-fitted-model-runs/{DATASET_SLUG}/run-1"
    model_relative = f"{run_relative}/model.bin"
    model_full = repo_root / model_relative
    model_full.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, model_full)
    model_sha256 = _sha(model_full)

    record_relative = f"{run_relative}/training-parameter-record.json"
    record_full = repo_root / record_relative
    record_full.write_text(json.dumps({"model_family": model_family}), encoding="utf-8")
    record_sha256 = _sha(record_full)

    materialization_result = {
        "status": "materialized",
        "model_source_mode": "validated_external_fitted_model",
        "dataset_identity": {"dataset_slug": DATASET_SLUG},
        "evidence_references": {"training_parameter_record_path": record_relative},
        "evidence_hashes": {"training_parameter_record_sha256": record_sha256},
        "model_artifact_path": model_relative,
        "model_artifact_sha256": model_sha256,
    }

    resolved_target_encoding = target_encoding or {negative_label: 0, positive_label: 1}
    final_model_manifest = {
        "dataset_slug": DATASET_SLUG,
        "selected_model_id": model_family,
        "selected_model_family": model_class_name,
        "feature_columns": list(feature_order),
        "target_column": "Target",
        "target_encoding": resolved_target_encoding,
        "runtime_versions": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
    }

    kwargs = dict(
        dataset_slug=DATASET_SLUG,
        external_root=external_root,
        split_manifest=split_manifest,
        split_manifest_reference="artifacts/preparation/derivation-test-dataset/split-manifest.json",
        split_manifest_sha256="c" * 64,
        final_model_manifest=final_model_manifest,
        final_model_manifest_reference="artifacts/models/derivation-test-dataset/final-model-manifest.json",
        final_model_manifest_sha256="d" * 64,
        materialization_result=materialization_result,
        output_derivation_evidence_path=f"{run_relative}/derived-analytical-visualization-evidence.json",
        repo_root=repo_root,
    )
    context = {
        "repo_root": repo_root,
        "external_root": external_root,
        "validation_path": validation_path,
        "model_full": model_full,
        "train_labels": train_labels,
        "validation_labels": validation_labels,
        "test_labels": test_labels,
        "negative_label": negative_label,
        "positive_label": positive_label,
    }
    return kwargs, context


# --- success path + target-distribution aggregation -------------------------


def test_derive_success_returns_derived_status_and_writes_evidence(tmp_path):
    kwargs, context = _build_environment(tmp_path)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    assert result["dataset_slug"] == DATASET_SLUG
    assert result["derivation_evidence_path"] == kwargs["output_derivation_evidence_path"]
    assert result["derivation_evidence_sha256"]

    output_full = context["repo_root"] / result["derivation_evidence_path"]
    assert output_full.is_file()
    assert _sha(output_full) == result["derivation_evidence_sha256"]


def test_target_distribution_is_aggregated_from_split_manifest_class_counts(tmp_path):
    kwargs, context = _build_environment(tmp_path)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    expected_totals = {}
    for labels in (context["train_labels"], context["validation_labels"], context["test_labels"]):
        for label in labels:
            expected_totals[label] = expected_totals.get(label, 0) + 1

    actual_totals = {row["name"]: row["value"] for row in result["target_distribution"]["counts"]}
    assert actual_totals == expected_totals
    assert result["target_distribution"]["target_column"] == "Target"
    assert result["target_distribution"]["source"] == kwargs["split_manifest_reference"]


def test_row_count_inconsistency_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["split_manifest"]["row_counts"]["train"] += 1

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "row_count_inconsistent"


def test_dataset_identity_mismatch_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["final_model_manifest"]["dataset_slug"] = "a-different-dataset"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


def test_split_manifest_dataset_identity_mismatch_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["split_manifest"]["dataset_slug"] = "a-different-dataset"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "dataset_identity_mismatch"


# --- Project Spec S0215: multiclass fallback derivation fails closed --------


def test_v2_materialization_result_blocks_before_any_further_processing(tmp_path):
    """A multiclass (v2) materialization result must block immediately --
    binary Average Precision permutation scoring is never attempted."""
    kwargs, _ = _build_environment(tmp_path)
    kwargs["materialization_result"]["schema_version"] = "external-fitted-model-materialization.v2"
    # Sabotage a later-stage field so a passing result could only mean the
    # v2 guard fired before that field was ever read.
    kwargs["final_model_manifest"]["target_column"] = "does-not-exist-column"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "multiclass_fallback_derivation_not_supported"


# --- validation-partition integrity ------------------------------------------


def test_validation_partition_path_traversal_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["split_manifest"]["partition_paths"]["validation"] = "../outside-external-root.csv"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "unsafe_path"


def test_validation_partition_hash_mismatch_blocks_before_pandas_read(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["split_manifest"]["partition_sha256"]["validation"] = "f" * 64

    def _fail_read_csv(*_args, **_kwargs):
        raise AssertionError("pandas.read_csv must not be called after a validation hash mismatch")

    monkeypatch.setattr(pd, "read_csv", _fail_read_csv)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "validation_hash_mismatch"


def test_no_test_or_train_partition_file_is_ever_opened(tmp_path):
    kwargs, context = _build_environment(tmp_path)
    # Only validation.csv exists beneath external_root -- train.csv/test.csv
    # are never created on disk. A successful derivation proves the module
    # never opened either, even though their row/class counts (already
    # in-memory JSON, not files) are read for target-distribution aggregation.
    assert not (context["external_root"] / "train.csv").exists()
    assert not (context["external_root"] / "test.csv").exists()

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result


def test_module_source_never_calls_fit_or_reads_test_partition_path():
    import pipeline.derive_external_analytical_visualization_evidence as module

    source_lines = Path(module.__file__).read_text(encoding="utf-8").splitlines()
    for forbidden in (".fit(", "fit_transform(", "partial_fit(", 'partition_paths.get("test")', 'partition_paths["test"]'):
        assert not any(
            forbidden in line and not line.strip().startswith("#") for line in source_lines
        ), forbidden


# --- model source / load-safe gate -------------------------------------------


def test_model_artifact_hash_mismatch_blocks_before_joblib_load(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["materialization_result"]["model_artifact_sha256"] = "e" * 64

    def _fail_load(*_args, **_kwargs):
        raise AssertionError("joblib.load must not be called after a model hash mismatch")

    monkeypatch.setattr(joblib, "load", _fail_load)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "referenced_evidence_hash_mismatch"


def test_runtime_incompatibility_blocks_before_joblib_load(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["final_model_manifest"]["runtime_versions"]["scikit_learn"] = "0.0.0-not-installed"

    def _fail_load(*_args, **_kwargs):
        raise AssertionError("joblib.load must not be called after a runtime incompatibility")

    monkeypatch.setattr(joblib, "load", _fail_load)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "runtime_incompatible"


def test_python_patch_only_difference_does_not_block(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    major, minor, patch = kwargs["final_model_manifest"]["runtime_versions"]["python"].split(".")
    kwargs["final_model_manifest"]["runtime_versions"]["python"] = f"{major}.{minor}.{int(patch) + 1}"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result


def test_inconsistent_version_warning_blocks(tmp_path, monkeypatch):
    kwargs, context = _build_environment(tmp_path)
    from sklearn.exceptions import InconsistentVersionWarning

    real_model = joblib.load(context["model_full"])

    def _warning_load(_path):
        import warnings

        warnings.warn(
            InconsistentVersionWarning(
                estimator_name="LogisticRegression",
                current_sklearn_version=sklearn.__version__,
                original_sklearn_version="0.0.0",
            )
        )
        return real_model

    monkeypatch.setattr(joblib, "load", _warning_load)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "inconsistent_version_warning_emitted"


def test_untrusted_non_pipeline_model_object_blocks(tmp_path):
    kwargs, context = _build_environment(tmp_path, fit_model=False)
    bare_estimator = LogisticRegression()
    joblib.dump(bare_estimator, context["model_full"])
    kwargs["materialization_result"]["model_artifact_sha256"] = _sha(context["model_full"])

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "untrusted_model_object"


def test_model_family_mismatch_after_load_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    kwargs["final_model_manifest"]["selected_model_family"] = "RandomForestClassifier"

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "model_family_mismatch_after_load"


# --- target encoding / feature order / permutation_importance call ----------


def test_target_encoding_is_governed_not_hardcoded_no_yes(tmp_path):
    kwargs, _ = _build_environment(tmp_path, target_labels=("negative", "positive"))

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    names = {row["name"] for row in result["target_distribution"]["counts"]}
    assert names == {"negative", "positive"}


def test_target_encoding_incomplete_for_validation_label_blocks(tmp_path):
    kwargs, _ = _build_environment(tmp_path)
    # Structurally valid (two entries) but does not cover the "Yes" label
    # that actually appears in the validation partition.
    kwargs["final_model_manifest"]["target_encoding"] = {"No": 0, "Maybe": 1}

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "target_encoding_incomplete"


def test_permutation_importance_called_with_exact_governed_parameters(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path, feature_order=("f1", "f2", "f3"))

    captured = {}

    def _spy_permutation_importance(estimator, x_arg, y_arg, **call_kwargs):
        captured["feature_columns"] = list(x_arg.columns)
        captured["y_values"] = list(y_arg)
        captured["kwargs"] = call_kwargs
        return types.SimpleNamespace(
            importances_mean=np.array([0.3, 0.2, 0.1]),
            importances_std=np.array([0.01, 0.01, 0.01]),
        )

    monkeypatch.setattr(sklearn.inspection, "permutation_importance", _spy_permutation_importance)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    assert captured["feature_columns"] == ["f1", "f2", "f3"]
    assert captured["kwargs"] == {
        "scoring": "average_precision",
        "n_repeats": 30,
        "random_state": 42,
        "n_jobs": 1,
    }
    assert set(captured["y_values"]) <= {0, 1}


# --- full/public feature-importance evidence shaping -------------------------


def test_full_signed_importance_preserved_and_public_rows_bounded_sorted_and_positive_only(tmp_path, monkeypatch):
    feature_order = tuple(f"f{i}" for i in range(1, 13))
    kwargs, _ = _build_environment(tmp_path, feature_order=feature_order)

    # Twelve features: ten strictly positive means (scrambled order), one
    # exactly zero, one negative -- exercises aggregation, sorting, the
    # ten-row public cap, and negative/non-positive omission all at once.
    means = [3.0, 12.0, -1.0, 7.0, 9.0, 0.0, 5.0, 11.0, 4.0, 10.0, 8.0, 6.0]
    stds = [0.05] * 12

    def _fake_permutation_importance(_estimator, _x, _y, **_kwargs):
        return types.SimpleNamespace(importances_mean=np.array(means), importances_std=np.array(stds))

    monkeypatch.setattr(sklearn.inspection, "permutation_importance", _fake_permutation_importance)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    public_rows = result["feature_importance"]["rows"]
    assert len(public_rows) == 10
    assert [row["value"] for row in public_rows] == sorted((v for v in means if v > 0), reverse=True)
    assert all(row["value"] > 0 for row in public_rows)
    assert result["feature_importance"]["total_source_feature_count"] == 12
    assert result["feature_importance"]["omitted_source_feature_count"] == 2

    output_full = kwargs["repo_root"] / result["derivation_evidence_path"]
    full_evidence = json.loads(output_full.read_text(encoding="utf-8"))
    full_signed = {entry["name"]: entry["mean"] for entry in full_evidence["feature_importance_evidence"]}
    assert full_signed == dict(zip(feature_order, means))
    # Negative and zero-mean features are absent from the bounded public
    # rows but remain present in the full signed evidence.
    public_names = {row["name"] for row in public_rows}
    assert "f3" not in public_names  # mean -1.0
    assert "f6" not in public_names  # mean 0.0
    assert "f3" in full_signed and "f6" in full_signed


def test_zero_positive_importance_rows_blocks(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path)

    def _fake_permutation_importance(_estimator, _x, _y, **_kwargs):
        return types.SimpleNamespace(
            importances_mean=np.array([0.0, -0.1, -0.2]), importances_std=np.array([0.01, 0.01, 0.01])
        )

    monkeypatch.setattr(sklearn.inspection, "permutation_importance", _fake_permutation_importance)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "zero_positive_importance_rows"


def test_non_finite_importance_blocks(tmp_path, monkeypatch):
    kwargs, _ = _build_environment(tmp_path)

    def _fake_permutation_importance(_estimator, _x, _y, **_kwargs):
        return types.SimpleNamespace(
            importances_mean=np.array([float("inf"), 0.1, 0.2]), importances_std=np.array([0.01, 0.01, 0.01])
        )

    monkeypatch.setattr(sklearn.inspection, "permutation_importance", _fake_permutation_importance)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    assert result["blocking_reasons"][0]["code"] == "non_finite_value"


# --- evidence artifact hygiene ------------------------------------------------


def test_output_never_contains_absolute_external_root(tmp_path):
    kwargs, context = _build_environment(tmp_path)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    output_full = context["repo_root"] / result["derivation_evidence_path"]
    artifact_text = output_full.read_text(encoding="utf-8")
    assert str(context["external_root"]) not in artifact_text


def test_output_never_contains_raw_rows_or_model_bytes(tmp_path):
    kwargs, context = _build_environment(tmp_path)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    output_full = context["repo_root"] / result["derivation_evidence_path"]
    artifact = json.loads(output_full.read_text(encoding="utf-8"))
    forbidden_keys = {"raw_validation_rows", "raw_transformed_matrix", "serialized_estimator_state", "model_bytes"}
    assert forbidden_keys.isdisjoint(artifact.keys())
    assert forbidden_keys.isdisjoint(artifact["method_details"].keys())


def test_output_written_only_after_all_checks_pass(tmp_path):
    kwargs, context = _build_environment(tmp_path)
    kwargs["split_manifest"]["partition_sha256"]["validation"] = "f" * 64

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "blocked", result
    output_full = context["repo_root"] / kwargs["output_derivation_evidence_path"]
    assert not output_full.exists()


def test_derivation_evidence_sha256_matches_written_bytes(tmp_path):
    kwargs, context = _build_environment(tmp_path)

    result = derive_external_analytical_visualization_evidence(**kwargs)

    assert result["status"] == "derived", result
    output_full = context["repo_root"] / result["derivation_evidence_path"]
    assert _sha(output_full) == result["derivation_evidence_sha256"]

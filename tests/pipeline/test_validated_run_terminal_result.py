"""
Tests for Project Spec S0181: Deferred External Fitted-Model Materialization
and Validated-Run Artifact Completion Contract (validated-run terminal-result
producer half).

Uses only temporary/synthetic durable artifacts -- never notebook state,
runtime services, the registry, or an external project directory.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline import validated_run  # noqa: E402
from pipeline.validated_run import (  # noqa: E402
    materialize_validated_run_terminal_result as materialize_terminal,
)

REPO_ROOT = Path(__file__).parent.parent.parent
TERMINAL_SCHEMA_PATH = REPO_ROOT / "pipeline" / "validated-run-terminal-result.schema.json"

DATASET_SLUG = "sample-binary-classification-dataset"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_artifact(repo_root: Path, relative_path: str, content: bytes) -> dict:
    path = repo_root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return {"path": relative_path, "sha256": _sha256_bytes(content)}


def _isolated_repo_root(tmp_path: Path) -> Path:
    repo_root = tmp_path / "repo-root"
    pipeline_dir = repo_root / "pipeline"
    pipeline_dir.mkdir(parents=True)
    src = REPO_ROOT / "pipeline" / "validated-run-terminal-result.schema.json"
    (pipeline_dir / "validated-run-terminal-result.schema.json").write_bytes(src.read_bytes())
    return repo_root


def _full_durable_references(repo_root: Path) -> dict:
    return {
        "materialization_result": _write_artifact(repo_root, "governed/materialization-result.json", b"materialization-fixture-1"),
        "inference_bundle": _write_artifact(repo_root, "governed/inference-bundle.json", b"inference-bundle-fixture-1"),
        "release_candidate": _write_artifact(repo_root, "governed/release-candidate.json", b"release-candidate-fixture-1"),
        "publisher_validation_result": _write_artifact(repo_root, "governed/validation-result.json", b"validation-result-fixture-1"),
        "manifest": _write_artifact(repo_root, "governed/manifest.json", b"manifest-fixture-1"),
        "operational_readiness_source": _write_artifact(repo_root, "governed/operational-readiness.json", b"operational-readiness-fixture-1"),
    }


def _resolved_external_readiness() -> dict:
    return {
        "operational_validity": "confirmed",
        "operational_threshold": {"status": "resolved", "value": 0.5},
        "operational_prediction_available": True,
    }


def _fail_closed_external_readiness() -> dict:
    return {
        "operational_validity": "unconfirmed",
        "operational_threshold": {"status": "unresolved", "value": None},
        "operational_prediction_available": False,
    }


def _validate_schema(instance: dict) -> None:
    schema = json.loads(TERMINAL_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(instance)


# --- completed, internal-compatible ------------------------------------------


def test_completed_internal_training_result_is_schema_valid_and_promotion_true(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0001",
        dataset_slug=DATASET_SLUG,
        model_source_mode="atlas_internal_training",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": "governed/manifest.json"},
        operational_readiness={
            "operational_validity": "not_applicable",
            "operational_threshold": {"status": "not_applicable", "value": None},
            "operational_prediction_available": False,
        },
        repo_root=repo_root,
    )
    assert result["status"] == "completed"
    assert result["promotion_eligibility"] is True
    assert result["reasons"] == []
    _validate_schema(result)


# --- completed, external, promotion false by default -------------------------


def test_completed_external_result_with_unresolved_readiness_has_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0002",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": "governed/manifest.json"},
        operational_readiness=_fail_closed_external_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "completed"
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


@pytest.mark.parametrize(
    "readiness_override",
    [
        {"operational_validity": "unconfirmed"},
        {"operational_threshold": {"status": "unresolved", "value": None}},
        {"operational_prediction_available": False},
    ],
)
def test_each_individual_unmet_readiness_condition_keeps_promotion_false(
    tmp_path: Path, readiness_override: dict
) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    readiness = _resolved_external_readiness()
    readiness.update(readiness_override)
    result = materialize_terminal(
        run_id="run-0003",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=readiness,
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_rejected_structural_validation_keeps_promotion_false_even_with_full_readiness(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0004",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "rejected"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    assert result["structural_validation"]["validation_outcome"] == "rejected"
    _validate_schema(result)


def test_fully_resolved_external_readiness_with_accepted_structural_validation_is_promotable(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0005",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": "governed/manifest.json"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is True
    _validate_schema(result)


def test_no_structural_validation_checked_keeps_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0006",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation=None,
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["structural_validation"] is None
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


# --- hash mismatch / missing reference behavior -------------------------------


def test_durable_reference_hash_mismatch_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    references = _full_durable_references(repo_root)
    references["inference_bundle"]["sha256"] = "0" * 64

    result = materialize_terminal(
        run_id="run-0007",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=references,
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["promotion_eligibility"] is False
    assert result["reasons"][0]["code"] == "durable_reference_hash_mismatch"
    _validate_schema(result)


def test_durable_reference_missing_file_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    references = _full_durable_references(repo_root)
    references["manifest"] = {"path": "governed/does-not-exist.json", "sha256": "0" * 64}

    result = materialize_terminal(
        run_id="run-0008",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=references,
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["reasons"][0]["code"] == "durable_reference_missing"
    _validate_schema(result)


def test_missing_required_reference_field_blocks(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    references = _full_durable_references(repo_root)
    del references["inference_bundle"]["sha256"]

    result = materialize_terminal(
        run_id="run-0009",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=references,
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["reasons"][0]["code"] == "invalid_hash"
    _validate_schema(result)


def test_omitted_durable_reference_role_is_allowed_as_applicable(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    references = _full_durable_references(repo_root)
    references["manifest"] = None
    result = materialize_terminal(
        run_id="run-0010",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=references,
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome=None,
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "completed"
    assert result["durable_references"]["manifest"] is None
    assert result["manifest_outcome"] is None
    _validate_schema(result)


# --- blocked / failed statuses carry explicit reasons -------------------------


def test_blocked_status_requires_and_carries_explicit_reasons(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0011",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="blocked",
        durable_references=_full_durable_references(repo_root),
        operational_readiness=_fail_closed_external_readiness(),
        reasons=[{"code": "operational_policy_review_pending", "message": "Awaiting operational policy review."}],
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["reasons"] == [
        {"code": "operational_policy_review_pending", "message": "Awaiting operational policy review."}
    ]
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_failed_status_requires_and_carries_explicit_reasons(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0012",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="failed",
        durable_references=_full_durable_references(repo_root),
        operational_readiness=_fail_closed_external_readiness(),
        reasons=[{"code": "manifest_generation_failed", "message": "Manifest artifact hash could not be verified."}],
        repo_root=repo_root,
    )
    assert result["status"] == "failed"
    assert result["reasons"][0]["code"] == "manifest_generation_failed"
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_non_completed_status_without_reasons_blocks_deterministically(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0013",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="failed",
        durable_references=_full_durable_references(repo_root),
        operational_readiness=_fail_closed_external_readiness(),
        reasons=[],
        repo_root=repo_root,
    )
    # Caller-declared status is overridden to "blocked" with a concrete,
    # stable reason when required evidence (non-empty reasons) is missing.
    assert result["status"] == "blocked"
    assert result["reasons"]
    _validate_schema(result)


# --- manifest presence / absence representation -------------------------------


def test_manifest_absent_representation(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    references = _full_durable_references(repo_root)
    references["manifest"] = None
    result = materialize_terminal(
        run_id="run-0014",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=references,
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome=None,
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["manifest_outcome"] is None
    _validate_schema(result)


def test_manifest_present_representation(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0015",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": "governed/manifest.json"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["manifest_outcome"] == {
        "manifest_generated": True,
        "manifest_path": "governed/manifest.json",
    }
    _validate_schema(result)


# --- no promotion / no registry mutation --------------------------------------


def test_never_calls_publisher_promote_or_writes_registry_state() -> None:
    # Code-only check (docstrings legitimately describe this boundary in
    # prose): strip every triple-quoted docstring block before scanning, so
    # this only catches an actual import/call, not the module's own
    # documentation of the guarantee it upholds.
    source_lines = inspect.getsource(validated_run).splitlines()
    code_lines: list[str] = []
    in_docstring = False
    for line in source_lines:
        if '"""' in line:
            occurrences = line.count('"""')
            if occurrences % 2 == 1:
                in_docstring = not in_docstring
            continue
        if not in_docstring:
            code_lines.append(line)
    code_only_source = "\n".join(code_lines)

    forbidden_substrings = (
        "import publisher",
        "from publisher",
        "publisher.promote",
        "promote.run",
        "import registry",
        "from registry",
        "registry_store",
        "write_text(",
        "write_bytes(",
    )
    for substring in forbidden_substrings:
        assert substring not in code_only_source, f"forbidden call/import found: {substring}"


# --- Project Spec S0208: strict argmax operational readiness ----------------


def _resolved_argmax_readiness() -> dict:
    return {
        "operational_validity": "confirmed",
        "decision_strategy": "argmax",
        "operational_prediction_available": True,
    }


def _fail_closed_argmax_readiness() -> dict:
    return {
        "operational_validity": "unconfirmed",
        "decision_strategy": "argmax",
        "operational_prediction_available": False,
    }


def test_external_accepted_structure_confirmed_argmax_readiness_prediction_available_promotes(
    tmp_path: Path,
) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0017",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        manifest_outcome={"manifest_generated": True, "manifest_path": "governed/manifest.json"},
        operational_readiness=_resolved_argmax_readiness(),
        repo_root=repo_root,
    )
    assert result["status"] == "completed"
    assert result["promotion_eligibility"] is True
    assert result["operational_readiness"]["decision_strategy"] == "argmax"
    assert "operational_threshold" not in result["operational_readiness"]
    _validate_schema(result)


def test_argmax_unconfirmed_validity_keeps_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    readiness = _resolved_argmax_readiness()
    readiness["operational_validity"] = "unconfirmed"
    result = materialize_terminal(
        run_id="run-0018",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=readiness,
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_argmax_prediction_unavailable_keeps_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    readiness = _resolved_argmax_readiness()
    readiness["operational_prediction_available"] = False
    result = materialize_terminal(
        run_id="run-0019",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=readiness,
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_argmax_rejected_structural_validation_keeps_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0020",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "rejected"},
        operational_readiness=_resolved_argmax_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_argmax_no_structural_validation_checked_keeps_promotion_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0021",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation=None,
        operational_readiness=_resolved_argmax_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_argmax_readiness_containing_operational_threshold_is_rejected(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    readiness = _resolved_argmax_readiness()
    readiness["operational_threshold"] = {"status": "resolved", "value": 0.5}
    result = materialize_terminal(
        run_id="run-0022",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=readiness,
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["promotion_eligibility"] is False
    assert result["reasons"][0]["code"] == "malformed_operational_readiness"
    _validate_schema(result)


def test_unknown_decision_strategy_is_rejected(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    readiness = _resolved_argmax_readiness()
    readiness["decision_strategy"] = "weighted_vote"
    result = materialize_terminal(
        run_id="run-0023",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=readiness,
        repo_root=repo_root,
    )
    assert result["status"] == "blocked"
    assert result["promotion_eligibility"] is False
    assert result["reasons"][0]["code"] == "unknown_decision_strategy"
    _validate_schema(result)


def test_legacy_threshold_external_readiness_remains_promotable_only_with_resolved_threshold(
    tmp_path: Path,
) -> None:
    """Continuity anchor: the legacy threshold-oriented branch (no
    decision_strategy key at all) is unaffected by the Project Spec S0208
    argmax addition -- mirrors
    test_fully_resolved_external_readiness_with_accepted_structural_validation_is_promotable."""
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0024",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is True
    assert "decision_strategy" not in result["operational_readiness"]
    _validate_schema(result)


def test_legacy_unresolved_threshold_remains_non_promotable(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0025",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_fail_closed_external_readiness(),
        repo_root=repo_root,
    )
    assert result["promotion_eligibility"] is False
    _validate_schema(result)


def test_internal_training_not_applicable_readiness_remains_unchanged(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0026",
        dataset_slug=DATASET_SLUG,
        model_source_mode="atlas_internal_training",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness={
            "operational_validity": "not_applicable",
            "operational_threshold": {"status": "not_applicable", "value": None},
            "operational_prediction_available": False,
        },
        repo_root=repo_root,
    )
    assert result["status"] == "completed"
    assert result["promotion_eligibility"] is True
    _validate_schema(result)


def test_schema_validates_both_legacy_and_argmax_readiness_variants(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    legacy_result = materialize_terminal(
        run_id="run-0027",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    argmax_result = materialize_terminal(
        run_id="run-0028",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_argmax_readiness(),
        repo_root=repo_root,
    )
    _validate_schema(legacy_result)
    _validate_schema(argmax_result)


def test_boundary_confirmations_always_false(tmp_path: Path) -> None:
    repo_root = _isolated_repo_root(tmp_path)
    result = materialize_terminal(
        run_id="run-0016",
        dataset_slug=DATASET_SLUG,
        model_source_mode="validated_external_fitted_model",
        status="completed",
        durable_references=_full_durable_references(repo_root),
        structural_validation={"validation_outcome": "accepted"},
        operational_readiness=_resolved_external_readiness(),
        repo_root=repo_root,
    )
    assert all(value is False for value in result["boundary_confirmations"].values())

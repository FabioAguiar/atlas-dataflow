"""
Project Spec S0284: focused tests for the reduced release-bound
prediction-target projection.

Covers:
  * api/public_model_card_loader.py's new load_public_prediction_target()
    reduced technical reader (governed model-card.v1 identity, bounded
    nonblank target name, supported problem type, no raw model-card leak,
    path-traversal protection, and non-interference with the raw
    load_public_model_card() response);
  * api/main.py's _project_prediction_target_safely() coherence guard
    (result-contract availability + exact problem-type match, no coarse
    legacy alias widening);
  * the public GET /datasets/{slug}/contract envelope and the Admin
    GET /admin/datasets/{slug}/authoring-context contract resource both
    carrying the same target_contract, with target unavailability never
    degrading the technical contract resource;
  * GET /datasets/{slug}/model-card staying byte-shape compatible.

All release/manifest inputs are synthetic temporary fixtures. No real
release, registry, notebook, training, or publisher artifact is touched.
"""

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO_ROOT = Path(__file__).parent.parent.parent
API_ROOT = REPO_ROOT / "api"
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(API_ROOT))

import main as api_main  # noqa: E402
import public_model_card_loader  # noqa: E402
from public_model_card_loader import (  # noqa: E402
    PublicPredictionTargetUnavailableError,
    load_public_model_card,
    load_public_prediction_target,
)


# ---------------------------------------------------------------------------
# Synthetic release fixture helpers
# ---------------------------------------------------------------------------

_BINARY_MODEL_CARD = {
    "schema_version": "model-card.v1",
    "artifact_kind": "model_card",
    "problem_type": "binary_classification",
    "prediction_target": "Churn",
    # Deliberately noisy: none of this may appear in the reduced projection.
    "hashes": {"model": "deadbeef"},
    "path_references": {"model": "models/model.joblib"},
    "evaluation": {"metrics": [{"name": "roc_auc", "value": 0.84}]},
    "model_summary": {"family": "gradient_boosting"},
    "training_run_identity": {"run_id": "train-xyz"},
}

_MULTICLASS_MODEL_CARD = {
    "schema_version": "model-card.v1",
    "artifact_kind": "model_card",
    "problem_type": "multiclass_classification",
    "prediction_target": "Class",
}

_REGRESSION_MODEL_CARD = {
    "schema_version": "model-card.v1",
    "artifact_kind": "model_card",
    "problem_type": "continuous_regression",
    "prediction_target": "Concrete compressive strength",
}

# Mirrors the current active nottem forecasting release: role-identified,
# no artifact_kind key.
_FORECASTING_MODEL_CARD = {
    "schema_version": "model-card.v1",
    "role": "model_card",
    "problem_type": "univariate_forecasting",
    "prediction_target": "temperature",
}


def _write_release(root: Path, release_id: str, *, model_card_ref="model-card.json",
                   model_card_body=None, declare_model_card_role=True,
                   raw_model_card_text=None) -> str:
    release_dir = root / release_id
    (release_dir).mkdir(parents=True, exist_ok=True)

    artifacts = []
    if declare_model_card_role:
        artifacts.append({"role": "model_card", "reference": model_card_ref})
    (release_dir / "manifest.json").write_text(
        json.dumps({"artifacts": artifacts}), encoding="utf-8"
    )

    target_path = release_dir / model_card_ref
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if raw_model_card_text is not None:
        target_path.write_text(raw_model_card_text, encoding="utf-8")
    elif model_card_body is not None:
        target_path.write_text(json.dumps(model_card_body), encoding="utf-8")
    return release_id


# ---------------------------------------------------------------------------
# load_public_prediction_target: valid reductions
# ---------------------------------------------------------------------------

def test_valid_binary_model_card_reduces_to_problem_type_and_target_name_only():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-bin-001", model_card_body=_BINARY_MODEL_CARD)

        reduced = load_public_prediction_target("release-bin-001", releases_root=root)

    assert reduced == {"problem_type": "binary_classification", "target_name": "Churn"}
    assert set(reduced.keys()) == {"problem_type", "target_name"}


def test_valid_multiclass_model_card_reduces_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-mc-001", model_card_body=_MULTICLASS_MODEL_CARD)
        reduced = load_public_prediction_target("release-mc-001", releases_root=root)
    assert reduced == {"problem_type": "multiclass_classification", "target_name": "Class"}


def test_valid_continuous_regression_model_card_reduces_correctly():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-reg-001", model_card_body=_REGRESSION_MODEL_CARD)
        reduced = load_public_prediction_target("release-reg-001", releases_root=root)
    assert reduced == {
        "problem_type": "continuous_regression",
        "target_name": "Concrete compressive strength",
    }


def test_valid_forecasting_model_card_reduces_correctly_via_role_identity():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-fc-001", model_card_body=_FORECASTING_MODEL_CARD)
        reduced = load_public_prediction_target("release-fc-001", releases_root=root)
    assert reduced == {"problem_type": "univariate_forecasting", "target_name": "temperature"}


def test_reduced_reader_never_returns_raw_model_card_fields():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-bin-002", model_card_body=_BINARY_MODEL_CARD)
        reduced = load_public_prediction_target("release-bin-002", releases_root=root)

    serialized = json.dumps(reduced)
    for leaked in ("hashes", "deadbeef", "path_references", "models/model.joblib",
                   "evaluation", "roc_auc", "model_summary", "training_run_identity",
                   "train-xyz"):
        assert leaked not in serialized


def test_leading_trailing_whitespace_is_trimmed_but_internal_identity_is_preserved():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card = {**_REGRESSION_MODEL_CARD, "prediction_target": "  Concrete compressive strength  "}
        _write_release(root, "release-reg-002", model_card_body=card)
        reduced = load_public_prediction_target("release-reg-002", releases_root=root)
    assert reduced["target_name"] == "Concrete compressive strength"


# ---------------------------------------------------------------------------
# load_public_prediction_target: rejection paths (fail closed)
# ---------------------------------------------------------------------------

def _assert_target_unavailable(release_id, root):
    try:
        load_public_prediction_target(release_id, releases_root=root)
    except PublicPredictionTargetUnavailableError:
        return
    raise AssertionError("expected PublicPredictionTargetUnavailableError")


def test_missing_model_card_role_yields_target_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-nomc-001", declare_model_card_role=False)
        _assert_target_unavailable("release-nomc-001", root)


def test_non_json_model_card_yields_target_unavailable_without_breaking_raw_loader():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-bad-001", raw_model_card_text="# Not JSON\n\nHuman copy.")

        _assert_target_unavailable("release-bad-001", root)

        raw = load_public_model_card("release-bad-001", releases_root=root)
        assert raw == {"content": "# Not JSON\n\nHuman copy.", "format": "markdown"}


def test_wrong_schema_version_yields_target_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card = {**_BINARY_MODEL_CARD, "schema_version": "model-card.v2"}
        _write_release(root, "release-ver-001", model_card_body=card)
        _assert_target_unavailable("release-ver-001", root)


def test_wrong_artifact_kind_yields_target_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card = {**_BINARY_MODEL_CARD, "artifact_kind": "training_metrics"}
        _write_release(root, "release-kind-001", model_card_body=card)
        _assert_target_unavailable("release-kind-001", root)


def test_blank_target_yields_target_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i, blank in enumerate(("", "   ", "\t\n")):
            card = {**_BINARY_MODEL_CARD, "prediction_target": blank}
            rid = f"release-blank-{i:03d}"
            _write_release(root, rid, model_card_body=card)
            _assert_target_unavailable(rid, root)


def test_non_string_target_yields_target_unavailable():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card = {**_BINARY_MODEL_CARD, "prediction_target": 42}
        _write_release(root, "release-nonstr-001", model_card_body=card)
        _assert_target_unavailable("release-nonstr-001", root)


def test_unreasonably_large_target_is_rejected_not_truncated():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        card = {**_BINARY_MODEL_CARD, "prediction_target": "T" * 5000}
        _write_release(root, "release-big-001", model_card_body=card)
        _assert_target_unavailable("release-big-001", root)


def test_unsupported_or_coarse_legacy_problem_type_fails_closed():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for i, coarse in enumerate(("classification", "regression", "forecasting",
                                    "clustering", "")):
            card = {**_BINARY_MODEL_CARD, "problem_type": coarse}
            rid = f"release-coarse-{i:03d}"
            _write_release(root, rid, model_card_body=card)
            _assert_target_unavailable(rid, root)


def test_model_card_reference_escaping_release_dir_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        outside = root / "outside-secret.json"
        outside.write_text(json.dumps(_BINARY_MODEL_CARD), encoding="utf-8")
        _write_release(
            root, "release-trav-001",
            model_card_ref="../outside-secret.json",
            declare_model_card_role=True,
        )
        # manifest declares the traversing reference; no in-dir card written.
        _assert_target_unavailable("release-trav-001", root)


def test_raw_public_model_card_response_is_unchanged_for_a_valid_release():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _write_release(root, "release-raw-001", model_card_body=_BINARY_MODEL_CARD)
        raw = load_public_model_card("release-raw-001", releases_root=root)
    assert set(raw.keys()) == {"content", "format"}
    assert raw["format"] == "markdown"
    assert json.loads(raw["content"]) == _BINARY_MODEL_CARD


# ---------------------------------------------------------------------------
# _project_prediction_target_safely: coherence guard
# ---------------------------------------------------------------------------

def _available_result_contract(problem_type):
    return {"status": "available", "semantics": {"problem_type": problem_type}}


def test_project_prediction_target_safely_available_on_coherent_match(monkeypatch):
    monkeypatch.setattr(
        api_main, "load_public_prediction_target",
        lambda _release: {"problem_type": "multiclass_classification", "target_name": "Class"},
    )
    projected = api_main._project_prediction_target_safely(
        "release-x", _available_result_contract("multiclass_classification")
    )
    assert projected == {
        "status": "available",
        "problem_type": "multiclass_classification",
        "target_name": "Class",
    }


def test_project_prediction_target_safely_unavailable_when_result_contract_unavailable(monkeypatch):
    monkeypatch.setattr(
        api_main, "load_public_prediction_target",
        lambda _release: {"problem_type": "binary_classification", "target_name": "Churn"},
    )
    projected = api_main._project_prediction_target_safely(
        "release-x", {"status": "unavailable", "reason": "binary_result_semantics_unavailable"}
    )
    assert projected == {"status": "unavailable", "reason": "prediction_target_unavailable"}


def test_project_prediction_target_safely_unavailable_on_problem_type_mismatch(monkeypatch):
    monkeypatch.setattr(
        api_main, "load_public_prediction_target",
        lambda _release: {"problem_type": "multiclass_classification", "target_name": "Class"},
    )
    projected = api_main._project_prediction_target_safely(
        "release-x", _available_result_contract("continuous_regression")
    )
    assert projected == {"status": "unavailable", "reason": "prediction_target_unavailable"}


def test_project_prediction_target_safely_unavailable_when_reader_raises(monkeypatch):
    def _raise(_release):
        raise PublicPredictionTargetUnavailableError("nope")

    monkeypatch.setattr(api_main, "load_public_prediction_target", _raise)
    projected = api_main._project_prediction_target_safely(
        "release-x", _available_result_contract("binary_classification")
    )
    assert projected == {"status": "unavailable", "reason": "prediction_target_unavailable"}


def test_project_prediction_target_safely_never_widens_a_coarse_result_problem_type(monkeypatch):
    monkeypatch.setattr(
        api_main, "load_public_prediction_target",
        lambda _release: {"problem_type": "binary_classification", "target_name": "Churn"},
    )
    projected = api_main._project_prediction_target_safely(
        "release-x", _available_result_contract("classification")
    )
    assert projected == {"status": "unavailable", "reason": "prediction_target_unavailable"}


# ---------------------------------------------------------------------------
# Contract envelope parity (public /contract + Admin authoring-context)
# ---------------------------------------------------------------------------

_FIXTURE_SLUG = "fixture-s0284-dataset"
_FIXTURE_RELEASE = "release-s0284-001"


def _install_common_contract_env(monkeypatch, *, target_reader, result_contract):
    monkeypatch.setattr(
        api_main, "_resolve_public_dataset_detail_access",
        lambda _slug: SimpleNamespace(dataset_slug=_FIXTURE_SLUG, active_release=_FIXTURE_RELEASE),
    )
    monkeypatch.setattr(
        api_main, "resolve_dataset",
        lambda _slug: SimpleNamespace(dataset_slug=_FIXTURE_SLUG, active_release=_FIXTURE_RELEASE),
    )
    monkeypatch.setattr(api_main, "load_public_contract", lambda _release: {"features": [{"name": "a"}]})
    monkeypatch.setattr(api_main, "_project_result_contract_safely", lambda _release: result_contract)
    monkeypatch.setattr(api_main, "load_public_prediction_target", target_reader)
    # Admin authoring-context extra dependencies.
    monkeypatch.setattr(api_main, "load_public_context", lambda _release: {"problem_type": "binary_classification"})
    monkeypatch.setattr(api_main, "load_public_metrics", lambda _release: {"accuracy": 0.9})
    monkeypatch.setattr(api_main, "load_public_visualizations", lambda _release: {"charts": []})
    monkeypatch.setattr(api_main, "load_public_predict_view_list", lambda _slug: [])
    monkeypatch.setattr(api_main, "load_contract", lambda _release: {"schema_version": "atlas.dataflow.runtime_contract.v1"})
    monkeypatch.setattr(api_main, "_project_admin_authoring_dataset_identity", lambda _slug: {"dataset_slug": _FIXTURE_SLUG})


def _authoring_request():
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET",
                    "path": f"/admin/datasets/{_FIXTURE_SLUG}/authoring-context", "headers": []})


def test_public_contract_envelope_contains_target_contract(monkeypatch):
    _install_common_contract_env(
        monkeypatch,
        target_reader=lambda _release: {"problem_type": "binary_classification", "target_name": "Churn"},
        result_contract=_available_result_contract("binary_classification"),
    )
    response = api_main.get_public_contract(_FIXTURE_SLUG)
    assert set(response.keys()) == {"dataset_slug", "contract", "result_contract", "target_contract"}
    assert response["target_contract"] == {
        "status": "available",
        "problem_type": "binary_classification",
        "target_name": "Churn",
    }


def test_admin_authoring_context_contract_resource_contains_same_target_contract(monkeypatch):
    _install_common_contract_env(
        monkeypatch,
        target_reader=lambda _release: {"problem_type": "binary_classification", "target_name": "Churn"},
        result_contract=_available_result_contract("binary_classification"),
    )
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        response = api_main.get_admin_dataset_authoring_context(_FIXTURE_SLUG, _authoring_request())
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    contract_resource = response["contract"]
    assert contract_resource["status"] == "ready"
    assert set(contract_resource["data"].keys()) == {"contract", "result_contract", "target_contract"}
    assert contract_resource["data"]["target_contract"] == {
        "status": "available",
        "problem_type": "binary_classification",
        "target_name": "Churn",
    }


def test_target_failure_does_not_make_public_contract_unavailable(monkeypatch):
    def _raise(_release):
        raise PublicPredictionTargetUnavailableError("nope")

    _install_common_contract_env(
        monkeypatch,
        target_reader=_raise,
        result_contract=_available_result_contract("binary_classification"),
    )
    response = api_main.get_public_contract(_FIXTURE_SLUG)
    assert response["contract"] == {"features": [{"name": "a"}]}
    assert response["result_contract"]["status"] == "available"
    assert response["target_contract"] == {"status": "unavailable", "reason": "prediction_target_unavailable"}


def test_target_failure_does_not_make_admin_contract_resource_unavailable(monkeypatch):
    def _raise(_release):
        raise PublicPredictionTargetUnavailableError("nope")

    _install_common_contract_env(
        monkeypatch,
        target_reader=_raise,
        result_contract=_available_result_contract("binary_classification"),
    )
    os.environ["ATLAS_ADMIN_ENABLED"] = "true"
    try:
        response = api_main.get_admin_dataset_authoring_context(_FIXTURE_SLUG, _authoring_request())
    finally:
        os.environ.pop("ATLAS_ADMIN_ENABLED", None)

    contract_resource = response["contract"]
    assert contract_resource["status"] == "ready"
    assert contract_resource["data"]["contract"] == {"features": [{"name": "a"}]}
    assert contract_resource["data"]["result_contract"]["status"] == "available"
    assert contract_resource["data"]["target_contract"] == {
        "status": "unavailable",
        "reason": "prediction_target_unavailable",
    }


def test_target_contract_never_leaks_raw_model_card_technical_fields(monkeypatch):
    _install_common_contract_env(
        monkeypatch,
        target_reader=lambda _release: {"problem_type": "binary_classification", "target_name": "Churn"},
        result_contract=_available_result_contract("binary_classification"),
    )
    response = api_main.get_public_contract(_FIXTURE_SLUG)
    serialized = json.dumps(response["target_contract"])
    for leaked in ("hashes", "path_references", "evaluation", "model_summary",
                   "provenance", "training_run_identity"):
        assert leaked not in serialized


# ---------------------------------------------------------------------------
# GET /datasets/{slug}/model-card stays byte-shape compatible
# ---------------------------------------------------------------------------

def test_public_model_card_route_shape_unchanged_and_carries_no_target_metadata(monkeypatch):
    monkeypatch.setattr(
        api_main, "_resolve_public_dataset_detail_access",
        lambda _slug: SimpleNamespace(dataset_slug=_FIXTURE_SLUG, active_release=_FIXTURE_RELEASE),
    )
    monkeypatch.setattr(
        api_main, "load_public_model_card",
        lambda _release: {"content": "raw model card markdown", "format": "markdown"},
    )
    response = api_main.get_public_model_card(_FIXTURE_SLUG)
    assert response == {
        "dataset_slug": _FIXTURE_SLUG,
        "model_card": {"content": "raw model card markdown", "format": "markdown"},
    }
    assert "target_contract" not in response
    assert "prediction_target" not in json.dumps(response)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))

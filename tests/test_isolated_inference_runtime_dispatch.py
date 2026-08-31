"""Project Spec S0285: retirement / backward-compatibility regression for
runtime execution topology.

Originally an S0171 regression that imported the isolated
``external-inference`` service runtime and asserted the API could dispatch
to it. S0285 retired the isolated service, its HTTP client, and its
contracts. This file keeps its historical name (regression lineage) but no
longer imports any deleted module. It now proves:

* legacy inference_bundle.v1 bundles that omit ``execution_strategy`` still
  resolve to in-process;
* an explicit ``in_process`` resolves to the main runtime;
* ``isolated_service`` does not dispatch -- it fails closed deterministically;
* ``api/main.py`` carries no ``external_inference_client`` dependency and no
  external-service delegation helper;
* the historical ``isolated_service`` schema vocabulary, retained for
  versioned compatibility, is annotated legacy/deprecated and does not imply
  operational support.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).parents[1]
INFERENCE_BUNDLE_SCHEMA_PATH = ROOT / "contracts" / "inference-bundle.schema.json"
API_MAIN_PATH = ROOT / "api" / "main.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def main_module():
    sys.path.insert(0, str(ROOT / "api"))
    return _load_module("s0285_api_main", API_MAIN_PATH)


_BASE_RUNTIME_EXECUTION = {
    "serialization_format": "joblib",
    "loader_strategy": "joblib_sklearn_predict",
    "prediction_interface": "predict",
    "model_family": "gradient_boosting",
}


def test_legacy_v1_omission_resolves_to_in_process(main_module):
    strategy, profile, runtime_execution = main_module._resolve_runtime_dispatch(
        {"runtime_execution": {"loader_strategy": "joblib_sklearn_predict"}}
    )
    assert strategy == "in_process"
    assert profile is None
    assert "execution_strategy" not in runtime_execution


def test_explicit_in_process_resolves_to_main_runtime(main_module):
    strategy, profile, _ = main_module._resolve_runtime_dispatch(
        {"runtime_execution": {**_BASE_RUNTIME_EXECUTION, "execution_strategy": "in_process"}}
    )
    assert strategy == "in_process"
    assert profile is None


def test_isolated_service_does_not_dispatch_and_fails_closed_deterministically(main_module):
    declaration = {
        "model_artifact": {"sha256": "a" * 64},
        "runtime_execution": {
            **_BASE_RUNTIME_EXECUTION,
            "execution_strategy": "isolated_service",
            "runtime_profile": {"service_dispatch": {"service_id": "external-inference"}},
        },
    }
    categories = set()
    for _ in range(3):
        with pytest.raises(main_module.RuntimeDispatchError) as raised:
            main_module._resolve_runtime_dispatch(declaration)
        categories.add(raised.value.category)
        assert raised.value.diagnostic_code == "INFERENCE_BUNDLE_UNAVAILABLE"
    assert categories == {"unsupported_execution_strategy"}


def test_any_other_alternate_strategy_also_fails_closed(main_module):
    with pytest.raises(main_module.RuntimeDispatchError) as raised:
        main_module._resolve_runtime_dispatch(
            {"runtime_execution": {**_BASE_RUNTIME_EXECUTION, "execution_strategy": "remote_worker"}}
        )
    assert raised.value.category == "unsupported_execution_strategy"


def test_missing_runtime_execution_metadata_is_typed(main_module):
    with pytest.raises(main_module.RuntimeDispatchError) as raised:
        main_module._resolve_runtime_dispatch({})
    assert raised.value.category == "runtime_profile_invalid"


def test_api_main_has_no_external_inference_client_dependency():
    source = API_MAIN_PATH.read_text(encoding="utf-8")
    assert "external_inference_client" not in source
    assert "execute_external_inference" not in source
    assert "_execute_via_external_inference_service" not in source
    assert "8100" not in source


def test_deleted_service_modules_are_absent_from_the_repository():
    for relative in (
        "api/external_inference_client.py",
        "external-inference/service_app.py",
        "external-inference/runtime_loader.py",
        "external-inference/Dockerfile",
        "external-inference/pyproject.toml",
        "external-inference/contracts/external-inference-request.schema.json",
        "external-inference/contracts/external-inference-result.schema.json",
    ):
        assert not (ROOT / relative).exists(), relative


def test_schema_still_validates_historical_v1_omission_and_marks_isolated_service_legacy():
    schema = json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    validator = jsonschema.Draft202012Validator(schema)

    # A minimal inference_bundle.v1 document that omits execution_strategy
    # must still be structurally valid against the current schema.
    for release_id in (
        "release-20260818-002",
        "release-20260820-001",
        "release-20260830-001",
    ):
        bundle = json.loads(
            (ROOT / "releases" / release_id / "predictions" / "bundle.json").read_text(encoding="utf-8")
        )
        assert bundle.get("runtime_execution", {}).get("execution_strategy") is None
        assert list(validator.iter_errors(bundle)) == []

    # The isolated_service vocabulary is retained (S0285 does not pretend it
    # never existed) but its annotations mark it legacy / not operationally
    # supported.
    runtime_execution_schema = schema["$defs"]["inference_bundle_v1"]["properties"]["runtime_execution"]
    execution_strategy_schema = runtime_execution_schema["properties"]["execution_strategy"]
    assert "isolated_service" in execution_strategy_schema["enum"]
    description = execution_strategy_schema["description"].lower()
    assert "historical" in description or "legacy" in description
    assert "s0285" in description
    profile_description = schema["$defs"]["isolated_runtime_profile"]["description"].lower()
    assert "legacy" in profile_description or "deprecated" in profile_description


def test_schema_validity_of_isolated_service_alone_does_not_imply_dispatch(main_module):
    # A document can be schema-shaped with isolated_service, yet the API
    # runtime still refuses to dispatch it.
    schema = json.loads(INFERENCE_BUNDLE_SCHEMA_PATH.read_text(encoding="utf-8"))
    runtime_execution_schema = schema["$defs"]["inference_bundle_v1"]["properties"]["runtime_execution"]
    resolver = jsonschema.RefResolver.from_schema(schema)
    profile = {
        "profile_id": "sklearn-joblib-exact",
        "profile_version": "v1",
        "producer_runtime": {
            "python_major_minor": "3.11",
            "dependencies": {"joblib": "1", "pandas": "2", "scikit_learn": "1.5"},
        },
        "required_consumer_runtime": {
            "python_major_minor": "3.11",
            "dependencies": {"joblib": "1", "pandas": "2", "scikit_learn": "1.5"},
        },
        "compatibility_policy": "exact",
        "artifact_format": "joblib",
        "loader_family": "joblib_sklearn_predict",
        "trusted_source_required": True,
        "artifact_integrity": {"model_sha256": "a" * 64},
        "load_safe": True,
        "service_dispatch": {
            "service_id": "external-inference",
            "request_contract_version": "external_inference_request.v1",
        },
    }
    runtime_execution = {
        **_BASE_RUNTIME_EXECUTION,
        "execution_strategy": "isolated_service",
        "runtime_profile": profile,
    }
    jsonschema.validate(runtime_execution, runtime_execution_schema, resolver=resolver)

    with pytest.raises(main_module.RuntimeDispatchError):
        main_module._resolve_runtime_dispatch(
            {"model_artifact": {"sha256": "a" * 64}, "runtime_execution": runtime_execution}
        )

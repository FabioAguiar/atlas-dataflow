from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).parents[1]


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime_profile(**overrides):
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
    profile.update(overrides)
    return profile


@pytest.fixture(scope="module")
def main_module():
    sys.path.insert(0, str(ROOT / "api"))
    return _load_module("s0171_api_main", ROOT / "api" / "main.py")


@pytest.fixture(scope="module")
def loader_module():
    return _load_module("s0171_runtime_loader", ROOT / "external-inference" / "runtime_loader.py")


def test_schema_is_valid_and_accepts_both_dispatch_strategies():
    schema = json.loads((ROOT / "contracts" / "inference-bundle.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    runtime_schema = schema["properties"]["runtime_execution"]
    resolver = jsonschema.RefResolver.from_schema(schema)
    base = {
        "serialization_format": "joblib",
        "loader_strategy": "joblib_sklearn_predict",
        "prediction_interface": "predict",
        "model_family": "gradient_boosting",
    }
    jsonschema.validate({**base, "execution_strategy": "in_process"}, runtime_schema, resolver=resolver)
    jsonschema.validate(
        {**base, "execution_strategy": "isolated_service", "runtime_profile": _runtime_profile()},
        runtime_schema,
        resolver=resolver,
    )


def test_historical_runtime_metadata_defaults_to_in_process(main_module):
    strategy, profile, _ = main_module._resolve_runtime_dispatch(
        {"runtime_execution": {"loader_strategy": "joblib_sklearn_predict"}}
    )
    assert strategy == "in_process"
    assert profile is None


def test_governed_isolated_dispatch_does_not_need_release_manifest_policy(main_module):
    declaration = {
        "model_artifact": {"sha256": "a" * 64},
        "runtime_execution": {"execution_strategy": "isolated_service", "runtime_profile": _runtime_profile()},
    }
    strategy, profile, _ = main_module._resolve_runtime_dispatch(declaration)
    assert strategy == "isolated_service"
    assert profile["profile_id"] == "sklearn-joblib-exact"


@pytest.mark.parametrize(
    ("runtime_execution", "category"),
    [
        ({"execution_strategy": "other"}, "unsupported_execution_strategy"),
        ({"execution_strategy": "isolated_service"}, "runtime_profile_invalid"),
        ({"execution_strategy": "isolated_service", "runtime_profile": {}}, "runtime_profile_invalid"),
    ],
)
def test_dispatch_failures_are_typed(main_module, runtime_execution, category):
    with pytest.raises(main_module.RuntimeDispatchError) as raised:
        main_module._resolve_runtime_dispatch({"runtime_execution": runtime_execution})
    assert raised.value.category == category


def test_runtime_profile_mismatch_is_typed(main_module):
    profile = _runtime_profile()
    profile["producer_runtime"] = {**profile["producer_runtime"], "python_major_minor": "3.10"}
    with pytest.raises(main_module.RuntimeDispatchError) as raised:
        main_module._resolve_runtime_dispatch(
            {
                "model_artifact": {"sha256": "a" * 64},
                "runtime_execution": {"execution_strategy": "isolated_service", "runtime_profile": profile},
            }
        )
    assert raised.value.category == "runtime_profile_mismatch"


@pytest.mark.parametrize(
    ("change", "category"),
    [
        ({"trusted_source_required": False}, "untrusted_artifact"),
        ({"artifact_integrity": {"model_sha256": "b" * 64}}, "artifact_integrity_mismatch"),
        ({"load_safe": False}, "load_not_safe"),
    ],
)
def test_profile_trust_integrity_and_load_safe_fail_before_deserialization(loader_module, change, category):
    manifest = {
        "trusted_source": {"kind": "governed"},
        "model_artifact": {"byte_sha256": "a" * 64},
    }
    profile = _runtime_profile(**change)
    with pytest.raises(loader_module.LoadSafeGateError) as raised:
        loader_module.validate_governed_runtime_profile(profile, manifest)
    assert raised.value.category == category


def test_exact_runtime_mismatch_is_rejected(loader_module):
    result = loader_module.evaluate_load_safe_compatibility(
        request=None,
        manifest_bundle_identity={},
        expected_runtime={"python_major_minor": "3.11", "joblib": "1", "pandas": "2", "scikit_learn": "1.5"},
        observed_runtime={"python_major_minor": "3.11", "joblib": "1", "pandas": "2", "scikit_learn": "1.6"},
    )
    assert result["status"] == "incompatible"


def test_generic_client_and_loader_have_no_dataset_specific_identity():
    sources = [
        (ROOT / "api" / "external_inference_client.py").read_text(),
        (ROOT / "external-inference" / "runtime_loader.py").read_text(),
    ]
    forbidden = ("telco-customer-churn", "BUNDLE_DIRECTORY_NAME", "External Telco")
    for source in sources:
        assert all(value not in source for value in forbidden)

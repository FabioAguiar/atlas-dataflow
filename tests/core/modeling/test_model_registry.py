from __future__ import annotations

import pytest

from atlas_dataflow.modeling.model_registry import ModelRegistry, ModelSpec, ParamSpec


def test_registry_v1_contains_expected_models():
    reg = ModelRegistry.v1()
    assert reg.list_ids() == ["knn", "logistic_regression", "random_forest"]


def test_registry_get_returns_models_with_defaults_and_ui_params():
    reg = ModelRegistry.v1()
    spec = reg.get("logistic_regression")

    assert isinstance(spec, ModelSpec)
    assert spec.estimator_cls is not None
    assert isinstance(spec.default_params, dict)
    assert len(spec.default_params) > 0

    assert isinstance(spec.ui_params, dict)
    assert "C" in spec.ui_params
    assert isinstance(spec.ui_params["C"], ParamSpec)


def test_registry_build_instantiates_estimator_without_training():
    reg = ModelRegistry.v1()
    est = reg.build("knn")
    # should have sklearn-like get_params
    params = est.get_params()
    assert "n_neighbors" in params


def test_invalid_model_id_raises_explicit_error():
    reg = ModelRegistry.v1()
    with pytest.raises(KeyError):
        reg.get("does_not_exist")


def test_registry_is_explicitly_extensible_via_register():
    reg = ModelRegistry.v1()

    custom = ModelSpec(
        model_id="dummy_custom",
        estimator_cls=dict,  # simple placeholder class for test; should be callable
        default_params={"x": 1},
        ui_params={"x": ParamSpec(dtype="int", default=1, min=0, max=10)},
    )

    reg.register(custom)
    assert "dummy_custom" in reg.list_ids()
    spec = reg.get("dummy_custom")
    assert spec.default_params["x"] == 1

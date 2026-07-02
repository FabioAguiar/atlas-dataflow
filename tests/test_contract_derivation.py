import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.contract_derivation import (
    _check_safety,
    _derive_public_contract,
    _derive_public_feature,
    _derive_public_options,
    _fresh_label,
)


def _categorical_feature(values=("admin", "blue-collar", "technician"), **overrides):
    feature = {
        "name": "job",
        "type": "categorical",
        "required": True,
        "description": "Type of job held by the client.",
        "domain_constraints": {"values": list(values)},
    }
    feature.update(overrides)
    return feature


def test_categorical_feature_with_values_produces_safe_options() -> None:
    feature = _categorical_feature(values=("admin", "blue-collar", "technician"))
    public = _derive_public_feature(feature, display_order=1)
    assert public["options"] == [
        {"value": "admin", "label": _fresh_label("admin")},
        {"value": "blue-collar", "label": _fresh_label("blue-collar")},
        {"value": "technician", "label": _fresh_label("technician")},
    ]


def test_options_preserve_source_declaration_order() -> None:
    feature = _categorical_feature(values=("zeta", "alpha", "mu"))
    public = _derive_public_feature(feature, display_order=1)
    assert [option["value"] for option in public["options"]] == ["zeta", "alpha", "mu"]


def test_options_entries_carry_only_value_and_label_keys() -> None:
    feature = _categorical_feature()
    public = _derive_public_feature(feature, display_order=1)
    for option in public["options"]:
        assert set(option.keys()) == {"value", "label"}


def test_categorical_feature_without_domain_constraints_has_no_options_key() -> None:
    feature = _categorical_feature()
    del feature["domain_constraints"]
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_categorical_feature_with_empty_values_has_no_options_key() -> None:
    feature = _categorical_feature(values=())
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_numeric_feature_never_has_options_key() -> None:
    feature = {
        "name": "age",
        "type": "numeric",
        "required": True,
        "domain_constraints": {"min": 18, "max": 95},
    }
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_boolean_feature_never_has_options_key() -> None:
    feature = {"name": "employed", "type": "boolean", "required": False}
    public = _derive_public_feature(feature, display_order=1)
    assert "options" not in public


def test_derive_public_options_returns_none_for_non_categorical_feature() -> None:
    feature = {"name": "age", "type": "numeric", "domain_constraints": {"min": 0, "max": 1}}
    assert _derive_public_options(feature) is None


def test_derived_contract_with_options_passes_safety_check() -> None:
    runtime_contract = {
        "schema_version": "1.0.0",
        "features": [
            {"name": "age", "type": "numeric", "required": True, "domain_constraints": {"min": 17, "max": 98}},
            _categorical_feature(),
            {"name": "employed", "type": "boolean", "required": False},
        ],
    }
    public_contract = _derive_public_contract(runtime_contract)
    assert _check_safety(public_contract) == []
    job_feature = next(f for f in public_contract["features"] if f["name"] == "job")
    assert job_feature["options"]
    age_feature = next(f for f in public_contract["features"] if f["name"] == "age")
    assert "options" not in age_feature

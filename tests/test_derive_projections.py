import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.derive_projections import DerivationFailed, derive

REPO_ROOT = Path(__file__).parent.parent


def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _valid_contract(
    feature_columns: list | None = None,
    feature_definitions: dict | None = None,
    required_columns: list | None = None,
    optional_columns: list | None = None,
    ignored_columns: list | None = None,
) -> dict:
    """Minimal valid execution contract conforming to execution_contract.v1."""
    if feature_columns is None:
        feature_columns = ["age", "job", "loan"]
    if feature_definitions is None:
        feature_definitions = {
            "age": {"type": "numeric", "domain_constraints": {"min": 18, "max": 95}},
            "job": {"type": "categorical", "domain_constraints": {"values": ["admin", "blue-collar", "technician"]}},
            "loan": {"type": "boolean"},
        }
    if required_columns is None:
        required_columns = ["age", "job", "loan"]
    if optional_columns is None:
        optional_columns = []
    if ignored_columns is None:
        ignored_columns = []
    missing_value_policy = {
        col: "median"
        if feature_definitions.get(col, {}).get("type") == "numeric"
        else "mode"
        for col in feature_columns
    }
    val_ratio = 0.15
    return {
        "contract_version": "execution_contract.v1",
        "dataset_id": "bank-marketing",
        "target_column": "y",
        "feature_columns": feature_columns,
        "ignored_columns": ignored_columns,
        "required_columns": required_columns,
        "optional_columns": optional_columns,
        "feature_definitions": feature_definitions,
        "missing_value_policy": missing_value_policy,
        "categorical_encoding_policy": "onehot",
        "numeric_handling": "standardize",
        "allowed_transformations": ["passthrough"],
        "split_policy": {
            "strategy": "stratified",
            "train_ratio": 0.7,
            "val_ratio": val_ratio,
            "test_ratio": val_ratio,
        },
        "random_seed": None,
        "primary_metric": "roc_auc",
        "secondary_metrics": [],
        "modeling_constraints": {
            "allowed_model_families": ["logistic_regression", "gradient_boosting"],
            "no_automl": True,
            "max_training_time_seconds": None,
        },
    }


def test_valid_contract_produces_runtime_and_public(tmp_path):
    """A valid execution contract produces both runtime-contract.json and public-contract.json."""
    contract_path = _write_json(tmp_path, "contract.json", _valid_contract())
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    assert (out_dir / "runtime-contract.json").exists()
    assert (out_dir / "public-contract.json").exists()
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    public = json.loads((out_dir / "public-contract.json").read_text())
    assert runtime["schema_version"] == "1.0.0"
    assert len(runtime["features"]) == 3
    assert public["schema_version"] == "1.0.0"
    assert len(public["features"]) == 3


def test_runtime_projection_has_no_interface_hints(tmp_path):
    """Runtime contract features must not contain label, input_type, display_order, or optional."""
    contract_path = _write_json(tmp_path, "contract.json", _valid_contract())
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    forbidden = {"label", "input_type", "display_order", "optional"}
    for feature in runtime["features"]:
        leaked = forbidden & set(feature.keys())
        assert not leaked, f"Runtime feature '{feature['name']}' contains interface hints: {leaked}"


def test_public_projection_excludes_ignored_columns(tmp_path):
    """Public contract must not contain any feature whose name comes from ignored_columns."""
    contract = _valid_contract(
        feature_columns=["age", "job"],
        feature_definitions={
            "age": {"type": "numeric"},
            "job": {"type": "categorical", "domain_constraints": {"values": ["admin"]}},
        },
        required_columns=["age", "job"],
        ignored_columns=["duration"],
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    public = json.loads((out_dir / "public-contract.json").read_text())
    public_names = {f["name"] for f in public["features"]}
    assert "duration" not in public_names


def test_missing_feature_definition_raises(tmp_path):
    """A feature_column with no feature_definitions entry raises DerivationFailed with an informative message."""
    contract = _valid_contract(
        feature_columns=["age", "unknown_col"],
        feature_definitions={"age": {"type": "numeric"}},
        required_columns=["age"],
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    with pytest.raises(DerivationFailed) as exc_info:
        derive(contract_path, out_dir, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("unknown_col" in e for e in errors)
    assert any("feature_definitions" in e for e in errors)


def test_optional_column_produces_required_false_and_optional_true(tmp_path):
    """An optional_column must produce required=False in runtime and optional=True in public."""
    contract = _valid_contract(
        feature_columns=["age", "job"],
        feature_definitions={
            "age": {"type": "numeric"},
            "job": {"type": "categorical", "domain_constraints": {"values": ["admin"]}},
        },
        required_columns=["age"],
        optional_columns=["job"],
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    public = json.loads((out_dir / "public-contract.json").read_text())
    runtime_by_name = {f["name"]: f for f in runtime["features"]}
    public_by_name = {f["name"]: f for f in public["features"]}
    assert runtime_by_name["job"].get("required") is False
    assert public_by_name["job"].get("optional") is True


def test_invalid_execution_contract_schema_raises(tmp_path):
    """An execution contract missing required fields raises DerivationFailed before projection."""
    invalid = {"contract_version": "execution_contract.v1"}
    contract_path = _write_json(tmp_path, "contract.json", invalid)
    out_dir = tmp_path / "out"
    with pytest.raises(DerivationFailed) as exc_info:
        derive(contract_path, out_dir, repo_root=REPO_ROOT)
    errors = exc_info.value.errors
    assert any("execution contract schema validation failed" in e for e in errors)


def test_domain_constraints_carried_verbatim(tmp_path):
    """domain_constraints from feature_definitions are CARRIED verbatim into the runtime contract."""
    numeric_dc = {"min": 18, "max": 95}
    categorical_dc = {"values": ["admin", "technician"]}
    contract = _valid_contract(
        feature_columns=["age", "job"],
        feature_definitions={
            "age": {"type": "numeric", "domain_constraints": numeric_dc},
            "job": {"type": "categorical", "domain_constraints": categorical_dc},
        },
        required_columns=["age", "job"],
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    by_name = {f["name"]: f for f in runtime["features"]}
    assert by_name["age"]["domain_constraints"] == numeric_dc
    assert by_name["job"]["domain_constraints"] == categorical_dc


def test_boolean_feature_has_no_domain_constraints(tmp_path):
    """A boolean feature without domain_constraints in feature_definitions must not have that key in runtime."""
    contract = _valid_contract(
        feature_columns=["loan"],
        feature_definitions={"loan": {"type": "boolean"}},
        required_columns=["loan"],
    )
    contract_path = _write_json(tmp_path, "contract.json", contract)
    out_dir = tmp_path / "out"
    derive(contract_path, out_dir, repo_root=REPO_ROOT)
    runtime = json.loads((out_dir / "runtime-contract.json").read_text())
    loan_feature = runtime["features"][0]
    assert "domain_constraints" not in loan_feature


def test_derivation_is_deterministic(tmp_path):
    """The same execution contract always produces identical runtime and public contract outputs."""
    contract_path = _write_json(tmp_path, "contract.json", _valid_contract())
    out_dir_a = tmp_path / "out_a"
    out_dir_b = tmp_path / "out_b"
    derive(contract_path, out_dir_a, repo_root=REPO_ROOT)
    derive(contract_path, out_dir_b, repo_root=REPO_ROOT)
    for filename in ("runtime-contract.json", "public-contract.json"):
        a = json.loads((out_dir_a / filename).read_text())
        b = json.loads((out_dir_b / filename).read_text())
        assert a == b, f"{filename}: outputs from two derive() calls are not identical"

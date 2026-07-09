import json
import sys
from pathlib import Path

import jsonschema
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline.derive_projections import DerivationFailed, derive
from pipeline.contract_derivation import _derive_public_contract
from pipeline.assemble_candidate import build_release_candidate_handoff_readiness

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


# ---------------------------------------------------------------------------
# Real seeded dataset options re-derivation: M32-05
#
# The published releases/*/contracts/public-contract.json artifacts for both
# currently seeded datasets predate the M32-01 options projection and do not
# carry an "options" key on any select-type feature, even though both real
# runtime-contract.json files declare non-empty domain_constraints.values for
# those same features. Per the M32-05 implementation handoff, releases/ is an
# immutable published package and must not be edited or regenerated by this
# issue. This test validates, in memory only, that re-deriving the public
# contract today from each real seeded dataset's real runtime contract via
# pipeline.contract_derivation._derive_public_contract produces a correct
# options array for every categorical feature with a non-empty
# domain_constraints.values list. It does not read, assert against, write to,
# or otherwise touch any releases/*/contracts/public-contract.json file.
# ---------------------------------------------------------------------------

_REAL_SEEDED_RELEASE_CONTRACT_DIRS = [
    REPO_ROOT / "releases" / "release-20260619-001" / "contracts",
    REPO_ROOT / "releases" / "release-20260620-002" / "contracts",
]


def test_real_seeded_dataset_runtime_contracts_project_safe_select_options():
    """
    Re-derives the public contract in memory (no write, no publish, no
    modification of any releases/ file) from both currently seeded datasets'
    real runtime-contract.json files and confirms every categorical feature
    with a non-empty domain_constraints.values list receives an options array
    whose entries carry only value/label keys, with values matching
    domain_constraints.values verbatim in source order.

    Also documents, by reading (not modifying) each dataset's currently
    published public-contract.json, that the published release artifact
    predates this projection and does not yet carry options for the same
    select-type features -- so this test's re-derivation proves the
    projection is correct today without implying the live API response
    already reflects it.
    """
    for contracts_dir in _REAL_SEEDED_RELEASE_CONTRACT_DIRS:
        runtime_contract = json.loads(
            (contracts_dir / "runtime-contract.json").read_text(encoding="utf-8")
        )
        published_public_contract = json.loads(
            (contracts_dir / "public-contract.json").read_text(encoding="utf-8")
        )
        published_by_name = {f["name"]: f for f in published_public_contract["features"]}

        rederived_public_contract = _derive_public_contract(runtime_contract)
        rederived_by_name = {f["name"]: f for f in rederived_public_contract["features"]}

        categorical_features_with_values = [
            feature
            for feature in runtime_contract["features"]
            if feature.get("type") == "categorical"
            and feature.get("domain_constraints", {}).get("values")
        ]
        assert categorical_features_with_values, (
            f"expected at least one real categorical feature with domain_constraints.values "
            f"in {contracts_dir / 'runtime-contract.json'}"
        )

        for feature in categorical_features_with_values:
            expected_values = feature["domain_constraints"]["values"]

            rederived_feature = rederived_by_name[feature["name"]]
            assert "options" in rederived_feature, (
                f"feature '{feature['name']}' has real domain_constraints.values "
                "but re-deriving today via _derive_public_contract produced no options key"
            )
            options = rederived_feature["options"]
            assert [option["value"] for option in options] == expected_values
            for option in options:
                assert set(option.keys()) == {"value", "label"}

            published_feature = published_by_name.get(feature["name"])
            if published_feature is not None:
                assert "options" not in published_feature, (
                    f"published {contracts_dir / 'public-contract.json'} unexpectedly "
                    f"already carries options for '{feature['name']}'; if this now "
                    "fails, the release has been regenerated and M32-05's evidence "
                    "about published-artifact staleness should be revisited"
                )


# ---------------------------------------------------------------------------
# Telco runtime/public contract projection: Project Spec S0025
#
# The Telco execution contract (contracts/telco-customer-churn/execution-contract.json)
# was materialized by Project Spec S0024. This section proves the existing,
# dataset-agnostic derive() pipeline correctly projects it into
# contracts/telco-customer-churn/runtime-contract.json and public-contract.json,
# and that the release-candidate handoff readiness gate recognizes both roles
# as ready once those two artifacts exist and validate. Skip-guarded, per the
# S0024 precedent, so the suite still passes before the Telco execution
# contract exists on disk.
# ---------------------------------------------------------------------------

TELCO_EXECUTION_CONTRACT_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "execution-contract.json"
TELCO_RUNTIME_CONTRACT_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "runtime-contract.json"
TELCO_PUBLIC_CONTRACT_PATH = REPO_ROOT / "contracts" / "telco-customer-churn" / "public-contract.json"
RUNTIME_SCHEMA_PATH = REPO_ROOT / "contracts" / "runtime-contract.schema.json"
PUBLIC_SCHEMA_PATH = REPO_ROOT / "contracts" / "public-contract.schema.json"


@pytest.mark.skipif(
    not TELCO_EXECUTION_CONTRACT_PATH.exists(),
    reason="Telco execution contract not yet materialized on disk",
)
def test_real_telco_execution_contract_projects_to_valid_runtime_and_public_contracts(tmp_path):
    """Projecting the real, on-disk Telco execution contract (a tmp output dir,
    so this test never mutates the repository) produces a runtime contract and
    a public contract that both validate against their schemas, exclude
    customerID, include/exclude TotalCharges consistently with the execution
    contract's own current review status, and preserve SeniorCitizen's
    boolean/binary-indicator semantics."""
    recipe = json.loads(
        (
            REPO_ROOT / "pipeline" / "evidence" / "telco-customer-churn" / "preparation-recipe.json"
        ).read_text(encoding="utf-8")
    )
    total_charges_review_status = next(
        t["review_status"]
        for t in recipe["transformations"]
        if t["transformation_type"] == "missing_value_handling"
        and "TotalCharges" in t["target_columns"]
    )
    total_charges_approved = total_charges_review_status in ("explicit", "inferred_approved")

    out_dir = tmp_path / "telco-out"
    derive(TELCO_EXECUTION_CONTRACT_PATH, out_dir, repo_root=REPO_ROOT)

    runtime = json.loads((out_dir / "runtime-contract.json").read_text(encoding="utf-8"))
    public = json.loads((out_dir / "public-contract.json").read_text(encoding="utf-8"))

    jsonschema.validate(runtime, json.loads(RUNTIME_SCHEMA_PATH.read_text(encoding="utf-8")))
    jsonschema.validate(public, json.loads(PUBLIC_SCHEMA_PATH.read_text(encoding="utf-8")))

    runtime_names = {f["name"] for f in runtime["features"]}
    public_names = {f["name"] for f in public["features"]}
    assert "customerID" not in runtime_names
    assert "customerID" not in public_names
    if total_charges_approved:
        assert "TotalCharges" in runtime_names, (
            "TotalCharges blank-value handling is approved "
            f"({total_charges_review_status!r}) but is missing from the "
            "projected runtime contract"
        )
        assert "TotalCharges" in public_names
    else:
        assert "TotalCharges" not in runtime_names, (
            "TotalCharges blank-value handling is still "
            f"{total_charges_review_status!r} and must not appear as a "
            "runtime/public feature via projection"
        )
        assert "TotalCharges" not in public_names

    runtime_by_name = {f["name"]: f for f in runtime["features"]}
    assert runtime_by_name["SeniorCitizen"]["type"] == "boolean"
    assert "domain_constraints" not in runtime_by_name["SeniorCitizen"]

    public_by_name = {f["name"]: f for f in public["features"]}
    assert public_by_name["SeniorCitizen"]["input_type"] == "checkbox"


@pytest.mark.skipif(
    not (TELCO_RUNTIME_CONTRACT_PATH.exists() and TELCO_PUBLIC_CONTRACT_PATH.exists()),
    reason="Telco runtime/public contracts not yet materialized on disk",
)
def test_real_telco_runtime_and_public_contracts_materialized_on_disk_are_valid():
    """The actual committed contracts/telco-customer-churn/runtime-contract.json
    and public-contract.json artifacts validate against their schemas and
    exclude customerID/TotalCharges.

    KNOWN, DISCLOSED DIVERGENCE (as of Project Spec S0028's execution-contract
    fix): these two committed files were last (re)materialized while
    TotalCharges was still `inferred_pending_review` and were deliberately
    NOT regenerated when contracts/telco-customer-churn/execution-contract.json
    was updated to include TotalCharges as an approved feature -- runtime/
    public contract regeneration is API/UI-facing and out of scope for that
    fix. This test therefore intentionally continues to assert the current,
    still-excluding, on-disk reality, which no longer matches what
    test_real_telco_execution_contract_projects_to_valid_runtime_and_public_contracts
    proves the live execution contract would now project. Regenerating these
    two files to include TotalCharges (and updating this test to match)
    requires a separate, explicitly authorized implementation request."""
    runtime = json.loads(TELCO_RUNTIME_CONTRACT_PATH.read_text(encoding="utf-8"))
    public = json.loads(TELCO_PUBLIC_CONTRACT_PATH.read_text(encoding="utf-8"))

    jsonschema.validate(runtime, json.loads(RUNTIME_SCHEMA_PATH.read_text(encoding="utf-8")))
    jsonschema.validate(public, json.loads(PUBLIC_SCHEMA_PATH.read_text(encoding="utf-8")))

    runtime_names = {f["name"] for f in runtime["features"]}
    public_names = {f["name"] for f in public["features"]}
    assert "customerID" not in runtime_names
    assert "customerID" not in public_names
    assert "TotalCharges" not in runtime_names
    assert "TotalCharges" not in public_names


@pytest.mark.skipif(
    not (TELCO_RUNTIME_CONTRACT_PATH.exists() and TELCO_PUBLIC_CONTRACT_PATH.exists()),
    reason="Telco runtime/public contracts not yet materialized on disk",
)
def test_release_candidate_handoff_readiness_recognizes_telco_runtime_and_public_contract():
    """Once contracts/telco-customer-churn/runtime-contract.json and
    public-contract.json exist and validate, the release-candidate handoff
    readiness check (pipeline/assemble_candidate.py, Project Spec S0016)
    reports both roles ready:true from explicit repository-relative path
    references, while every other required role -- correctly left
    unreferenced here, since generating them is out of this spec's scope --
    remains not-ready and is_release_candidate_input_ready stays False."""
    readiness = build_release_candidate_handoff_readiness(
        {
            "runtime_contract": "contracts/telco-customer-churn/runtime-contract.json",
            "public_contract": "contracts/telco-customer-churn/public-contract.json",
        },
        repo_root=REPO_ROOT,
    )
    results_by_role = {r["role"]: r for r in readiness["role_results"]}
    assert results_by_role["runtime_contract"]["ready"] is True
    assert results_by_role["public_contract"]["ready"] is True
    for role, result in results_by_role.items():
        if role in ("runtime_contract", "public_contract"):
            continue
        assert result["ready"] is False
    assert readiness["is_release_candidate_input_ready"] is False

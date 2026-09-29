"""One canonical preparation-rule identity for the conditional blank fill
capability, shared by native preparation, scientific reproduction, and
authoring. Rules are parametric -- no dataset column names in code."""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import prepare_candidate, preparation_rules, scientific_reproduction  # noqa: E402
from pipeline import scientific_study_contract  # noqa: E402


def test_one_canonical_kind_shared_by_every_layer():
    kind = preparation_rules.CONDITIONAL_BLANK_NUMERIC_FILL
    assert kind == "conditional_blank_numeric_fill"
    assert set(scientific_reproduction._PREPARATION_RULES) == set(preparation_rules.PREPARATION_RULE_KINDS)
    assert scientific_study_contract.REPRODUCTION_CAPABILITIES["preparation_rule_kinds"] == set(
        preparation_rules.PREPARATION_RULE_KINDS
    )


def test_deprecated_alias_resolves_explicitly_and_unknown_kinds_fail_closed():
    assert preparation_rules.canonical_rule_kind("conditional_blank_to_zero") == "conditional_blank_numeric_fill"
    with pytest.raises(preparation_rules.PreparationRuleError):
        preparation_rules.canonical_rule_kind("mean_impute")


def test_historical_telco_authoring_policy_normalizes_to_the_canonical_rule():
    # The telco-authoring-v2 provenance artifact is read, never rewritten.
    recipe = json.loads(
        (REPO_ROOT / "pipeline/authoring/telco-customer-churn/preparation-recipe.json").read_text(encoding="utf-8")
    )
    (legacy,) = recipe["transformations"]
    assert preparation_rules.normalize_rule(legacy) == {
        "kind": "conditional_blank_numeric_fill",
        "column": "TotalCharges",
        "condition_column": "tenure",
        "condition_value": "0",
        "replacement": 0,
    }


def test_rule_is_parametric_for_any_dataset_columns():
    rule = preparation_rules.conditional_blank_numeric_fill_rule(
        column="balance", condition_column="months_active", condition_value="0", replacement=0
    )
    rows = [
        {"balance": " ", "months_active": "0"},
        {"balance": "12.5", "months_active": "3"},
    ]
    filled, passed, failing = prepare_candidate.apply_conditional_blank_numeric_fill(
        rows, rule["column"], rule["condition_column"], rule["condition_value"], rule["replacement"]
    )
    assert passed and failing == 0
    assert [row["balance"] for row in filled] == ["0.0", "12.5"]


def test_native_and_scientific_implementations_agree():
    import pandas as pd

    rows = [
        {"amount": "", "age": "0"},
        {"amount": "7", "age": "2"},
        {"amount": " ", "age": "0"},
    ]
    native, passed, _ = prepare_candidate.apply_conditional_blank_numeric_fill(rows, "amount", "age", "0", "0")
    assert passed
    frame = pd.DataFrame(rows)
    rule = {
        **preparation_rules.conditional_blank_numeric_fill_rule(
            column="amount", condition_column="age", condition_value="0", replacement=0
        ),
        "strip_strings": True,
    }
    prepared, filled_count = scientific_reproduction._apply_conditional_blank_numeric_fill(frame, rule)
    assert filled_count == 2
    assert [float(row["amount"]) for row in native] == list(prepared["amount"])


def test_blank_failing_the_condition_blocks_in_both_implementations():
    import pandas as pd

    rows = [{"amount": "", "age": "5"}]
    assert prepare_candidate.apply_conditional_blank_numeric_fill(rows, "amount", "age", "0", "0")[1] is False
    with pytest.raises(scientific_reproduction.ScientificReproductionError):
        scientific_reproduction._apply_conditional_blank_numeric_fill(
            pd.DataFrame(rows),
            preparation_rules.conditional_blank_numeric_fill_rule(
                column="amount", condition_column="age", condition_value="0", replacement=0
            ),
        )


def test_deprecated_native_function_name_delegates_to_canonical_implementation():
    rows = [{"x": "", "y": "0"}]
    assert prepare_candidate.verify_and_apply_conditional_fill(
        rows, "x", verification_column="y", verification_value="0", fill_value="0"
    ) == prepare_candidate.apply_conditional_blank_numeric_fill(rows, "x", "y", "0", "0")

"""
Predict view customization store tests for M35-05.

Verifies get_customization, create_customization, update_customization, and
validate_identifiers against an isolated fake repository root (pytest
tmp_path), so no test writes into the real
registry/predict-view-customizations.json or any other real repository path.
A minimal public_contract dict is constructed directly for each test (the
store module never loads a contract itself, matching
registry/predict_view_customization_validate.py's own caller-injects-contract
convention), so no real release/manifest data is needed.

Run from the repository root:
    python -m pytest tests/registry/test_predict_view_customization_store.py -v
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from registry.predict_view_customization_store import (  # noqa: E402
    CustomizationNotFoundError,
    create_customization,
    get_customization,
    update_customization,
    validate_identifiers,
)


_PUBLIC_CONTRACT = {
    "features": [
        {"name": "tenure", "optional": True},
        {"name": "monthly_charges", "optional": True},
        {"name": "senior_citizen", "optional": False},
    ]
}


def _customization(**overrides) -> dict:
    base = {
        "schema_version": "1.0.0",
        "view_id": "churn-risk-overview",
        "dataset_slug": "telco-customer-churn",
        "contract_precedence": {
            "canonical_contracts_are_source_of_truth": True,
            "customization_defines_runtime_validation": False,
            "customization_duplicates_contract": False,
        },
        "field_hints": [
            {"field_name": "tenure", "display_order_hint": 1},
        ],
        "groups": [],
    }
    base.update(overrides)
    return base


def _codes(result: dict) -> set:
    return {e["code"] for e in result["errors"]}


@pytest.fixture
def fake_repo(tmp_path):
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    return tmp_path


def test_create_customization_success(fake_repo):
    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is True
    assert result["errors"] == []
    registry_path = fake_repo / "registry" / "predict-view-customizations.json"
    assert registry_path.is_file()
    stored = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(stored["predict_view_customizations"]) == 1


def test_create_customization_view_id_mismatch(fake_repo):
    customization = _customization(view_id="other-view")

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", customization, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is False
    assert "VIEW_ID_MISMATCH" in _codes(result)


def test_create_customization_dataset_slug_mismatch(fake_repo):
    customization = _customization(dataset_slug="bank-marketing")

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", customization, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is False
    assert "DATASET_SLUG_MISMATCH" in _codes(result)


def test_create_customization_already_exists(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is False
    assert "CUSTOMIZATION_ALREADY_EXISTS" in _codes(result)


def test_create_customization_rejects_unknown_field_reference(fake_repo):
    customization = _customization(field_hints=[{"field_name": "not_a_real_field"}])

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", customization, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is False
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)
    registry_path = fake_repo / "registry" / "predict-view-customizations.json"
    assert not registry_path.exists()


def test_create_customization_rejects_required_field_hidden(fake_repo):
    customization = _customization(field_hints=[{"field_name": "senior_citizen", "hidden": True}])

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", customization, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["created"] is False
    assert "REQUIRED_FIELD_HIDDEN" in _codes(result)


def test_get_customization_returns_created_content(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    record = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)

    assert record["view_id"] == "churn-risk-overview"


def test_get_customization_missing_raises_not_found(fake_repo):
    with pytest.raises(CustomizationNotFoundError):
        get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)


# Project Spec S0110: the store is a generic, field-name-agnostic round trip
# -- it must persist and return view_copy.submit_button_label (and every
# other view_copy field) exactly as given, with no hardcoded field
# filtering.
def test_create_and_get_customization_round_trips_view_copy_submit_button_label(fake_repo):
    customization = _customization(
        view_copy={
            "heading": "Churn Risk Assessment",
            "description": "Estimate churn likelihood.",
            "usage_guidance": "Use canonical contracts.",
            "submit_button_label": "Estimate Churn Risk",
        }
    )

    result = create_customization(
        "churn-risk-overview", "telco-customer-churn", customization, _PUBLIC_CONTRACT, repo_root=fake_repo
    )
    assert result["created"] is True

    stored = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)
    assert stored["view_copy"]["submit_button_label"] == "Estimate Churn Risk"
    # Other view_copy fields are preserved unchanged alongside the new field.
    assert stored["view_copy"]["heading"] == "Churn Risk Assessment"
    assert stored["view_copy"]["description"] == "Estimate churn likelihood."
    assert stored["view_copy"]["usage_guidance"] == "Use canonical contracts."


def test_update_customization_round_trips_view_copy_submit_button_label(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    updated = _customization(view_copy={"heading": "Kept heading", "submit_button_label": "Run prediction"})
    result = update_customization(
        "churn-risk-overview", "telco-customer-churn", updated, _PUBLIC_CONTRACT, repo_root=fake_repo
    )
    assert result["updated"] is True

    stored = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)
    assert stored["view_copy"]["submit_button_label"] == "Run prediction"
    assert stored["view_copy"]["heading"] == "Kept heading"


def test_get_customization_returns_invalid_stored_record_without_validating(fake_repo):
    registry_path = fake_repo / "registry" / "predict-view-customizations.json"
    registry_path.write_text(
        json.dumps({
            "schema_version": "atlas.dataflow.predict-view-customizations.v1",
            "predict_view_customizations": [
                {
                    "view_id": "churn-risk-overview",
                    "dataset_slug": "telco-customer-churn",
                    "field_hints": [{"field_name": "not_a_real_field"}],
                }
            ],
        }),
        encoding="utf-8",
    )

    record = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)

    assert record["field_hints"][0]["field_name"] == "not_a_real_field"


def test_update_customization_success_creates_backup_and_replaces_content(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )
    updated = _customization(groups=[{"group_id": "g1", "label": "Group 1"}])
    updated["field_hints"] = [{"field_name": "tenure", "display_order_hint": 1, "group": "g1"}]

    result = update_customization(
        "churn-risk-overview", "telco-customer-churn", updated, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["updated"] is True
    backup_path = fake_repo / "registry" / "predict-view-customizations.json.previous"
    assert backup_path.is_file()
    record = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)
    assert record["groups"] == [{"group_id": "g1", "label": "Group 1"}]


def test_update_customization_nonexistent_rejected(fake_repo):
    result = update_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["updated"] is False
    assert "CUSTOMIZATION_NOT_FOUND_FOR_UPDATE" in _codes(result)
    backup_path = fake_repo / "registry" / "predict-view-customizations.json.previous"
    assert not backup_path.exists()


def test_update_customization_rejects_invalid_customization_without_writing(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )
    invalid = _customization(field_hints=[{"field_name": "not_a_real_field"}])

    result = update_customization(
        "churn-risk-overview", "telco-customer-churn", invalid, _PUBLIC_CONTRACT, repo_root=fake_repo
    )

    assert result["updated"] is False
    assert "UNKNOWN_FIELD_REFERENCE" in _codes(result)
    record = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)
    assert record["field_hints"] == _customization()["field_hints"]


@pytest.mark.parametrize(
    "bad_value",
    ["../etc/passwd", "Foo/Bar", "FOO", "foo_bar", "", "foo bar"],
)
def test_invalid_identifiers_rejected_before_filesystem_access(fake_repo, bad_value):
    with pytest.raises(ValueError):
        validate_identifiers(bad_value, "telco-customer-churn")
    with pytest.raises(ValueError):
        validate_identifiers("churn-risk-overview", bad_value)

    with pytest.raises(ValueError):
        create_customization(bad_value, "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo)
    with pytest.raises(ValueError):
        get_customization(bad_value, "telco-customer-churn", repo_root=fake_repo)
    with pytest.raises(ValueError):
        update_customization(bad_value, "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo)


def test_two_distinct_views_can_each_hold_their_own_customization(fake_repo):
    create_customization(
        "churn-risk-overview", "telco-customer-churn", _customization(), _PUBLIC_CONTRACT, repo_root=fake_repo
    )
    other_contract = {"features": [{"name": "age", "optional": True}]}
    other_customization = _customization(
        view_id="bank-subscription-predictor",
        dataset_slug="bank-marketing",
        field_hints=[{"field_name": "age", "display_order_hint": 1}],
    )

    result = create_customization(
        "bank-subscription-predictor", "bank-marketing", other_customization, other_contract, repo_root=fake_repo
    )

    assert result["created"] is True
    first = get_customization("churn-risk-overview", "telco-customer-churn", repo_root=fake_repo)
    second = get_customization("bank-subscription-predictor", "bank-marketing", repo_root=fake_repo)
    assert first["view_id"] == "churn-risk-overview"
    assert second["view_id"] == "bank-subscription-predictor"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))

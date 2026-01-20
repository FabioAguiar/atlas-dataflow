from __future__ import annotations

import copy
from typing import List, Dict, Any

import pytest

from atlas_dataflow.core.pipeline.types import StepStatus
from atlas_dataflow.steps.audit.profile_baseline import AuditProfileBaselineStep


def _make_rows() -> List[Dict[str, Any]]:
    return [
        {"id": 1, "cat": "A", "val": None},
        {"id": 2, "cat": "A", "val": 10},
        {"id": 2, "cat": "A", "val": 10},  # duplicate row
    ]


def test_audit_profile_baseline_success(dummy_ctx):
    rows = _make_rows()
    rows_before = copy.deepcopy(rows)

    dummy_ctx.set_artifact("data.raw_rows", rows)

    step = AuditProfileBaselineStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.SUCCESS
    assert rows == rows_before  # no mutation

    payload = result.payload

    # shape
    assert payload["shape"]["rows"] == 3
    assert payload["shape"]["columns"] == 3

    # missing
    missing = payload["missing"]["per_column"]
    assert missing["id"]["count"] == 0
    assert missing["id"]["ratio"] == 0.0
    assert missing["id"]["is_fully_null"] is False

    assert missing["val"]["count"] == 1
    assert missing["val"]["ratio"] == pytest.approx(1 / 3)
    assert missing["val"]["is_fully_null"] is False

    # duplicates
    duplicates = payload["duplicates"]
    assert duplicates["rows"] == 1
    assert duplicates["ratio"] == pytest.approx(1 / 3)

    # cardinality
    cardinality = payload["cardinality"]
    assert cardinality["id"]["unique_values"] == 2
    assert cardinality["cat"]["unique_values"] == 1
    assert cardinality["val"]["unique_values"] == 1
    assert cardinality["id"]["high_cardinality"] is True
    assert cardinality["cat"]["high_cardinality"] is False

    # dtypes
    dtypes = payload["dtypes"]
    assert dtypes["id"]["family"] == "numeric"
    assert dtypes["cat"]["family"] == "categorical"
    assert dtypes["val"]["family"] in {"numeric", "other"}


def test_audit_profile_baseline_missing_dataset(dummy_ctx):
    # do NOT set data.raw_rows
    step = AuditProfileBaselineStep()
    result = step.run(dummy_ctx)

    assert result.status == StepStatus.FAILED
    assert "error" in result.payload
    assert result.payload["error"]["type"] == "ValueError"
    assert "data.raw_rows" in result.payload["error"]["message"]

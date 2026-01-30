from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.types import StepResult, StepStatus, StepKind

from atlas_dataflow.core.traceability import create_manifest, step_finished, step_started
from atlas_dataflow.steps.export.inference_bundle import ExportInferenceBundleStep
from atlas_dataflow.steps.export.model_card import ExportModelCardStep

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.persistence.preprocess_store import PreprocessStore


def _minimal_contract_v1() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"name": "synthetic", "type": "classification"},
        "target": {"name": "y", "dtype": "int", "allowed_null": False},
        "features": [
            {
                "name": "x",
                "role": "numerical",
                "dtype": "float",
                "required": True,
                "allowed_null": False,
            },
            {
                "name": "category",
                "role": "categorical",
                "dtype": "category",
                "required": True,
                "allowed_null": False,
            },
        ],
        "defaults": {},
        "categories": {},
        "imputation": {},
    }


def _minimal_config() -> dict:
    return {
        "engine": {"fail_fast": True},
        "representation": {
            "preprocess": {
                "numeric": {"columns": ["x"], "scaler": None},
                "categorical": {
                    "columns": ["category"],
                    "encoder": "onehot",
                    "handle_unknown": "ignore",
                    "drop": None,
                },
            }
        },
        "steps": {
            "export.inference_bundle": {"enabled": True, "format": "joblib"},
            "export.model_card": {"enabled": True},
        },
    }


def _fit_preprocess_and_model(run_dir: Path):
    import pandas as pd
    from sklearn.linear_model import LogisticRegression

    contract = _minimal_contract_v1()
    cfg = _minimal_config()

    preprocess = build_representation_preprocess(contract=contract, config=cfg)

    df = pd.DataFrame(
        [
            {"x": 1.0, "category": "A", "y": 0},
            {"x": 2.0, "category": "B", "y": 1},
            {"x": 3.0, "category": "A", "y": 1},
            {"x": 0.5, "category": "B", "y": 0},
        ]
    )

    X = df.drop(columns=["y"])
    y = df["y"]

    preprocess.fit(X, y)

    store = PreprocessStore(run_dir=run_dir)
    store.save(preprocess=preprocess)

    model = LogisticRegression(max_iter=200)
    Xtr = preprocess.transform(X)
    model.fit(Xtr, y)

    return contract, cfg, preprocess, model


def _mk_manifest_with_minimum_steps(*, contract_hash: str = "contract_hash", config_hash: str = "config_hash") -> dict:
    m = create_manifest(
        run_id="run_123",
        started_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        atlas_version="0.1.0",
        config_hash=config_hash,
        contract_hash=contract_hash,
    )
    return m.to_dict()


def test_export_model_card_generates_file_and_has_min_sections(tmp_path: Path):
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    contract, cfg, preprocess, model = _fit_preprocess_and_model(run_dir)

    # --- ctx para export.inference_bundle ---
    ctx = RunContext(
        run_id="run_123",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        config=cfg,
        contract=contract,
        meta={"run_dir": run_dir},
    )
    # artefatos esperados de M5
    ctx.set_artifact("eval.model_selection", {"selection": {"champion_model_id": "logreg", "champion_score": 0.9}})
    ctx.set_artifact("eval.metrics", [{"model_id": "logreg", "metrics": {"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0}}])
    ctx.set_artifact("model.best_estimator", model)

    # Gera o bundle
    sr_bundle = ExportInferenceBundleStep().run(ctx)
    print("STATUS:", sr_bundle.status)
    print("SUMMARY:", sr_bundle.summary)
    print("PAYLOAD:", sr_bundle.payload)
    assert sr_bundle.status == StepStatus.SUCCESS

    assert sr_bundle.status == StepStatus.SUCCESS

    # --- Monta Manifest (fonte de verdade do Model Card) ---
    manifest = _mk_manifest_with_minimum_steps()

    # ingest.load
    step_started(manifest, step_id="ingest.load", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), kind="ingest")
    step_finished(
        manifest,
        step_id="ingest.load",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        result=StepResult(
            step_id="ingest.load",
            kind=StepKind.DIAGNOSTIC,
            status=StepStatus.SUCCESS,
            summary="dataset loaded",
            metrics={"rows": 4},
            warnings=[],
            artifacts={
                "source_path": "/data/dataset.csv",
                "source_type": "csv",
                "source_bytes": 123,
                "source_sha256": "sha_dataset",
            },
            payload={},
        ),
    )

    # evaluate.metrics
    step_started(manifest, step_id="evaluate.metrics", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), kind="evaluate")
    step_finished(
        manifest,
        step_id="evaluate.metrics",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        result=StepResult(
            step_id="evaluate.metrics",
            kind=StepKind.EVALUATE,
            status=StepStatus.SUCCESS,
            summary="evaluate.metrics completed",
            metrics={"accuracy": 1.0, "precision": 1.0, "recall": 1.0, "f1": 1.0},
            warnings=[],
            artifacts={"eval.metrics": "eval.metrics"},
            payload={},
        ),
    )

    # export.inference_bundle (usa o StepResult real)
    step_started(manifest, step_id="export.inference_bundle", ts=datetime(2025, 1, 1, tzinfo=timezone.utc), kind="export")
    step_finished(
        manifest,
        step_id="export.inference_bundle",
        ts=datetime(2025, 1, 1, tzinfo=timezone.utc),
        result=sr_bundle,
    )

    # --- Step export.model_card ---
    ctx2 = RunContext(
        run_id="run_123",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        config=cfg,
        contract=contract,
        meta={"run_dir": run_dir, "manifest": manifest},
    )

    sr = ExportModelCardStep().run(ctx2)
    assert sr.status == StepStatus.SUCCESS

    out = run_dir / "artifacts" / "model_card.md"
    assert out.exists()

    content = out.read_text(encoding="utf-8")

    # seções mínimas
    for section in [
        "# Model Card",
        "## Model Overview",
        "## Training Data",
        "## Input Contract",
        "## Metrics",
        "## Limitations",
        "## Execution Metadata",
    ]:
        assert section in content

    # coerência: bundle hash e id do campeão vêm do Manifest
    assert "Bundle hash (sha256)" in content
    assert "logreg" in content


def test_export_model_card_fails_explicitly_when_manifest_missing(tmp_path: Path):
    run_dir = tmp_path / "run"
    (run_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    contract = _minimal_contract_v1()
    cfg = _minimal_config()

    ctx = RunContext(
        run_id="run_123",
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
        config=cfg,
        contract=contract,
        meta={"run_dir": run_dir},
    )

    sr = ExportModelCardStep().run(ctx)
    assert sr.status == StepStatus.FAILED

"""
Smoke E2E — Atlas DataFlow (Issue #6)

Valida o core de ponta a ponta (M0):
- dataset sintético versionado
- contrato mínimo
- config mínima
- steps dummy (ingest/transform/export)
- Engine DAG
- geração e round-trip do Manifest v1

Requisitos:
- pytest -q (sem dependências externas)
"""

from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

from atlas_dataflow.core.config.loader import load_config
from atlas_dataflow.core.config.hashing import compute_config_hash
from atlas_dataflow.core.engine.engine import Engine
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.registry import StepRegistry
from atlas_dataflow.core.traceability.manifest import (
    create_manifest,
    step_started,
    step_finished,
    save_manifest,
    load_manifest,
)

from tests.fixtures.steps.dummy_ingest import DummyIngestStep
from tests.fixtures.steps.dummy_transform import DummyTransformStep
from tests.fixtures.steps.dummy_export import DummyExportStep


def _compute_contract_hash(contract: dict) -> str:
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_pipeline_smoke_e2e(tmp_path: Path) -> None:
    fixtures_dir = Path(__file__).parents[1] / "fixtures"
    dataset_path = fixtures_dir / "data" / "synthetic_binary.csv"
    contract_path = fixtures_dir / "config" / "contract_minimal.json"
    config_path = fixtures_dir / "config" / "config_minimal.yaml"

    assert dataset_path.exists()
    assert contract_path.exists()
    assert config_path.exists()

    config = load_config(defaults_path=str(config_path), local_path=None)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    ctx = RunContext(
        run_id="smoke-e2e",
        created_at=datetime.now(timezone.utc),
        config=config,
        contract=contract,
        meta={
            "dataset_path": dataset_path,
            "tmp_path": tmp_path,
        },
    )

    registry = StepRegistry()
    registry.add(DummyIngestStep())
    registry.add(DummyTransformStep())
    registry.add(DummyExportStep())

    engine = Engine(steps=registry.list(), ctx=ctx)
    run_result = engine.run()

    assert set(run_result.steps.keys()) == {"dummy.ingest", "dummy.transform", "dummy.export"}

    config_hash = compute_config_hash(config)
    contract_hash = _compute_contract_hash(contract)

    manifest = create_manifest(
        run_id=ctx.run_id,
        started_at=ctx.created_at,
        atlas_version="0.1.0",
        config_hash=config_hash,
        contract_hash=contract_hash,
    )

    for sid in ["dummy.ingest", "dummy.transform", "dummy.export"]:
        sr = run_result.steps[sid]
        step_started(manifest, step_id=sid, kind=sr.kind.value, ts=datetime.now(timezone.utc))
        step_finished(manifest, step_id=sid, ts=datetime.now(timezone.utc), result=sr)

    manifest_path = tmp_path / "manifest.json"
    save_manifest(manifest, manifest_path)
    assert manifest_path.exists()

    loaded = load_manifest(manifest_path).to_dict()
    assert set(loaded["steps"].keys()) == {"dummy.ingest", "dummy.transform", "dummy.export"}
    assert len(loaded["events"]) >= 6

    export_file = tmp_path / "export.csv"
    assert export_file.exists()

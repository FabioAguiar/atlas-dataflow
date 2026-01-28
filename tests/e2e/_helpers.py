"""Common helpers for Atlas DataFlow end-to-end tests.

Centraliza boilerplate para cenários E2E:
- criação de run_dir
- materialização de config/contract
- execução do Engine via StepRegistry (DAG determinístico)
- geração explícita do Manifest v1 (fonte de verdade)
- execução explícita de exports baseados em Manifest (model_card + report_md)
- asserts de artefatos

Princípios:
- usar APENAS APIs públicas do core
- sem atalhos mágicos (ex.: RunContext.from_config)
- builder representation.preprocess NÃO é Step: é chamado explicitamente aqui
- Manifest não é criado implicitamente pelo Engine: é criado explicitamente aqui (como no smoke E2E)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import os
from contextlib import contextmanager

@contextmanager
def _pushd(path: Path):
    """Temporarily chdir to `path` (E2E helper).

    Why: configs in E2E use RELATIVE paths for determinism between run_dir_a/run_dir_b.
    The core resolves those paths relative to the current working directory.
    In tests, we want them to resolve relative to the run_dir itself.
    """
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)
from typing import Any, Dict

import yaml

from atlas_dataflow.builders.representation.preprocess import build_representation_preprocess
from atlas_dataflow.core.config.hashing import compute_config_hash
from atlas_dataflow.core.config.loader import load_config
from atlas_dataflow.core.engine.engine import Engine
from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.registry import StepRegistry
from atlas_dataflow.core.traceability.manifest import create_manifest, step_finished, step_started
from atlas_dataflow.persistence.preprocess_store import PreprocessStore

# Steps canônicos (registrados explicitamente)
from atlas_dataflow.steps.ingest.load import IngestLoadStep
from atlas_dataflow.steps.contract.load import ContractLoadStep
from atlas_dataflow.steps.contract.conformity_report import ContractConformityReportStep
from atlas_dataflow.steps.transform.cast_types_safe import CastTypesSafeStep
from atlas_dataflow.steps.transform.categorical_standardize import TransformCategoricalStandardizeStep
from atlas_dataflow.steps.transform.impute_missing import TransformImputeMissingStep
from atlas_dataflow.steps.audit.profile_baseline import AuditProfileBaselineStep
from atlas_dataflow.steps.audit.duplicates import AuditDuplicatesStep
from atlas_dataflow.steps.transform.deduplicate import TransformDeduplicateStep
from atlas_dataflow.steps.transform.split_train_test import SplitTrainTestStep
from atlas_dataflow.steps.train.single import TrainSingleStep
from atlas_dataflow.steps.evaluate.metrics import EvaluateMetricsStep
from atlas_dataflow.steps.evaluate.model_selection import EvaluateModelSelectionStep
from atlas_dataflow.steps.export.inference_bundle import ExportInferenceBundleStep

# Exports baseados em Manifest (executados após a execução do Engine)
from atlas_dataflow.steps.export.model_card import ExportModelCardStep
from atlas_dataflow.steps.export.report_md import ExportReportMdStep


# Determinismo forte: timestamps fixos
_FIXED_CREATED_AT = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
_ATLAS_VERSION = "0.1.0"


def create_run_dir(base_tmp: Path, name: str) -> Path:
    run_dir = base_tmp / name
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_yaml(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _compute_contract_hash(contract: Dict[str, Any]) -> str:
    canonical = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def make_ctx(*, run_dir: Path, config_path: Path, contract_path: Path, run_id: str) -> RunContext:
    config = load_config(defaults_path=str(config_path), local_path=None)
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    return RunContext(
        run_id=run_id,
        created_at=_FIXED_CREATED_AT,
        config=config,
        contract=contract,
        meta={
            "run_dir": str(run_dir),
            "tmp_path": str(run_dir),  # compat
        },
    )


def _build_registry_for_engine() -> StepRegistry:
    """Registry da execução principal (Engine).

    Observação:
    - NÃO inclui export.model_card/export.report_md, pois dependem do Manifest final,
      que só existe após termos o RunResult.
    """
    registry = StepRegistry()

    registry.add(IngestLoadStep())
    registry.add(ContractLoadStep())

    # IMPORTANTE: evitar que contract.conformity_report rode antes de ingest.load
    conformity = ContractConformityReportStep()
    conformity.depends_on = ["contract.load", "ingest.load"]
    registry.add(conformity)

    registry.add(CastTypesSafeStep())
    registry.add(TransformCategoricalStandardizeStep())
    registry.add(TransformImputeMissingStep())
    registry.add(AuditProfileBaselineStep())
    registry.add(AuditDuplicatesStep())
    registry.add(TransformDeduplicateStep())
    registry.add(SplitTrainTestStep())
    registry.add(TrainSingleStep())
    registry.add(EvaluateMetricsStep())
    registry.add(EvaluateModelSelectionStep())
    registry.add(ExportInferenceBundleStep())

    return registry


def _build_manifest_for_run(*, ctx: RunContext, run_result) -> Dict[str, Any]:
    """Cria Manifest v1 determinístico a partir do RunResult."""
    config_hash = compute_config_hash(ctx.config)
    contract_hash = _compute_contract_hash(ctx.contract)

    manifest = create_manifest(
        run_id=ctx.run_id,
        started_at=ctx.created_at,
        atlas_version=_ATLAS_VERSION,
        config_hash=config_hash,
        contract_hash=contract_hash,
    )

    # Ordem determinística: usar a ordem de inserção do dict run_result.steps
    step_ids = list(run_result.steps.keys())

    base = ctx.created_at
    for i, sid in enumerate(step_ids):
        sr = run_result.steps[sid]
        ts_start = base + timedelta(seconds=i * 2)
        ts_end = base + timedelta(seconds=i * 2 + 1)
        step_started(manifest, step_id=sid, kind=sr.kind.value, ts=ts_start)
        step_finished(manifest, step_id=sid, ts=ts_end, result=sr)

    return manifest.to_dict()


def _run_manifest_based_exports(*, ctx: RunContext) -> None:
    """Executa exports que exigem Manifest final."""
    # Esses steps escrevem em artifacts/ e leem apenas meta["manifest"]
    r1 = ExportModelCardStep().run(ctx)
    if getattr(r1, "status", None) and r1.status.value != "success":
        raise AssertionError(f"export.model_card failed: {r1.summary}")

    r2 = ExportReportMdStep().run(ctx)
    if getattr(r2, "status", None) and r2.status.value != "success":
        raise AssertionError(f"export.report_md failed: {r2.summary}")


def run_pipeline(*, run_dir: Path, config_path: Path, contract_path: Path, run_id: str) -> RunContext:
    ctx = make_ctx(run_dir=run_dir, config_path=config_path, contract_path=contract_path, run_id=run_id)

    # Builder NÃO recebe ctx
    preprocess = build_representation_preprocess(contract=ctx.contract, config=ctx.config)
    PreprocessStore(run_dir=run_dir).save(preprocess=preprocess)

    # IMPORTANT: executar o core a partir do run_dir para que paths RELATIVOS do config
    # (ex.: telco_like.csv, contract.internal.v1.json) sejam resolvidos corretamente.
    with _pushd(run_dir):
        registry = _build_registry_for_engine()
        run_result = Engine(steps=registry.list(), ctx=ctx).run()

        # Fail-fast: se algo falhou no core, pare já com resumo.
        failed = [
            sid
            for sid, sr in run_result.steps.items()
            if getattr(sr, "status", None) and sr.status.value == "failed"
        ]
        if failed:
            summaries = {sid: run_result.steps[sid].summary for sid in failed}
            raise AssertionError(f"Pipeline failed steps: {failed} | summaries={summaries}")

        # Manifest final para exports
        ctx.meta["manifest"] = _build_manifest_for_run(ctx=ctx, run_result=run_result)

        # Exports baseados em Manifest (gera report.md)
        _run_manifest_based_exports(ctx=ctx)

    return ctx


def assert_core_artifacts(run_dir: Path) -> None:
    artifacts_dir = run_dir / "artifacts"
    assert artifacts_dir.exists(), f"artifacts/ ausente em {run_dir}"

    assert (artifacts_dir / "preprocess.joblib").exists(), "preprocess.joblib ausente"
    assert (artifacts_dir / "model_card.md").exists(), "model_card.md ausente"
    assert (artifacts_dir / "report.md").exists(), "report.md ausente"

    # inference bundle pode variar por versão
    assert (artifacts_dir / "inference_bundle").exists() or (artifacts_dir / "inference_bundle.joblib").exists(), (
        "inference bundle ausente (esperado inference_bundle/ ou inference_bundle.joblib)"
    )


def assert_reports_equal(run_dir_a: Path, run_dir_b: Path) -> None:
    """Compare reports in a deterministic way.

    Reports may contain volatile fields (timestamps, absolute paths, run_dir names),
    and also hashes/sha256 summaries that can change due to path-bound metadata
    or serialization details.

    This helper normalizes those fields before comparing.
    """
    import re

    report_a = (run_dir_a / "artifacts" / "report.md").read_text(encoding="utf-8")
    report_b = (run_dir_b / "artifacts" / "report.md").read_text(encoding="utf-8")

    def _normalize(text: str) -> str:
        # 1) Normalize ISO timestamps (UTC)
        text = re.sub(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z",
            "<TS>",
            text,
        )

        # 2) Normalize absolute paths (Windows + POSIX)
        text = re.sub(r"[A-Za-z]:\\[^ \n\r\t]*", "<PATH>", text)
        text = re.sub(r"[A-Za-z]:/[^ \n\r\t]*", "<PATH>", text)

        # 3) Normalize run_dir markers used in this suite
        text = text.replace("run_telco_like_a", "run_telco_like_<X>")
        text = text.replace("run_telco_like_b", "run_telco_like_<X>")
        text = text.replace("run_bank_like_a", "run_bank_like_<X>")
        text = text.replace("run_bank_like_b", "run_bank_like_<X>")

        # 4) Normalize payload_meta bytes (often volatile with serialization)
        # Examples:
        # {'payload_bytes': 125, 'payload_sha256': '...'}
        text = re.sub(r"('payload_bytes':\s*)\d+", r"\1<HASH_BYTES>", text)

        # 5) Normalize any 64-hex hashes (sha256/config_hash/contract_hash/etc)
        # Covers: payload_sha256, bundle_sha256, source_sha256, config_hash, contract_hash...
        text = re.sub(r"\b[0-9a-fA-F]{64}\b", "<HASH>", text)

        return text

    assert _normalize(report_a) == _normalize(report_b)

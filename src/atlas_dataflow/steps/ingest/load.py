"""Step canônico: ingest.load (v1).

Responsabilidades (M2):
- ler dataset de arquivo (CSV / Parquet) de forma determinística
- registrar origem (path + tipo) e fingerprint (sha256) no StepResult
- publicar dataset como artifact `data.raw_rows`

Limites explícitos (v1):
- NÃO infere schema
- NÃO aplica defaults
- NÃO normaliza valores
- NÃO executa auditorias de qualidade

Referências:
- docs/spec/ingest.load.v1.md (ainda não existe)
- docs/traceability.md
- docs/manifest.schema.v1.md
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from atlas_dataflow.core.pipeline.context import RunContext
from atlas_dataflow.core.pipeline.step import Step
from atlas_dataflow.core.pipeline.types import StepKind, StepResult, StepStatus


def _resolve_path(path_value: Any) -> Path:
    if not isinstance(path_value, str) or not path_value.strip():
        raise ValueError("Missing required config: steps.ingest.load.path")

    p = Path(path_value).expanduser()
    # resolve() pode falhar em alguns cenários, mas é útil para rastreabilidade
    try:
        p = p.resolve()
    except Exception:
        p = Path(path_value).expanduser().absolute()

    if not p.exists():
        raise FileNotFoundError(f"File not found: {p}")
    if not p.is_file():
        raise ValueError(f"Path is not a file: {p}")
    return p


def _sha256_and_bytes(path: Path) -> Tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
            size += len(chunk)
    return h.hexdigest(), size


def _load_csv(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        # csv.DictReader retorna tudo como string; isso é OK (sem coerções em ingest)
        return list(reader)


def _load_parquet(path: Path) -> List[Dict[str, Any]]:
    try:
        import pandas as pd  # type: ignore
    except Exception as e:  # pragma: no cover
        raise RuntimeError(
            "Parquet support requires pandas + a parquet engine (pyarrow or fastparquet)."
        ) from e

    df = pd.read_parquet(path)
    return df.to_dict(orient="records")


@dataclass
class IngestLoadStep(Step):
    """Carrega dados de um arquivo (CSV/Parquet) e registra origem + fingerprint."""

    id: str = "ingest.load"
    kind: StepKind = StepKind.DIAGNOSTIC
    depends_on: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.depends_on is None:
            self.depends_on = []

    def run(self, ctx: RunContext) -> StepResult:
        cfg = ctx.config or {}
        steps_cfg = cfg.get("steps") if isinstance(cfg, dict) else None
        step_cfg = (
            (steps_cfg.get(self.id) or {})
            if isinstance(steps_cfg, dict)
            else {}
        )

        # permissivo: se alguém usar config.steps["ingest.load"].enabled
        enabled = step_cfg.get("enabled", True) if isinstance(step_cfg, dict) else True
        if enabled is False:
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SKIPPED,
                summary="step disabled by config",
                metrics={},
                warnings=[],
                artifacts={},
                payload={"disabled": True},
            )

        try:
            path = _resolve_path(step_cfg.get("path") if isinstance(step_cfg, dict) else None)
            suffix = path.suffix.lower()

            sha256, size_bytes = _sha256_and_bytes(path)

            if suffix == ".csv":
                rows = _load_csv(path)
                source_type = "csv"
            elif suffix == ".parquet":
                rows = _load_parquet(path)
                source_type = "parquet"
            else:
                raise ValueError(f"Unsupported file extension: {suffix}")

            ctx.set_artifact("data.raw_rows", rows)

            ctx.log(
                step_id=self.id,
                level="info",
                message="dataset loaded",
                source_type=source_type,
                source_path=str(path),
                rows=len(rows),
            )

            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="dataset loaded",
                metrics={
                    "rows": len(rows),
                    "bytes": size_bytes,
                },
                warnings=[],
                artifacts={
                    "source_path": str(path),
                    "source_type": source_type,
                    "source_bytes": size_bytes,
                    "source_sha256": sha256,
                },
                payload={
                    "source": {
                        "path": str(path),
                        "type": source_type,
                        "sha256": sha256,
                        "bytes": size_bytes,
                    }
                },
            )

        except Exception as e:
            # padrão do repo: Steps retornam FAILED com payload de erro, não explodem o runner
            ctx.log(
                step_id=self.id,
                level="error",
                message="ingest.load failed",
                error_type=e.__class__.__name__,
                error_message=str(e) or "error",
            )
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.FAILED,
                summary=str(e) or "ingest.load failed",
                metrics={},
                warnings=[],
                artifacts={},
                payload={
                    "error": {
                        "type": e.__class__.__name__,
                        "message": str(e) or "error",
                    }
                },
            )

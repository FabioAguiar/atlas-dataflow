"""Persistência canônica do artefato de preprocess (v1).

Issue: M4-02 — Persistência do preprocess (artefato)

No Atlas DataFlow, o preprocess (ex.: `sklearn.compose.ColumnTransformer`) deve
ser persistido de forma **explícita** e **rastreável**, garantindo:

- reprodutibilidade entre execuções
- consistência entre treino/validação/inferência
- round-trip load sem alteração de comportamento

Este módulo implementa uma Store minimalista, sem acoplamento com Engine.

Decisões (v1):
- Formato: joblib
- Caminho determinístico (relativo ao run_dir): artifacts/preprocess.joblib
- Metadata registrada no Manifest via Event Log (evento explícito)

Limites explícitos:
- Não recalcula preprocess no load
- Não altera parâmetros no reload
- Não depende do dataset (apenas persiste o objeto já construído/fitado)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Union


try:
    import joblib  # type: ignore
except Exception as e:  # pragma: no cover
    joblib = None  # type: ignore
    _JOBLIB_IMPORT_ERROR = e
else:
    _JOBLIB_IMPORT_ERROR = None


@dataclass(frozen=True)
class PreprocessArtifactMeta:
    """Metadata mínima (v1) para rastrear um preprocess persistido."""

    type: str = "preprocess"
    format: str = "joblib"
    path: str = "artifacts/preprocess.joblib"
    builder: str = "representation.preprocess"
    version: str = "v1"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "format": self.format,
            "path": self.path,
            "builder": self.builder,
            "version": self.version,
        }


class PreprocessStore:
    """Store canônica (v1) para persistência e load do preprocess."""

    def __init__(self, *, run_dir: Union[str, Path]):
        self.run_dir = Path(run_dir)

    # ------------------------------------------------------------------
    # Paths
    # ------------------------------------------------------------------
    def artifact_path(self) -> Path:
        """Retorna o caminho absoluto determinístico do artefato no run_dir."""
        return self.run_dir / "artifacts" / "preprocess.joblib"

    def artifact_rel_path(self) -> str:
        """Retorna o caminho relativo canônico (v1) para registro no Manifest."""
        return "artifacts/preprocess.joblib"

    # ------------------------------------------------------------------
    # Persist / Load
    # ------------------------------------------------------------------
    def save(
        self,
        *,
        preprocess: Any,
        manifest: Optional[Union[Dict[str, Any], Any]] = None,
        builder_id: str = "representation.preprocess",
        version: str = "v1",
    ) -> Dict[str, Any]:
        """Salva o preprocess em joblib e (opcionalmente) registra no Manifest.

        Args:
            preprocess: Objeto sklearn já construído (idealmente já fitado).
            manifest: AtlasManifest ou dict do Manifest (opcional).
            builder_id: Builder de origem (default: representation.preprocess).
            version: versão do artefato (default: v1).

        Returns:
            Dict[str, Any]: metadata do artefato (serializável).
        """
        if joblib is None:  # pragma: no cover
            raise RuntimeError("joblib is required for preprocess persistence") from _JOBLIB_IMPORT_ERROR

        path = self.artifact_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(preprocess, path)

        meta = PreprocessArtifactMeta(
            path=self.artifact_rel_path(),
            builder=builder_id,
            version=version,
        ).to_dict()

        if manifest is not None:
            self._record_manifest(manifest, meta)

        return meta

    def load(self) -> Any:
        """Carrega o preprocess persistido (joblib) sem recalcular."""
        if joblib is None:  # pragma: no cover
            raise RuntimeError("joblib is required for preprocess persistence") from _JOBLIB_IMPORT_ERROR

        path = self.artifact_path()
        if not path.exists():
            raise FileNotFoundError(str(path))
        return joblib.load(path)

    # ------------------------------------------------------------------
    # Manifest integration
    # ------------------------------------------------------------------
    def _record_manifest(self, manifest: Union[Dict[str, Any], Any], meta: Dict[str, Any]) -> None:
        """Registra metadata do artefato no Manifest via Event Log.

        Mantém compatibilidade com o schema atual do Manifest:
        - Não cria novos campos top-level
        - Usa somente `events` (já extensível por design)
        """
        from atlas_dataflow.core.traceability.manifest import add_event

        ts = datetime.now(timezone.utc)
        add_event(
            manifest,
            event_type="artifact_saved",
            ts=ts,
            step_id=None,
            payload={"artifact": dict(meta)},
        )


__all__ = ["PreprocessStore", "PreprocessArtifactMeta"]

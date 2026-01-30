# src/atlas_dataflow/core/run_context.py
"""
RunContext — Contexto canônico de execução do Atlas DataFlow.

Este módulo define o **RunContext**, a estrutura compartilhada passada a todos os Steps durante
a execução de uma run do pipeline.

O RunContext é o **único meio permitido** de:
- troca indireta de informações entre Steps
- armazenamento de artefatos intermediários (por chave explícita)
- registro de logs estruturados de execução
- coleta de warnings não fatais associados a Steps
- **acesso consistente ao dataset mutável** ao longo do run
- **suporte a payloads de impacto** (auditoria de transformações) no ciclo do run

Princípios fundamentais:
- Isolamento por execução (cada run possui seu próprio contexto)
- Nenhum Step acessa estado global ou externo para comunicação indireta
- Transformações devem ser auditáveis e rastreáveis (impact payload)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


# Chave canônica para o dataset mutável dentro do store de artefatos.
DATASET_ARTIFACT_KEY = "dataset"


@dataclass
class RunContext:
    """
    Contexto de execução compartilhado de uma run do pipeline.

    Campos canônicos:
    - run_id: identificador único da execução
    - created_at: timestamp UTC de criação do contexto
    - config: configuração efetiva (defaults + local deep-merge)
    - contract: contrato efetivo (após `contract.load`) — pode ser None antes do Step
    - meta: metadados de execução (ex.: run_dir, paths, info do runner)
    - warnings: warnings por step_id
    - events: log estruturado de eventos
    - _artifacts: store de artefatos intermediários (key -> value)

    Extensões M1:
    - impacts: payloads de impacto por step (ex.: auditoria de coerções)
    """

    run_id: str
    created_at: str
    config: Dict[str, Any]
    contract: Any = None

    warnings: Dict[str, List[str]] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    # Store de artefatos intermediários
    _artifacts: Dict[str, Any] = field(default_factory=dict, repr=False)

    # Payloads de impacto por step (transformações)
    impacts: Dict[str, Any] = field(default_factory=dict)

    # -----------------------------
    # Artifact store
    # -----------------------------
    def set_artifact(self, key: str, value: Any) -> None:
        self._artifacts[key] = value

    def has_artifact(self, key: str) -> bool:
        return key in self._artifacts

    def get_artifact(self, key: str) -> Any:
        if key not in self._artifacts:
            raise KeyError(key)
        return self._artifacts[key]

    # -----------------------------
    # Dataset (mutável) — acesso consistente
    # -----------------------------
    def has_dataset(self) -> bool:
        return self.has_artifact(DATASET_ARTIFACT_KEY)

    def set_dataset(self, dataset: Any) -> None:
        """Define o dataset efetivo da run.

        Importante:
        - Este método **não faz cópia** do dataset.
        - Steps de transformação podem modificar o dataset in-place,
          e o RunContext continuará apontando para a referência atual.
        """
        self.set_artifact(DATASET_ARTIFACT_KEY, dataset)

    def get_dataset(self) -> Any:
        """Retorna o dataset efetivo da run (referência mutável)."""
        return self.get_artifact(DATASET_ARTIFACT_KEY)

    # -----------------------------
    # Impact payloads — auditoria no ciclo do run
    # -----------------------------
    def set_impact(self, *, step_id: str, impact: Any) -> None:
        """Registra o payload de impacto de um Step.

        Usado por Steps de transformação (ex.: `transform.cast_types_safe`) para
        reportar auditoria de antes/depois e contagens afetadas.

        O Engine/Traceability pode incorporar este payload no Manifest.
        """
        self.impacts[step_id] = impact

    def get_impact(self, step_id: str) -> Any:
        if step_id not in self.impacts:
            raise KeyError(step_id)
        return self.impacts[step_id]

    # -----------------------------
    # Logging & warnings
    # -----------------------------
    def log(self, *, step_id: str, level: str, message: str, **extra: Any) -> None:
        event = {
            "run_id": self.run_id,
            "step_id": step_id,
            "level": level,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        event.update(extra)
        self.events.append(event)

    def add_warning(self, *, step_id: str, message: str) -> None:
        if step_id not in self.warnings:
            self.warnings[step_id] = []
        self.warnings[step_id].append(message)

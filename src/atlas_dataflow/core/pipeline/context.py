# src/atlas_dataflow/core/pipeline/context.py
"""
Contexto de execução compartilhado do pipeline.

Este módulo define o `RunContext`, a estrutura canônica utilizada para
compartilhar estado explícito entre Steps durante a execução de uma run
do pipeline no Atlas DataFlow.

O RunContext atua como o único meio permitido de:
    - troca indireta de informações entre Steps
    - armazenamento de artefatos intermediários
    - registro de logs estruturados de execução
    - coleta de warnings não fatais associados a Steps

Princípios fundamentais:
    - Isolamento por execução (cada run possui seu próprio contexto)
    - Comunicação explícita e rastreável
    - Ausência de estado global compartilhado
    - Estrutura simples e testável

Responsabilidades do módulo:
    - Manter identidade e metadados da execução
    - Armazenar configuração e contrato resolvidos
    - Oferecer um artifact store explícito
    - Registrar eventos de log estruturados
    - Coletar warnings por Step

Invariantes:
    - Artefatos são indexados por chave explícita
    - Logs sempre incluem `run_id` e `step_id`
    - Warnings são agrupados por `step_id`
    - O contexto é mutável apenas durante a execução

Limites explícitos:
    - Não executa Steps
    - Não planeja nem coordena execução
    - Não persiste dados automaticamente
    - Não registra eventos no Manifest

Este módulo existe para garantir isolamento,
clareza e rastreabilidade na execução de pipelines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from datetime import timezone


@dataclass
class RunContext:
    """
    Contexto de execução compartilhado de uma run do pipeline.

    Esta classe representa o contexto canônico passado a todos os Steps
    durante a execução do pipeline, funcionando como o único meio
    permitido de comunicação indireta e compartilhamento de estado.

    O RunContext consolida:
        - identidade da execução (run_id, created_at)
        - configuração resolvida
        - contrato semântico utilizado
        - armazenamento de artefatos produzidos
        - logs estruturados de execução
        - warnings associados a Steps específicos

    Decisões arquiteturais:
        - Steps interagem apenas via RunContext
        - Não existe acesso a estado global ou compartilhado externo
        - Artefatos são armazenados por chave explícita
        - Logs e warnings são estruturados e rastreáveis

    Invariantes:
        - Cada execução possui um RunContext único
        - Artefatos são isolados por run
        - Logs incluem sempre `run_id` e `step_id`
        - Warnings são associados explicitamente a um Step

    Limites explícitos:
        - Não executa Steps
        - Não decide políticas de execução
        - Não persiste dados automaticamente
        - Não valida semântica de domínio

    Este contexto existe para garantir isolamento,
    rastreabilidade e comunicação explícita entre Steps.
    """
    run_id: str
    created_at: datetime
    config: Dict[str, Any]
    contract: Dict[str, Any]
    meta: Dict[str, Any] = field(default_factory=dict)

    _artifacts: Dict[str, Any] = field(default_factory=dict, init=False, repr=False)
    events: List[Dict[str, Any]] = field(default_factory=list, init=False)
    warnings: Dict[str, List[str]] = field(default_factory=dict, init=False)

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

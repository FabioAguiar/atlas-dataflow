# src/atlas_dataflow/core/traceability/__init__.py
"""
Pacote de rastreabilidade (traceability) do Atlas DataFlow — Manifest v1.

Este pacote define a API canônica de rastreabilidade do Atlas DataFlow,
responsável por registrar, consolidar e persistir informações forenses
sobre a execução de pipelines.

Responsabilidades principais:
    - Criar e manter o Manifest de execução (Manifest v1)
    - Registrar eventos explícitos em um Event Log ordenado
    - Atualizar incrementalmente o estado de Steps
    - Persistir e restaurar o Manifest de forma determinística

API pública exposta:
    - AtlasManifest     → estrutura canônica do Manifest
    - create_manifest   → criação explícita do Manifest
    - add_event         → registro explícito de eventos no Event Log
    - step_started      → marca início de execução de um Step
    - step_finished     → registra conclusão bem-sucedida de um Step
    - step_failed       → registra falha de um Step
    - save_manifest     → persistência do Manifest em JSON
    - load_manifest     → restauração determinística do Manifest

Decisões arquiteturais:
    - Nenhum evento é emitido implicitamente
    - Atualizações ocorrem apenas via chamadas explícitas da API
    - A ordem do Event Log reflete a ordem de chamada
    - O Manifest é independente de engine, pipeline ou UI

Invariantes:
    - O Manifest inicia com `steps` e `events` vazios
    - Eventos nunca são reordenados automaticamente
    - A estrutura é serializável e reprodutível

Limites explícitos:
    - Não executa pipeline
    - Não decide políticas de execução
    - Não contém lógica de domínio

Este pacote existe para garantir rastreabilidade forense,
auditoria confiável e reprodutibilidade das execuções.
"""

from .manifest import (
    AtlasManifest,
    create_manifest,
    add_event,
    step_started,
    step_finished,
    step_failed,
    save_manifest,
    load_manifest,
)

__all__ = [
    "AtlasManifest",
    "create_manifest",
    "add_event",
    "step_started",
    "step_finished",
    "step_failed",
    "save_manifest",
    "load_manifest",
]

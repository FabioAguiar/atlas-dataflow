# src/atlas_dataflow/core/pipeline/registry.py
"""
Registro estrutural de Steps do pipeline.

Este módulo define o `StepRegistry`, responsável por registrar Steps
e validar a integridade estrutural do pipeline antes de qualquer
planejamento ou execução.

O registry atua como uma camada de proteção antecipada, garantindo que:
    - cada Step possua um identificador válido
    - não existam identificadores duplicados
    - a ordem de declaração dos Steps seja preservada explicitamente

Responsabilidades do módulo:
    - Validar unicidade de `step.id`
    - Preservar ordem de registro dos Steps
    - Expor acesso controlado aos Steps registrados

Decisões arquiteturais:
    - A validação ocorre antes do Engine e do planner
    - Erros estruturais são tratados como falhas fatais
    - O registry não resolve dependências nem executa Steps
    - A ordem de registro é mantida separadamente da estrutura de armazenamento

Invariantes:
    - Cada Step registrado possui um `step.id` único
    - A lista de Steps reflete exatamente a ordem de registro
    - Nenhum Step inválido é aceito no registry

Limites explícitos:
    - Não planeja execução (não é DAG planner)
    - Não executa pipeline
    - Não interage com RunContext ou Manifest
    - Não contém lógica de domínio

Este módulo existe para garantir integridade estrutural,
previsibilidade e segurança na definição do pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from .step import Step


class DuplicateStepIdError(ValueError):
    """
    Exceção levantada quando ocorre duplicidade de identificador de Step.

    Esta exceção indica uma violação estrutural do pipeline, ocorrendo
    quando se tenta registrar dois ou mais Steps com o mesmo `step.id`
    no `StepRegistry`.

    Decisões arquiteturais:
        - Identificadores de Step devem ser únicos no pipeline
        - A duplicidade é tratada como erro fatal de configuração
        - A exceção é lançada no momento do registro, antes da execução

    Invariantes:
        - Um `step.id` duplicado invalida o pipeline
        - Nenhum registro parcial é aceito após a detecção do erro

    Limites explícitos:
        - Não tenta resolver ou renomear Steps automaticamente
        - Não valida dependências entre Steps
        - Não interage com o Engine ou planner

    Esta exceção existe para garantir integridade estrutural,
    previsibilidade e segurança na definição do pipeline.
    """



@dataclass
class StepRegistry:
    """
    Registro canônico de Steps para validação estrutural pré-execução.

    Esta classe é responsável por registrar Steps e validar a unicidade
    de seus identificadores (`step.id`) antes que o pipeline seja
    planejado ou executado pelo Engine.

    O `StepRegistry` atua como uma salvaguarda estrutural, garantindo que:
        - cada Step possua um identificador válido
        - não existam Step IDs duplicados no pipeline
        - a ordem de registro seja preservada explicitamente

    Decisões arquiteturais:
        - A validação ocorre antes do Engine
        - A ordem de inserção é preservada separadamente
        - A estrutura interna não é exposta diretamente
        - Erros estruturais são tratados como falhas fatais

    Invariantes:
        - Cada `step.id` é único no registry
        - A lista de Steps reflete exatamente a ordem de registro
        - Apenas Steps válidos são armazenados

    Limites explícitos:
        - Não planeja execução (não é planner)
        - Não executa Steps
        - Não resolve dependências
        - Não interage com RunContext ou Manifest

    Este registro existe para garantir integridade estrutural,
    previsibilidade e segurança antes da execução do pipeline.
    """

    _steps: Dict[str, Step] = field(default_factory=dict, init=False, repr=False)
    _order: List[str] = field(default_factory=list, init=False, repr=False)

    def add(self, step: Step) -> None:
        step_id = getattr(step, "id", None)
        if not isinstance(step_id, str) or not step_id.strip():
            raise ValueError("step.id must be a non-empty string")

        if step_id in self._steps:
            raise DuplicateStepIdError(f"Duplicate step id: {step_id}")

        self._steps[step_id] = step
        self._order.append(step_id)

    def get(self, step_id: str) -> Step:
        return self._steps[step_id]

    def list(self) -> List[Step]:
        return [self._steps[sid] for sid in self._order]

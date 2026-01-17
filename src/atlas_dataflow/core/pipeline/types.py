# src/atlas_dataflow/core/pipeline/types.py
"""
Tipos canônicos do pipeline do Atlas DataFlow.

Este módulo define as estruturas e enums fundamentais que padronizam
a comunicação entre Steps, Engine e camadas de rastreabilidade.

Os tipos aqui definidos representam:
    - estados finais de execução de Steps
    - classificação semântica de Steps
    - resultado imutável produzido por um Step

Componentes principais:
    - StepStatus → enum de estados finais (SUCCESS, SKIPPED, FAILED)
    - StepKind   → enum de classificação semântica de Steps
    - StepResult → estrutura imutável de resultado de execução

Princípios fundamentais:
    - Tipos são estáveis e serializáveis
    - Valores são projetados para persistência em Manifest
    - Nenhuma lógica de execução vive neste módulo

Invariantes:
    - Enums possuem valores textuais canônicos
    - StepResult é imutável e seguro contra mutação acidental
    - Tipos não dependem de engine, pipeline ou UI

Limites explícitos:
    - Não executa Steps
    - Não planeja pipelines
    - Não decide políticas de execução
    - Não contém lógica de domínio

Este módulo existe para garantir consistência,
interoperabilidade e clareza semântica no pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class StepKind(str, Enum):
    """
    Tipos semânticos de Steps no pipeline.

    Este enum define a classificação semântica de um Step dentro do
    pipeline do Atlas DataFlow, permitindo diferenciar responsabilidades
    conceituais sem acoplamento à lógica de execução.

    Os valores são strings para facilitar:
        - serialização em JSON
        - persistência em Manifest
        - inspeção e relatórios

    Tipos definidos:
        - DIAGNOSTIC: inspeções, auditorias e validações de dados
        - TRANSFORM: transformações estruturais ou semânticas de dados
        - TRAIN: treinamento de modelos ou artefatos aprendidos
        - EVALUATE: avaliação de modelos ou resultados intermediários
        - EXPORT: exportação ou materialização de resultados

    Decisões arquiteturais:
        - O tipo é puramente informativo e semântico
        - Steps não alteram comportamento com base no `kind`
        - O Engine não utiliza `StepKind` para decidir execução

    Invariantes:
        - Todo Step possui exatamente um `kind`
        - O valor textual do enum é estável e canônico

    Limites explícitos:
        - Não define ordem de execução
        - Não codifica políticas ou regras de negócio
        - Não representa estados de execução

    Este enum existe para enriquecer a rastreabilidade,
    documentação e leitura semântica do pipeline.
    """
    DIAGNOSTIC = "diagnostic"
    TRANSFORM = "transform"
    TRAIN = "train"
    EVALUATE = "evaluate"
    EXPORT = "export"



class StepStatus(str, Enum):
    """
    Estados finais possíveis da execução de um Step.

    Este enum define os valores canônicos de status que representam
    o resultado final da execução de um Step no Atlas DataFlow.

    Os valores são strings para facilitar:
        - serialização em JSON
        - persistência em Manifest
        - interoperabilidade com adapters e relatórios

    Estados definidos:
        - SUCCESS: execução concluída com sucesso
        - SKIPPED: execução pulada por decisão explícita (ex.: config)
        - FAILED: execução interrompida por erro

    Decisões arquiteturais:
        - O status é um valor final, não transitório
        - Estados intermediários (ex.: running) não pertencem a este enum
        - O valor do enum é usado diretamente em persistência e eventos

    Invariantes:
        - O status final de um Step é exatamente um dos valores definidos
        - O valor textual do enum é estável e canônico

    Limites explícitos:
        - Não representa estados de execução em andamento
        - Não codifica políticas de execução
        - Não contém lógica associada ao status

    Este enum existe para padronizar e estabilizar
    a representação do estado final de Steps.
    """
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True)
class StepResult:
    """
    Resultado imutável da execução de um Step.

    Esta classe representa o artefato canônico retornado por um Step após
    sua execução, consolidando status, métricas, avisos e referências a
    artefatos produzidos.

    O `StepResult` é projetado para ser:
        - imutável (frozen)
        - serializável
        - independente de engine e UI
        - adequado para auditoria e inspeção posterior

    Campos:
        - step_id: identificador único do Step
        - kind: tipo semântico do Step (ex.: diagnostic, train, audit)
        - status: estado final da execução do Step
        - summary: resumo textual da execução
        - metrics: métricas numéricas produzidas pelo Step
        - warnings: avisos não fatais gerados durante a execução
        - artifacts: referências a artefatos produzidos (ex.: URIs)
        - payload: dados adicionais livres associados ao resultado

    Decisões arquiteturais:
        - A imutabilidade garante segurança contra mutações acidentais
        - Métricas, warnings e artifacts possuem defaults explícitos
        - O resultado não contém lógica de execução

    Invariantes:
        - Uma instância de StepResult nunca é alterada após criada
        - `step_id`, `kind` e `status` estão sempre presentes
        - Coleções internas são inicializadas de forma consistente

    Limites explícitos:
        - Não executa persistência
        - Não registra eventos
        - Não decide políticas de execução
        - Não valida semântica de domínio

    Este objeto existe para padronizar a saída de Steps
    e servir como insumo confiável para engine, relatórios e rastreabilidade.
    """
    step_id: str
    kind: StepKind
    status: StepStatus
    summary: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    artifacts: Dict[str, str] = field(default_factory=dict)
    payload: Dict[str, Any] = field(default_factory=dict)

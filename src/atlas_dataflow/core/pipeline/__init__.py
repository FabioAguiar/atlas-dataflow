# src/atlas_dataflow/core/pipeline/__init__.py
"""
# Pipeline Core — Atlas DataFlow

Este pacote define os **contratos canônicos** e as **estruturas fundamentais**
que compõem um pipeline no Atlas DataFlow.

Um pipeline é modelado como um **DAG explícito de Steps**, onde:
- cada Step declara identidade, tipo semântico e dependências
- a execução é coordenada exclusivamente pelo Engine
- o estado compartilhado é mediado pelo `RunContext`

## Componentes

- **types**
  - `StepStatus`: estados finais de execução
  - `StepKind`: classificação semântica de Steps
  - `StepResult`: resultado imutável da execução de um Step

- **step**
  - `Step` (Protocol): contrato mínimo que todo Step deve satisfazer

- **context**
  - `RunContext`: contexto de execução compartilhado (artefatos, logs, warnings)

- **registry**
  - `StepRegistry`: validação estrutural e unicidade de `step.id`

## Princípios Fundamentais

- Steps **não conhecem** o Engine nem o planner
- Steps **não controlam** ordem de execução
- Dependências são **explícitas e declarativas**
- Comunicação entre Steps ocorre **apenas via RunContext**
- Nenhuma decisão implícita ou silenciosa

## Invariantes

- Cada Step possui um `step_id` único
- Steps não executam fora do controle do Engine
- Estado compartilhado é sempre explícito e rastreável

## Limites Explícitos

- Não planeja execução (não é DAG planner)
- Não executa pipeline
- Não contém lógica de domínio ou ML
- Não depende de UI, notebooks ou frameworks externos

Este pacote existe para garantir **clareza contratual,
determinismo e testabilidade** na construção de pipelines.
"""

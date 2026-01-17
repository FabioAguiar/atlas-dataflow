# src/atlas_dataflow/core/__init__.py
"""
Core do Atlas DataFlow.

Este pacote contém a implementação canônica e independente de adapters
do Atlas DataFlow, reunindo todas as responsabilidades essenciais para
planejamento, execução e rastreabilidade de pipelines.

O core é projetado para ser:
    - determinístico
    - testável de forma isolada
    - livre de dependências de UI, notebooks ou frameworks externos
    - orientado a contratos explícitos

Componentes principais:
    - config       → resolução de configuração (merge, validação estrutural, hashing)
    - pipeline     → protocolos de Step, contexto de execução e registry
    - engine       → planejamento (DAG) e execução controlada do pipeline
    - traceability → Manifest e Event Log para auditoria e análise forense

Princípios fundamentais:
    - Nenhuma decisão silenciosa: todo comportamento é explícito e testado
    - Separação estrita de responsabilidades entre camadas
    - Estado e efeitos colaterais são sempre rastreáveis

Limites explícitos:
    - Não contém lógica de domínio específica
    - Não define Steps concretos de negócio ou ML
    - Não depende de notebooks, CLI ou serviços externos

Este pacote existe como a fonte de verdade operacional do Atlas DataFlow.
"""

# src/atlas_dataflow/core/engine/__init__.py
"""
Engine do Atlas DataFlow.

Este pacote contém a implementação responsável por **planejar** e
**executar** pipelines no Atlas DataFlow, respeitando contratos,
configuração resolvida e decisões explícitas de execução.

O Engine atua como o orquestrador central do pipeline, sendo responsável por:
    - validar a estrutura do pipeline
    - planejar a ordem de execução (DAG)
    - executar Steps de forma controlada
    - consolidar o resultado final da execução

Componentes principais:
    - planner → ordenação topológica determinística e validações estruturais
    - engine  → execução coordenada de Steps com políticas explícitas

Princípios fundamentais:
    - Planejamento e execução são responsabilidades separadas
    - A ordem de execução é determinística para o mesmo grafo
    - Nenhuma decisão silenciosa é tomada durante a execução
    - Políticas de execução são controladas por configuração

Invariantes:
    - Steps só são executados após suas dependências
    - Cada Step é executado no máximo uma vez por run
    - O resultado da execução reflete explicitamente o estado de cada Step

Limites explícitos:
    - Não define Steps de domínio
    - Não contém lógica de negócio ou ML
    - Não persiste resultados automaticamente
    - Não depende de UI, notebooks ou frameworks externos

Este pacote existe para garantir **execução determinística,
previsível e auditável** de pipelines.
"""

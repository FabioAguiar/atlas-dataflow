# src/atlas_dataflow/__init__.py
"""
Atlas DataFlow — framework contract-driven para pipelines analíticos e de ML.

Este pacote raiz define o namespace público do Atlas DataFlow, um
framework projetado para construção de pipelines determinísticos,
rastreáveis e orientados a contrato.

Princípios centrais:
    - O pipeline é um DAG explícito de Steps canônicos
    - A execução é determinística e reprodutível
    - Configuração, contrato, execução e resultados são responsabilidades separadas
    - Rastreabilidade forense é um requisito de primeira classe

Arquitetura em alto nível:
    - core.config       → carregamento, merge e hashing de configuração
    - core.pipeline     → protocolos, contexto de execução e registro de Steps
    - core.engine       → planejamento (DAG) e execução do pipeline
    - core.traceability → Manifest e Event Log para auditoria e rastreabilidade

Nota importante:
    Este pacote não depende de notebooks, frameworks de UI ou ferramentas
    externas de orquestração. Notebooks e interfaces atuam apenas como
    adapters narrativos ou de apresentação.

Limites explícitos:
    - Não define Steps concretos de domínio
    - Não executa pipelines automaticamente
    - Não contém lógica específica de negócio ou ML

Este módulo existe para estabelecer o contrato conceitual e o namespace
do Atlas DataFlow, servindo como ponto de entrada lógico do framework.
"""
# src/atlas_dataflow/__init__.py
from .notebook_ui import render_payload, RenderResult

__all__ = ["render_payload", "RenderResult", "notebook_ui"]

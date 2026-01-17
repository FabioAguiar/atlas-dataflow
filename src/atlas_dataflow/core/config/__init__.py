# src/atlas_dataflow/core/config/__init__.py

"""
Camada de configuração do Atlas DataFlow.

Este pacote contém as estruturas e utilitários responsáveis por carregar,
mesclar, validar estruturalmente e identificar configurações de execução
do Atlas DataFlow.

A configuração no Atlas DataFlow é:
    - declarativa
    - determinística
    - explicitamente versionável
    - separada do contrato semântico

Responsabilidades do pacote:
    - Carregamento de arquivos de configuração (defaults + overrides locais)
    - Resolução de configuração final via deep-merge determinístico
    - Validação estrutural básica da configuração
    - Geração de hash canônico para rastreabilidade

Princípios fundamentais:
    - Configuração não contém lógica de domínio
    - Nenhuma heurística implícita durante merge
    - Overrides são sempre explícitos
    - A mesma entrada sempre produz a mesma configuração final

Invariantes:
    - A configuração final é um dicionário puro (dict)
    - A estrutura resultante é determinística
    - Conflitos estruturais são tratados como erro

Limites explícitos:
    - Não valida semântica de domínio
    - Não executa pipeline
    - Não interage com Engine ou Steps diretamente
    - Não depende de UI ou notebooks

Este pacote existe para garantir previsibilidade,
rastreabilidade e segurança na resolução de configuração.
"""

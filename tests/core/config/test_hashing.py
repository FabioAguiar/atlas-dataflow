# tests/config/test_hashing.py
"""
Testes do hashing de configuração.

Este módulo valida o comportamento da função responsável por gerar
um identificador determinístico da configuração resolvida, usado
para rastreabilidade e controle forense de execuções no Atlas DataFlow.

Os testes asseguram que:
- alterações na configuração produzem hashes diferentes
- configurações equivalentes produzem o mesmo hash
- o hash é determinístico e independente da ordem das chaves
- o algoritmo utilizado corresponde ao SHA-256 do JSON canônico

Decisões arquiteturais:
    - O hash representa a identidade semântica da configuração
    - A serialização em JSON canônico é obrigatória antes do hashing
    - O algoritmo de hashing é fixo (SHA-256)
    - O resultado é uma string hexadecimal de tamanho estável

Invariantes:
    - O hash retornado possui 64 caracteres
    - O hash é reprodutível entre execuções
    - O cálculo não depende de estado externo ou ambiente

Limites explícitos:
    - Não valida hashing de contratos
    - Não valida persistência ou uso do hash em cache
    - Não valida integração com Manifest ou Engine

Este módulo existe para garantir determinismo,
rastreabilidade e confiança na identificação de configurações.
"""

import json
import hashlib
import pytest

try:
    from atlas_dataflow.core.config.hashing import compute_config_hash
except Exception as e:  # noqa: BLE001
    compute_config_hash = None
    _IMPORT_ERR = e
else:
    _IMPORT_ERR = None


def _canonical_json_bytes(obj: dict) -> bytes:
    """
    Converte um dicionário em sua representação JSON canônica em bytes.

    Esta função produz uma serialização JSON determinística, usada
    exclusivamente nos testes como referência explícita para validar
    o comportamento de `compute_config_hash`.

    Decisões arquiteturais:
        - As chaves são ordenadas (`sort_keys=True`)
        - Não há espaços ou formatação extra (`separators=(",", ":")`)
        - A codificação utilizada é UTF-8
        - A serialização não depende de locale ou estado externo

    Invariantes:
        - A mesma estrutura de dicionário sempre gera os mesmos bytes
        - A ordem original das chaves no dicionário não afeta o resultado
        - O retorno é sempre um objeto `bytes`

    Limites explícitos:
        - Não valida serialização de tipos não suportados por JSON
        - Não deve ser usada fora do contexto de testes
        - Não implementa lógica de hashing

    Usado para garantir:
        - Comparação exata com a política de hashing do core
        - Determinismo nos testes de hashing
        - Clareza explícita da definição de “JSON canônico”
    """
    s = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return s.encode("utf-8")


def _require_imports():
    """
    Garante que o módulo de hashing de configuração esteja disponível para os testes.

    Esta função atua como uma pré-condição explícita para os testes de
    hashing de configuração, falhando imediatamente quando a função
    canônica `compute_config_hash` não pode ser importada.

    Decisões arquiteturais:
        - Falha antecipada e explícita quando o contrato de hashing está ausente
        - Mensagem de erro descreve claramente a política esperada
          (SHA-256 sobre JSON canônico)
        - Evita falhas indiretas ou mensagens pouco informativas nos testes

    Invariantes:
        - Se o módulo existe, a função não produz efeitos colaterais
        - Se o módulo está ausente, o teste falha imediatamente
        - Não tenta fallback nem implementação alternativa

    Limites explícitos:
        - Não valida o comportamento do hashing
        - Não executa serialização nem cálculo de hash
        - Não substitui testes funcionais de determinismo e integridade

    Usado para garantir:
        - Alinhamento entre testes e o contrato de hashing de configuração
        - Feedback claro durante desenvolvimento incremental
        - Cumprimento explícito da política de identificação semântica
    """
    if _IMPORT_ERR is not None:
        pytest.fail(
            "Missing hashing module. Implement:\n"
            "- src/atlas_dataflow/core/config/hashing.py (compute_config_hash)\n"
            "Policy expected: SHA-256 of canonical JSON serialization.\n"
            f"Import error: {_IMPORT_ERR}"
        )


def test_hash_is_deterministic():
    """
    Verifica que o hash da configuração é determinístico e independente da ordem das chaves.

    Este teste valida que a função `compute_config_hash` produz o mesmo
    valor de hash para configurações semanticamente idênticas, mesmo
    quando a ordem das chaves no dicionário difere.

    Decisões arquiteturais:
        - A configuração é convertida para JSON canônico antes do hashing
        - A ordenação de chaves é estável e não depende da entrada original
        - O hash gerado é sempre uma string hexadecimal

    Invariantes:
        - Configurações equivalentes produzem o mesmo hash
        - O hash retornado é uma string
        - O hash possui comprimento fixo de 64 caracteres (SHA-256)

    Limites explícitos:
        - Não valida comportamento para tipos não serializáveis
        - Não valida impacto de mudanças fora da configuração
        - Não valida integração com Manifest ou Engine

    Usado para garantir:
        - Determinismo do hashing de configuração
        - Reprodutibilidade entre execuções
        - Confiabilidade do hash como identificador semântico
    """
    _require_imports()
    cfg = {"b": 2, "a": 1}
    h1 = compute_config_hash(cfg)
    h2 = compute_config_hash({"a": 1, "b": 2})
    assert h1 == h2
    assert isinstance(h1, str)
    assert len(h1) == 64


def test_hash_matches_sha256_of_canonical_json():
    """
    Verifica que o hash da configuração corresponde ao SHA-256 do JSON canônico.

    Este teste valida que a função `compute_config_hash` calcula o hash
    exatamente como o SHA-256 aplicado sobre a representação JSON
    canônica da configuração.

    Decisões arquiteturais:
        - A configuração é serializada em JSON canônico antes do hashing
        - A ordenação de chaves é estável e determinística
        - O algoritmo de hashing utilizado é SHA-256

    Invariantes:
        - O hash gerado é determinístico para a mesma configuração
        - O valor do hash corresponde exatamente ao SHA-256 do JSON canônico
        - O cálculo do hash não depende da ordem original das chaves no dicionário

    Limites explícitos:
        - Não valida compatibilidade com outros algoritmos de hash
        - Não valida uso do hash em persistência ou cache
        - Não valida impacto de alterações fora da configuração

    Usado para garantir:
        - Conformidade do hashing com o contrato definido
        - Reprodutibilidade e rastreabilidade forense
        - Segurança na identificação única de configurações
    """
    _require_imports()
    cfg = {"engine": {"fail_fast": True, "log_level": "INFO"}, "steps": {"train": {"enabled": True}}}
    expected = hashlib.sha256(_canonical_json_bytes(cfg)).hexdigest()
    got = compute_config_hash(cfg)
    assert got == expected


def test_hash_changes_on_override():
    """
    Verifica que alterações na configuração resultam em hashes diferentes.

    Este teste valida que a função `compute_config_hash` reflete mudanças
    semânticas na configuração, produzindo valores de hash distintos
    quando o conteúdo da configuração é alterado.

    Decisões arquiteturais:
        - O hash representa a identidade semântica da configuração
        - Qualquer mudança de valor relevante deve alterar o hash
        - O algoritmo de hashing é determinístico para o mesmo conteúdo

    Invariantes:
        - Configurações com valores diferentes produzem hashes diferentes
        - Configurações idênticas produzem o mesmo hash
        - O cálculo do hash não depende de estado externo

    Limites explícitos:
        - Não valida o algoritmo específico de hashing
        - Não valida ordenação de chaves isoladamente
        - Não valida persistência ou uso do hash em outros componentes

    Usado para garantir:
        - Rastreabilidade correta de mudanças de configuração
        - Segurança contra reutilização indevida de resultados
        - Base confiável para identificação forense de runs
    """
    _require_imports()
    base = {"a": 1, "b": 2}
    changed = {"a": 1, "b": 3}
    assert compute_config_hash(base) != compute_config_hash(changed)

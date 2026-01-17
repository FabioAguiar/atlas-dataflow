# src/atlas_dataflow/core/traceability/manifest.py
"""
Manifest v1 — rastreabilidade forense de execuções no Atlas DataFlow.

Este módulo define a estrutura e as operações canônicas do Manifest,
o artefato central de rastreabilidade do Atlas DataFlow.

O Manifest consolida, de forma determinística e auditável:
    - metadados da execução (run)
    - hashes semânticos de entradas (config e contract)
    - estado incremental dos Steps
    - Event Log ordenado de eventos explícitos

Princípios fundamentais:
    - Nenhum evento é emitido implicitamente
    - Toda mutação ocorre por chamadas explícitas da API
    - A ordem do Event Log reflete a ordem real de execução
    - O Manifest é serializável e reconstruível (round-trip)

Responsabilidades do módulo:
    - Definir a classe canônica `AtlasManifest`
    - Criar o Manifest inicial de uma execução
    - Registrar eventos explícitos no Event Log
    - Atualizar incrementalmente o estado de Steps
    - Persistir e restaurar o Manifest em JSON

Decisões arquiteturais:
    - UTC é o timezone canônico para todos os timestamps
    - O formato de persistência é JSON determinístico
    - Steps e eventos iniciam vazios
    - O Manifest é independente de engine, pipeline, UI ou notebooks

Invariantes:
    - `events` é sempre uma lista ordenada
    - `steps` é sempre um dicionário indexado por step_id
    - Nenhuma mutação ocorre fora das funções explícitas
    - A estrutura é compatível com inspeção forense

Limites explícitos:
    - Não executa pipeline
    - Não decide políticas de execução (fail-fast, skip)
    - Não valida semântica de domínio
    - Não realiza migração de versões de schema

Este módulo existe para garantir rastreabilidade forense,
auditoria confiável e reprodutibilidade das execuções.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple


def _ensure_tzaware_utc(dt: datetime) -> datetime:
    """
    Normaliza um timestamp para timezone-aware em UTC.

    Esta função utilitária garante que o `datetime` fornecido esteja
    associado explicitamente ao timezone UTC. Caso o timestamp seja
    timezone-naive, o UTC é atribuído; caso já possua timezone, ele é
    convertido para UTC.

    Decisões arquiteturais:
        - UTC é o timezone canônico do Atlas DataFlow
        - Timestamps timezone-naive são assumidos como UTC
        - A normalização é explícita e determinística

    Invariantes:
        - O valor retornado é sempre timezone-aware
        - O timezone do retorno é sempre UTC
        - O instante temporal representado é preservado quando possível

    Limites explícitos:
        - Não valida se o timestamp original deveria ter outro timezone
        - Não registra eventos
        - Não deve ser exposta como API pública

    Args:
        dt (datetime): Timestamp a ser normalizado.

    Returns:
        datetime: Timestamp timezone-aware normalizado para UTC.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    """
    Converte um timestamp para string ISO 8601 normalizada em UTC.

    Esta função utilitária garante que o `datetime` fornecido seja
    timezone-aware em UTC antes de convertê-lo para sua representação
    ISO 8601 em formato string.

    Decisões arquiteturais:
        - O timestamp é normalizado para UTC
        - O formato de saída é ISO 8601 padrão
        - A conversão é determinística

    Invariantes:
        - O valor retornado representa um timestamp UTC
        - A saída é sempre uma string
        - O resultado é consistente para o mesmo instante temporal

    Limites explícitos:
        - Não valida semântica do timestamp
        - Não registra eventos
        - Não deve ser exposta como API pública

    Args:
        dt (datetime): Timestamp a ser convertido.

    Returns:
        str: Representação ISO 8601 do timestamp em UTC.
    """
    return _ensure_tzaware_utc(dt).isoformat()


def _ms_between(start: datetime, end: datetime) -> int:
    """
    Calcula a duração em milissegundos entre dois timestamps.

    Esta função utilitária retorna a diferença temporal entre `start`
    e `end`, normalizando ambos para timestamps UTC timezone-aware
    antes do cálculo.

    O valor retornado é sempre não negativo, protegendo contra
    inconsistências de ordenação temporal.

    Decisões arquiteturais:
        - Ambos os timestamps são normalizados para UTC
        - A duração é expressa em milissegundos inteiros
        - Valores negativos são truncados para zero

    Invariantes:
        - O valor retornado é sempre >= 0
        - A função é determinística para os mesmos inputs
        - O resultado independe do timezone original dos datetimes

    Limites explícitos:
        - Não valida se `end` ocorre após `start`
        - Não registra eventos
        - Não deve ser exposta como API pública

    Args:
        start (datetime): Timestamp inicial.
        end (datetime): Timestamp final.

    Returns:
        int: Duração em milissegundos entre `start` e `end`.
    """
    s = _ensure_tzaware_utc(start)
    e = _ensure_tzaware_utc(end)
    return max(0, int((e - s).total_seconds() * 1000))


@dataclass
class AtlasManifest:
    """
    Manifest v1 — registro forense de uma execução de pipeline.

    Esta classe representa a estrutura canônica do Manifest no Atlas DataFlow,
    responsável por consolidar informações de execução, entradas semânticas,
    estado de Steps e Event Log ordenado.

    O Manifest é projetado para ser:
        - determinístico
        - serializável em JSON
        - reconstruível via round-trip
        - independente de engine, pipeline ou UI

    Campos principais:
        - run: metadados da execução (run_id, started_at, atlas_version)
        - inputs: hashes semânticos de configuração e contrato
        - steps: estado incremental de cada Step
        - events: Event Log ordenado de eventos explícitos

    Decisões arquiteturais:
        - O Manifest não emite eventos implicitamente
        - Steps e eventos são atualizados apenas por chamadas explícitas da API
        - A estrutura é compatível com persistência em JSON
        - O schema é mínimo e orientado a rastreabilidade

    Invariantes:
        - `steps` é sempre um dicionário indexado por step_id
        - `events` é sempre uma lista ordenada
        - A estrutura completa é serializável

    Limites explícitos:
        - Não executa pipeline
        - Não decide políticas de execução
        - Não valida semântica de domínio
        - Não realiza persistência automaticamente
    """

    run: Dict[str, Any]
    inputs: Dict[str, Any]
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """
        Converte o Manifest para sua representação em dicionário.

        Esta função produz uma cópia profunda e serializável da estrutura
        do Manifest, adequada para persistência em JSON ou inspeção externa.

        Decisões arquiteturais:
            - Retorna apenas tipos serializáveis
            - Evita vazamento de referências internas
            - Preserva exatamente o conteúdo semântico do Manifest

        Invariantes:
            - O dicionário retornado é independente do estado interno
            - Alterações no retorno não afetam o Manifest em memória

        Limites explícitos:
            - Não valida conteúdo
            - Não aplica normalização ou migração de schema

        Returns:
            Dict[str, Any]: Representação serializável do Manifest.
        """
        return {
            "run": dict(self.run),
            "inputs": dict(self.inputs),
            "steps": {k: dict(v) for k, v in self.steps.items()},
            "events": [dict(e) for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AtlasManifest":
        """
        Reconstrói um Manifest a partir de sua representação em dicionário.

        Este método cria uma nova instância de `AtlasManifest` a partir de
        um dicionário previamente serializado, garantindo compatibilidade
        com o round-trip via `to_dict`.

        Decisões arquiteturais:
            - Campos ausentes são inicializados com valores vazios
            - A reconstrução é permissiva e estrutural
            - Não há validação semântica implícita

        Invariantes:
            - O Manifest reconstruído é funcionalmente equivalente ao original
            - A estrutura resultante é consistente com o Manifest v1

        Limites explícitos:
            - Não valida schema ou versão
            - Não executa migração de dados
            - Não registra eventos automaticamente

        Args:
            data (Dict[str, Any]): Dicionário serializado do Manifest.

        Returns:
            AtlasManifest: Nova instância reconstruída a partir do dicionário.
        """
        return cls(
            run=dict(data.get("run", {})),
            inputs=dict(data.get("inputs", {})),
            steps={k: dict(v) for k, v in (data.get("steps", {}) or {}).items()},
            events=[dict(e) for e in (data.get("events", []) or [])],
        )


def create_manifest(
    *,
    run_id: str,
    started_at: datetime,
    atlas_version: str,
    config_hash: str,
    contract_hash: str,
) -> AtlasManifest:
    """
    Cria o Manifest inicial de uma execução (Manifest v1).

    Esta função constrói o Manifest canônico no início de uma run,
    inicializando metadados de execução, hashes de entrada e estruturas
    vazias para Steps e Event Log.

    ⚠️ Importante: esta função **não emite eventos implicitamente**.
    O Event Log inicia vazio e só é preenchido por chamadas explícitas
    a `add_event`, `step_started`, `step_finished` ou `step_failed`.

    Decisões arquiteturais:
        - A criação do Manifest é explícita e determinística
        - O timestamp de início é normalizado para UTC timezone-aware
        - Steps e eventos iniciam vazios
        - O Manifest é independente de engine e pipeline

    Invariantes:
        - `events` inicia como lista vazia
        - `steps` inicia como dicionário vazio
        - `run.run_id`, `run.started_at` e `run.atlas_version` estão sempre presentes
        - `inputs.config_hash` e `inputs.contract_hash` estão sempre presentes

    Limites explícitos:
        - Não registra eventos automaticamente (ex.: run_started)
        - Não valida semântica de hashes ou versão
        - Não executa persistência
        - Não inicia execução de Steps

    Args:
        run_id (str): Identificador único da execução.
        started_at (datetime): Timestamp de início da execução.
        atlas_version (str): Versão do Atlas DataFlow utilizada.
        config_hash (str): Hash semântico da configuração resolvida.
        contract_hash (str): Hash semântico do contrato utilizado.

    Returns:
        AtlasManifest: Instância inicializada do Manifest v1.
    """
    started_at = _ensure_tzaware_utc(started_at)

    return AtlasManifest(
        run={
            "run_id": run_id,
            "started_at": _iso(started_at),
            "atlas_version": atlas_version,
        },
        inputs={
            "config_hash": config_hash,
            "contract_hash": contract_hash,
        },
        steps={},
        events=[],
    )


def add_event(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    event_type: str,
    ts: datetime,
    step_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Adiciona um evento explícito ao Event Log do Manifest.

    Esta função registra um evento no Manifest, preservando a ordem de
    chamada como ordem canônica do Event Log. Eventos são sempre
    adicionados explicitamente e nunca inferidos automaticamente.

    O evento pode estar associado a um Step específico ou a um evento
    de escopo global (ex.: início de run).

    Decisões arquiteturais:
        - Eventos são adicionados apenas por chamada explícita da API
        - A ordem do Event Log reflete a ordem de chamada das funções
        - O timestamp é normalizado para UTC timezone-aware
        - O payload é opcional e livre de validação semântica

    Invariantes:
        - Cada chamada adiciona exatamente um evento ao Event Log
        - O campo `event_type` está sempre presente
        - O campo `timestamp` está sempre presente em formato ISO
        - Eventos não são reordenados ou deduplicados

    Limites explícitos:
        - Não valida semântica do `event_type`
        - Não altera estado de Steps
        - Não decide políticas de execução
        - Não executa persistência automaticamente

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest a ser atualizado.
        event_type (str): Tipo semântico do evento (ex.: run_started, step_started).
        ts (datetime): Timestamp do evento.
        step_id (Optional[str]): Identificador do Step associado, se aplicável.
        payload (Optional[Dict[str, Any]]): Dados adicionais associados ao evento.

    Returns:
        None
    """
    ts = _ensure_tzaware_utc(ts)
    m = manifest if isinstance(manifest, AtlasManifest) else AtlasManifest.from_dict(manifest)

    ev: Dict[str, Any] = {"event_type": event_type, "timestamp": _iso(ts)}
    if step_id is not None:
        ev["step_id"] = step_id
    if payload is not None:
        ev["payload"] = payload

    m.events.append(ev)

    if not isinstance(manifest, AtlasManifest):
        manifest.clear()
        manifest.update(m.to_dict())


def _get_manifest(manifest: Union[AtlasManifest, Dict[str, Any]]) -> Tuple[AtlasManifest, bool]:
    """
    Normaliza a entrada do Manifest para uma instância de `AtlasManifest`.

    Esta função interna aceita tanto uma instância de `AtlasManifest`
    quanto sua representação em dicionário, retornando sempre uma
    instância canônica de `AtlasManifest` para uso interno.

    O valor booleano retornado indica se a entrada original era um
    dicionário, permitindo que o chamador sincronize as alterações
    de volta para o objeto original quando necessário.

    Decisões arquiteturais:
        - A API pública aceita Manifest como objeto ou dict
        - A normalização ocorre de forma explícita e controlada
        - A reconstrução do Manifest delega para `AtlasManifest.from_dict`

    Invariantes:
        - O primeiro valor retornado é sempre um `AtlasManifest`
        - O segundo valor indica corretamente se houve conversão a partir de dict
        - Nenhuma mutação ocorre no objeto de entrada original neste ponto

    Limites explícitos:
        - Não valida semântica do conteúdo do Manifest
        - Não realiza persistência ou registro de eventos
        - Não deve ser exposta como API pública

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest como objeto
            ou dicionário serializável.

    Returns:
        Tuple[AtlasManifest, bool]: Tupla contendo:
            - a instância normalizada de `AtlasManifest`
            - flag indicando se a entrada original era um dicionário
    """
    if isinstance(manifest, AtlasManifest):
        return manifest, False
    return AtlasManifest.from_dict(manifest), True


def step_started(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    kind: str,
    ts: datetime,
) -> None:
    """
    Registra o início de execução de um Step no Manifest.

    Esta função inicializa ou atualiza o estado de um Step no Manifest,
    marcando-o como em execução (`running`) e registrando o timestamp
    de início normalizado em UTC.

    Além da atualização do estado do Step, um evento explícito
    `step_started` é adicionado ao Event Log do Manifest.

    Decisões arquiteturais:
        - O início do Step é registrado explicitamente por chamada da API
        - O timestamp é normalizado para UTC timezone-aware
        - O estado do Step é criado sob demanda, se ainda não existir
        - Um evento de início é sempre registrado no Event Log

    Invariantes:
        - O Step passa a existir no Manifest após a chamada
        - O status do Step é definido como `"running"`
        - O campo `started_at` está sempre presente após o registro
        - O Event Log preserva a ordem de chamada dos eventos

    Limites explícitos:
        - Não executa validação semântica do tipo (`kind`)
        - Não altera o status de outros Steps
        - Não decide políticas de execução (fail-fast, skip)
        - Não infere dependências ou ordem de execução

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest a ser atualizado.
        step_id (str): Identificador do Step iniciado.
        kind (str): Tipo semântico do Step (ex.: diagnostic, train, audit).
        ts (datetime): Timestamp de início do Step.

    Returns:
        None
    """
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    m.steps.setdefault(step_id, {})
    m.steps[step_id].update(
        {
            "step_id": step_id,
            "kind": kind,
            "status": "running",
            "started_at": _iso(ts),
        }
    )

    add_event(m, event_type="step_started", ts=ts, step_id=step_id, payload={"kind": kind})

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def step_finished(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    ts: datetime,
    result: Dict[str, Any],
) -> None:
    """
    Registra a conclusão de execução de um Step no Manifest.

    Esta função atualiza incrementalmente o estado de um Step após sua
    execução, registrando status final, timestamps, duração e metadados
    resultantes (métricas, warnings e artefatos).

    Além da atualização do estado do Step, um evento explícito
    `step_finished` é adicionado ao Event Log do Manifest.

    Decisões arquiteturais:
        - A conclusão do Step é registrada explicitamente por chamada da API
        - O timestamp é normalizado para UTC timezone-aware
        - A duração é calculada a partir de `started_at` quando disponível
        - Campos opcionais ausentes são normalizados para valores vazios

    Invariantes:
        - O Step permanece registrado no Manifest após a conclusão
        - O status final reflete o valor fornecido em `result`
        - O campo `finished_at` está sempre presente
        - O campo `duration_ms` é sempre numérico e não negativo
        - O Event Log preserva a ordem de chamada dos eventos

    Limites explícitos:
        - Não executa validação semântica do resultado
        - Não altera o status de outros Steps
        - Não decide políticas de execução (fail-fast, skip)
        - Não infere status além do fornecido em `result`

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest a ser atualizado.
        step_id (str): Identificador do Step finalizado.
        ts (datetime): Timestamp de finalização do Step.
        result (Dict[str, Any]): Resultado da execução do Step, contendo
            status, summary, metrics, warnings e artifacts.

    Returns:
        None
    """
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    s = m.steps.setdefault(step_id, {"step_id": step_id})
    started_iso = s.get("started_at")
    if started_iso:
        try:
            started_dt = datetime.fromisoformat(started_iso)
        except Exception:
            started_dt = ts
    else:
        started_dt = ts

    status = result.get("status", "success")
    s.update(
        {
            "status": status,
            "finished_at": _iso(ts),
            "duration_ms": _ms_between(started_dt, ts),
            "summary": result.get("summary"),
            "metrics": result.get("metrics", {}) or {},
            "warnings": result.get("warnings", []) or [],
            "artifacts": result.get("artifacts", {}) or {},
        }
    )

    add_event(
        m,
        event_type="step_finished",
        ts=ts,
        step_id=step_id,
        payload={"status": status, "duration_ms": s.get("duration_ms", 0)},
    )

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def step_failed(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    ts: datetime,
    error: str,
) -> None:
    """
    Registra a falha de execução de um Step no Manifest.

    Esta função atualiza incrementalmente o estado de um Step,
    marcando-o como FAILED, registrando o timestamp de finalização
    e associando a mensagem de erro correspondente.

    Além da atualização do estado do Step, um evento explícito
    `step_failed` é adicionado ao Event Log do Manifest.

    Decisões arquiteturais:
        - Falhas são registradas explicitamente por chamada da API
        - O timestamp é normalizado para UTC timezone-aware
        - A atualização do estado do Step é incremental
        - Um evento de falha é sempre registrado no Event Log

    Invariantes:
        - O Step permanece registrado no Manifest após a falha
        - O status final do Step é `"failed"`
        - O campo `error` está presente quando ocorre falha
        - O Event Log preserva a ordem de chamada dos eventos

    Limites explícitos:
        - Não executa lógica de retry ou recuperação
        - Não altera o status de outros Steps
        - Não valida semântica da mensagem de erro
        - Não decide políticas de execução (fail-fast, skip)

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest a ser atualizado.
        step_id (str): Identificador do Step que falhou.
        ts (datetime): Timestamp de ocorrência da falha.
        error (str): Descrição textual do erro ocorrido.

    Returns:
        None
    """
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    s = m.steps.setdefault(step_id, {"step_id": step_id})
    s.update(
        {
            "status": "failed",
            "finished_at": _iso(ts),
            "error": error,
        }
    )

    add_event(m, event_type="step_failed", ts=ts, step_id=step_id, payload={"error": error})

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def save_manifest(manifest: Union[AtlasManifest, Dict[str, Any]], path: Path) -> None:
    """
    Persiste um Manifest em disco no formato JSON.

    Esta função salva um Manifest de execução em sua representação
    serializável, garantindo persistência determinística e compatível
    com o round-trip via `load_manifest`.

    O Manifest pode ser fornecido tanto como:
    - instância de `AtlasManifest`, ou
    - dicionário já serializável equivalente à sua forma canônica

    Decisões arquiteturais:
        - O formato de persistência é JSON
        - A ordenação de chaves é estável (`sort_keys=True`)
        - A escrita é legível (indentação) sem afetar o determinismo
        - Diretórios intermediários são criados automaticamente

    Invariantes:
        - O conteúdo persistido reflete exatamente o estado do Manifest fornecido
        - A serialização é determinística para o mesmo conteúdo
        - A função não altera o Manifest em memória

    Limites explícitos:
        - Não valida semântica do conteúdo do Manifest
        - Não aplica versionamento ou migração de schema
        - Não registra eventos de persistência automaticamente

    Args:
        manifest (Union[AtlasManifest, Dict[str, Any]]): Manifest a ser persistido.
        path (Path): Caminho do arquivo JSON de destino.

    Returns:
        None

    Raises:
        OSError: Em caso de falha ao criar diretórios ou escrever o arquivo.
        TypeError: Se o conteúdo do Manifest não for serializável em JSON.
    """
    data = manifest.to_dict() if isinstance(manifest, AtlasManifest) else manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")



def load_manifest(path: Path) -> AtlasManifest:
    """
    Carrega um Manifest persistido a partir de um arquivo JSON.

    Esta função restaura um `AtlasManifest` a partir de sua representação
    serializada em JSON, garantindo round-trip determinístico entre
    persistência e execução.

    Decisões arquiteturais:
        - O formato de persistência é JSON
        - A desserialização delega a reconstrução semântica ao método
          `AtlasManifest.from_dict`
        - Nenhuma validação implícita adicional é aplicada além do contrato
          definido pelo schema do Manifest

    Invariantes:
        - O Manifest carregado reflete exatamente o conteúdo do arquivo
        - A estrutura restaurada é compatível com a API do Manifest v1
        - A função não produz efeitos colaterais além da leitura do arquivo

    Limites explícitos:
        - Não valida existência prévia do arquivo (propaga exceções de I/O)
        - Não valida compatibilidade entre versões diferentes de schema
        - Não executa migração ou normalização de dados

    Args:
        path (Path): Caminho para o arquivo JSON contendo o Manifest persistido.

    Returns:
        AtlasManifest: Instância reconstruída do Manifest a partir do JSON.

    Raises:
        OSError: Em caso de falha de leitura do arquivo.
        json.JSONDecodeError: Em caso de JSON inválido.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return AtlasManifest.from_dict(data)

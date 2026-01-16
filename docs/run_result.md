# Atlas DataFlow — RunResult Canonical Specification

## 1. Propósito do Documento

Este documento define a **estrutura canônica do RunResult**, o resultado global de uma execução do pipeline no Atlas DataFlow.

O RunResult representa a **visão consolidada do run**, agregando status, métricas, resultados por Step e metadados necessários para:
- rastreabilidade
- auditoria
- consumo por notebook/UI
- integração com APIs e CLIs
- testes E2E e automações

Este documento é **fonte de verdade** para qualquer consumidor do resultado de execução.

---

## 2. Papel do RunResult no Sistema

O RunResult é o **produto final do Engine**.

Ele não:
- executa lógica
- altera estado
- toma decisões

Ele:
- descreve *o que aconteceu*
- consolida *o estado final*
- referencia *evidências rastreáveis*

---

## 3. Estrutura Canônica do RunResult

O RunResult deve possuir, no mínimo, os seguintes campos:

```yaml
run_id: string
status: success | failed | partial
started_at: datetime
finished_at: datetime
duration_ms: int

summary: string

steps:
  - step_id: string
    kind: string
    status: success | failed | skipped | blocked
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    summary: string
    warnings: []
    artifacts: []

metrics:
  key: value

artifacts:
  - name: string
    path: string
    hash: string
    type: string

references:
  manifest_path: string
  config_hash: string
  contract_hash: string
```

---

## 4. Status Global do Run

### 4.1 Status possíveis

- `success`
  - todos os Steps críticos finalizaram com sucesso
- `failed`
  - ao menos um Step crítico falhou
- `partial`
  - execução completou, mas:
    - houve falhas não críticas, ou
    - houve Steps `skipped` esperados

A definição de *crítico* pode evoluir via policy futura.

---

## 5. Agregação de Steps

- A lista `steps` deve conter **todos os Steps planejados**
- Steps não executados devem aparecer com status `blocked` ou `skipped`
- A ordem da lista deve refletir a **ordem real de execução**, não a ordem declarativa

---

## 6. Métricas Globais

O campo `metrics` deve conter:
- métricas agregadas do run
- métricas do modelo campeão (quando aplicável)
- contadores relevantes (ex.: número de steps executados)

Regras:
- métricas detalhadas por Step permanecem nos payloads individuais
- RunResult agrega apenas o que é relevante globalmente

---

## 7. Artefatos Globais

O campo `artifacts` deve referenciar:
- modelos exportados
- preprocessadores
- bundles de inferência
- relatórios finais

Todos os artefatos listados devem:
- existir no filesystem
- possuir hash
- estar referenciados no manifest

---

## 8. Referências Cruzadas

O RunResult deve sempre conter:

- path do `manifest.json`
- hash do config efetivo
- hash do contrato efetivo

Isso garante:
- reprodutibilidade
- auditoria cruzada
- consistência com APIs de inferência

---

## 9. Serialização e Consumo

O RunResult deve ser:
- serializável em JSON
- facilmente renderizável no notebook
- consumível por APIs REST/CLI
- estável entre versões compatíveis

Qualquer quebra estrutural exige:
- bump de versão
- documentação explícita

---

## 10. Testes Obrigatórios

O projeto deve possuir testes para:

- estrutura mínima válida do RunResult
- consistência de status global vs status dos Steps
- presença de referências obrigatórias
- serialização/deserialização sem perda

---

## 11. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/engine.md`
- `docs/traceability.md`
- `docs/pipeline_elements.md`
- `docs/config.md`
- `docs/contract.md`

---

## 12. Regra de Ouro

Se um consumidor:
- não consegue entender o que aconteceu em um run,
- não consegue rastrear artefatos,
- não consegue reproduzir a execução,

**então o RunResult está incompleto.**

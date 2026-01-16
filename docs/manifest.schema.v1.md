# Atlas DataFlow — Manifest Schema v1 (Canonical)

## 1. Propósito do Documento

Este documento define o **schema formal do Manifest v1** do Atlas DataFlow.

O Manifest é o **registro forense canônico** de uma execução de pipeline e deve conter todas as informações necessárias para:
- auditoria técnica
- reprodutibilidade
- depuração
- consumo por notebook, APIs e CLIs
- validação automatizada (tests)

Este schema é **normativo**: qualquer implementação que não o siga deve ser considerada **incompatível**.

---

## 2. Princípios do Schema

1. **Append-only**
   - O Manifest cresce ao longo da execução.
   - Nenhuma informação registrada pode ser removida.

2. **Determinístico**
   - Mesmo pipeline + mesmo config + mesmo contrato → Manifest estruturalmente equivalente.

3. **Auditável**
   - Toda decisão, falha ou skip deve ser rastreável.

4. **Consumível**
   - Estrutura simples, serializável, compatível com JSON/YAML.

---

## 3. Estrutura Raiz do Manifest

```yaml
manifest_version: "1.0"

run:
  run_id: string
  status: success | failed | partial
  started_at: datetime
  finished_at: datetime
  duration_ms: int

system:
  atlas_version: string
  python_version: string
  platform: string

inputs:
  dataset:
    source: string
    checksum: string | null

config:
  effective_path: string | null
  hash: string

contract:
  effective_path: string | null
  hash: string

steps: []

events: []

artifacts: []

summary: string
```

---

## 4. Seção `steps`

Cada entrada em `steps` representa o **estado final** de um Step planejado.

```yaml
steps:
  - step_id: string
    kind: diagnostic | transform | train | evaluate | export
    status: pending | running | done | failed | skipped | blocked
    started_at: datetime | null
    finished_at: datetime | null
    duration_ms: int | null
    summary: string
    warnings:
      - string
    errors:
      - string
    metrics:
      key: value
    artifacts:
      - artifact_id: string
```

Regras:
- Todos os Steps planejados devem aparecer.
- Steps não executados devem possuir status `skipped` ou `blocked`.

---

## 5. Seção `events`

O **Event Log** registra eventos cronológicos ocorridos durante o run.

```yaml
events:
  - event_id: string
    event_type: run_started | step_started | step_finished | step_failed | step_skipped | run_finished
    timestamp: datetime
    step_id: string | null
    payload:
      key: value
```

Regras:
- Eventos devem estar ordenados por timestamp.
- Eventos de Step devem referenciar `step_id` válido.

---

## 6. Seção `artifacts`

Lista global de artefatos produzidos no run.

```yaml
artifacts:
  - artifact_id: string
    name: string
    type: model | preprocess | metrics | report | bundle | other
    path: string
    hash: string
    produced_by: step_id
```

Regras:
- Todo artefato deve estar associado a um Step.
- Todo artefato listado deve existir no filesystem.

---

## 7. Status Global do Run

### Regras de derivação

- `success`
  - nenhum Step crítico falhou

- `failed`
  - ao menos um Step crítico falhou

- `partial`
  - execução terminou
  - houve Steps `skipped` ou falhas não críticas

A definição de criticidade pode evoluir via policy futura.

---

## 8. Validações Obrigatórias

Qualquer Manifest v1 válido deve satisfazer:

- `manifest_version == "1.0"`
- `run.run_id` presente
- `run.started_at` presente
- `steps` não vazio
- todos `step_id` únicos
- `events` coerentes com `steps`
- todos `artifacts.produced_by` referenciam Step existente

---

## 9. Integração com Outros Documentos

Este schema deve ser usado em conjunto com:

- `docs/traceability.md`
- `docs/engine.md`
- `docs/run_result.md`
- `docs/pipeline_elements.md`
- `docs/config.md`
- `docs/contract.md`

---

## 10. Testes de Conformidade

O projeto deve possuir testes que validem:

- Manifest mínimo válido
- Manifest com falha de Step
- Manifest com skip
- Round-trip (serialize → deserialize)
- Detecção de schema inválido

---

## 11. Regra de Ouro

Se um dado:
- não cabe neste schema,
- não pode ser validado,
- não pode ser rastreado,

**ele não deve existir no Manifest do Atlas DataFlow.**

# 📄 export.inference_bundle — Bundle de Inferência Autocontido (v1)

## Visão Geral

Esta spec define o Step **export.inference_bundle v1** do **Atlas DataFlow**, responsável por
exportar um **bundle de inferência autocontido**, garantindo que modelos em produção sejam
**reprodutíveis, auditáveis e semanticamente compatíveis** com o pipeline de treino.

No Atlas, **inferência não depende do pipeline vivo**: todas as decisões relevantes devem
ser congeladas no momento do export.

---

## Objetivo

- Gerar um bundle único para inferência
- Congelar preprocess, modelo, contrato e metadados
- Garantir compatibilidade entre treino e inferência
- Permitir carregamento e uso isolado do bundle

---

## Natureza do Step

- **ID:** `export.inference_bundle`
- **Kind:** `export`
- **Milestone:** M6 — Deployment / Serving
- **Caráter:** Materialização de artefato

---

## Dependências

O Step depende semanticamente de:

- `evaluate.model_selection`
- `representation.preprocess`
- `ModelRegistry`
- `contract.internal.v1`

---

## Conteúdo do Bundle (v1)

O bundle deve conter, no mínimo:

- **preprocess**
  - pipeline treinado (ex.: ColumnTransformer)
- **model**
  - estimador treinado (campeão)
- **contract**
  - contrato interno congelado
- **metrics**
  - métricas finais do modelo campeão
- **metadata**
  - versões
  - seed
  - timestamps
  - hashes dos componentes

---

## Formato do Bundle

Formato padrão (v1):

- `joblib` (arquivo único)

Estrutura lógica interna:

```text
inference_bundle.joblib
 ├─ preprocess
 ├─ model
 ├─ contract
 ├─ metrics
 └─ metadata
```

---

## Interface de Inferência

O bundle carregado deve expor:

- `predict(payload)`
- `predict_proba(payload)` (quando suportado)

Regras:
- payload deve ser validado contra o **contrato congelado**
- falhas devem ser explícitas e estruturadas

---

## Payload Esperado (export)

```yaml
payload:
  bundle_path: string
  bundle_hash: string
  model_id: string
  contract_version: string
```

---

## Rastreabilidade

O Manifest deve registrar:

- hash do bundle
- referências dos artefatos incluídos
- versão do contrato
- métricas associadas
- localização do bundle

---

## Falhas Explícitas

O Step deve falhar quando:

- modelo campeão não existir
- preprocess não estiver disponível
- contrato não estiver disponível
- escrita do bundle falhar

---

## Testes Esperados

Os testes unitários devem cobrir:

- criação do bundle
- carregamento isolado
- inferência com payload válido
- falha para payload inválido
- preservação de métricas e metadados

---

## Fora de Escopo (v1)

- Serving HTTP
- Versionamento de bundles
- Canary / A-B testing
- Monitoramento em produção

---

## Evolução Futura

Possíveis extensões:

- Versionamento semântico do bundle
- Assinatura criptográfica
- Compatibilidade backward
- Integração com serviços de serving

---

## Referências

- `docs/spec/evaluate.model_selection.v1.md`
- `docs/spec/representation.preprocess.v1.md`
- `docs/spec/model_registry.v1.md`
- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

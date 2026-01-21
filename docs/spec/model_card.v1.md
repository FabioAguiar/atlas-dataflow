# 📄 model_card — Documentação Automática de Modelo (v1)

## Visão Geral

Esta spec define o **Model Card v1** do **Atlas DataFlow**, um documento Markdown
gerado **automaticamente** a partir das **fontes de verdade do pipeline**,
com o objetivo de garantir **transparência, rastreabilidade e governança**
na entrega de modelos para produção.

No Atlas, o Model Card **não é escrito manualmente**: ele é derivado
diretamente do **Manifest**, das **métricas finais** e do **contrato congelado**.

---

## Objetivo

- Gerar documentação padronizada do modelo
- Consolidar decisões de treino, avaliação e seleção
- Facilitar auditoria, revisão e handoff para produção
- Garantir determinismo do conteúdo

---

## Natureza do Artefato

- **Nome:** `model_card.md`
- **Tipo:** Documentação gerada
- **Milestone:** M6 — Deployment / Serving
- **Caráter:** Descritivo, não-executável

---

## Fontes de Verdade

O conteúdo do Model Card deve ser gerado **exclusivamente** a partir de:

- `manifest` final
- métricas de `evaluate.metrics`
- decisão de `evaluate.model_selection`
- contrato congelado (`contract.internal.v1`)
- metadata do bundle de inferência

Nenhuma informação pode ser inferida heurísticamente.

---

## Estrutura Canônica (v1)

O arquivo `model_card.md` deve conter, no mínimo, as seguintes seções:

```md
# Model Card

## Model Overview
## Training Data
## Input Contract
## Metrics
## Model Selection
## Limitations
## Execution Metadata
```

---

## Conteúdo das Seções

### 1) Model Overview
- `model_id`
- tipo do modelo
- hash do bundle de inferência
- versão do contrato

---

### 2) Training Data
- origem do dataset (via Manifest)
- período de execução
- observações relevantes (se existirem)

---

### 3) Input Contract
- lista de features
- tipos esperados
- colunas mandatórias/opcionais
- defaults (se aplicável)

---

### 4) Metrics
- métricas finais do modelo campeão
- confusion matrix (se aplicável)
- observação sobre `roc_auc` (quando existir)

---

### 5) Model Selection
- métrica alvo
- critério (maximize/minimize)
- ranking resumido
- justificativa objetiva da escolha

---

### 6) Limitations
- limitações conhecidas (ex.: dataset pequeno, classes desbalanceadas)
- esta seção pode ser parcialmente preenchida automaticamente

---

### 7) Execution Metadata
- run_id
- timestamps
- seed global
- versões relevantes (lib/modelo)

---

## Invariantes

- Conteúdo determinístico para Manifest fixo
- Todas as seções mínimas sempre presentes
- Formato Markdown válido
- Nenhuma mutação de artefatos existentes

---

## Falhas Explícitas

A geração do Model Card deve falhar quando:

- Manifest não existir
- métricas finais não estiverem disponíveis
- contrato não estiver disponível

---

## Testes Esperados

Os testes unitários devem cobrir:

- geração do arquivo
- presença de todas as seções mínimas
- coerência com Manifest e métricas
- determinismo do conteúdo

---

## Fora de Escopo (v1)

- Avaliação ética/fairness
- Explicabilidade (SHAP/LIME)
- Visualizações gráficas
- Publicação automática

---

## Evolução Futura

Possíveis extensões:

- Seção de fairness/bias
- Integração com explainability
- Model Card em formato JSON
- Publicação automática em registry

---

## Referências

- `docs/spec/export.inference_bundle.v1.md`
- `docs/spec/evaluate.metrics.v1.md`
- `docs/spec/evaluate.model_selection.v1.md`
- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

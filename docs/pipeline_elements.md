# 📘 Pipeline Elements — Catálogo Canônico do Atlas DataFlow

Este documento cataloga todos os **elementos canônicos do pipeline** do **Atlas DataFlow**,
organizados por tipo e milestone, servindo como **fonte única de verdade** para:

- quais Steps existem
- quais Builders existem
- qual o papel de cada elemento
- quais invariantes eles mantêm
- quais artefatos produzem ou consomem

Nenhum elemento fora deste catálogo deve existir sem documentação explícita.

---

## 🧱 Tipos de Elementos

- **Ingest (Step)** — entrada controlada de dados
- **Contract (Step)** — carregamento e validação declarativa de schema
- **Split (Step)** — separação determinística de datasets
- **Audit (Step)** — observação diagnóstica (não muta dados)
- **Transform (Step)** — transformação declarada e rastreável
- **Builder (Builder)** — construção explícita de representações e objetos canônicos
- **Train (Step)** — treinamento explícito de modelos
- **Evaluate (Step)** — avaliação e decisão baseada em métricas
- **Export (Step)** — empacotamento de artefatos finais
- **Report (Step)** — consolidação humana dos resultados

---

## ⭐ Pipeline E2E Mínimo (Canônico)

O **Pipeline E2E mínimo** representa o **menor conjunto de elementos**
necessário para validar o Atlas DataFlow como **sistema integrado e rastreável**.

Este pipeline é obrigatório para:
- testes E2E
- validação de reutilização do core
- garantia de rastreabilidade *full run*

### Sequência E2E mínima

1. `ingest.load`
2. `contract.load`
3. `contract.validate`
4. `split.train_test`
5. `representation.preprocess` (**Builder obrigatório**)
6. `train.single`
7. `evaluate.metrics`
8. `export.inference_bundle`
9. `report.generate`

⚠️ **Observação importante**  
`representation.preprocess` **não é um Step**.  
É um **Builder obrigatório**, executado explicitamente entre `split` e `train`.

---

## 🗂️ Milestone M5 — Modelagem & Avaliação

O Milestone M5 fecha o ciclo supervisionado do Atlas, indo da
**representação** até a **decisão final de modelo**, de forma:

- explícita
- determinística
- auditável
- comparável entre execuções

---

## 🔧 Builders

### `representation.preprocess` (Builder)

Constrói a representação canônica de features a partir do contrato.

- Usa exclusivamente o contrato como fonte de verdade
- Numéricas: scaler explícito
- Categóricas: encoder explícito
- Nenhuma inferência automática de colunas
- Persistido via `PreprocessStore`
- Consumido por todos os Steps de treino

**Artefatos produzidos:**
- `artifacts/preprocess.joblib`

---

## 🏋️ Training

### `train.single` (Step — kind: train)

Treinamento simples e determinístico de um único modelo.

- Parâmetros explícitos via config
- Seed explícita
- Sem busca de hiperparâmetros
- Serve como baseline confiável

**Artefatos produzidos:**
- modelo treinado
- métricas no Manifest

---

## 📊 Evaluation

### `evaluate.metrics` (Step — kind: evaluate)

Avaliação padronizada de modelos treinados.

**Métricas obrigatórias:**
- accuracy
- precision
- recall
- f1

**Condicional:**
- roc_auc (quando aplicável)

**Artefatos produzidos:**
- métricas serializadas
- registro no Manifest

---

## 📦 Export

### `export.inference_bundle` (Step — kind: export)

Empacota todos os artefatos necessários para inferência futura.

**Inclui:**
- preprocess persistido
- modelo treinado
- metadados de contrato

**Artefatos produzidos:**
- `artifacts/inference_bundle.joblib`

---

## 📝 Reporting

### `report.generate` (Step — kind: report)

Consolida a execução completa do pipeline em formato humano.

- Derivado exclusivamente do Manifest
- Sem lógica de negócio
- Pode gerar:
  - `report.md`
  - `report.pdf` (opcional)

**Artefatos produzidos:**
- `artifacts/report.md`
- (opcional) `artifacts/report.pdf`

---

## 🚦 Princípios Globais do Pipeline

- Nada é inferido automaticamente
- Toda decisão é:
  - declarada
  - rastreável
  - serializável
- Determinismo é obrigatório
- Builders são explícitos e auditáveis
- Steps são composáveis, mas nunca implícitos

---

## 📌 Regra de Ouro

Se um elemento:
- não estiver neste catálogo,
- não tiver papel explícito,
- não produzir artefatos rastreáveis,

**ele não existe oficialmente no Atlas DataFlow.**

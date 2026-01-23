# 📘 Pipeline Elements — Catálogo Canônico do Atlas DataFlow

Este documento cataloga todos os **elementos canônicos do pipeline** do **Atlas DataFlow**,
organizados por tipo e milestone, servindo como **fonte única de verdade** para:

- quais Steps existem
- qual o papel de cada Step
- quais invariantes eles mantêm
- quais artefatos produzem ou consomem

Nenhum Step fora deste catálogo deve existir sem documentação explícita.

---

## 🧱 Tipos de Elementos

- **Ingest** — entrada controlada de dados
- **Audit** — observação diagnóstica (não muta dados)
- **Transform** — transformação declarada e rastreável
- **Builder** — construção de representações e objetos canônicos
- **Train** — treinamento explícito de modelos
- **Evaluate** — avaliação e decisão baseada em métricas
- **Registry** — catálogos determinísticos (modelos, grids, etc.)
- **Persistence** — armazenamento de artefatos versionados

---

## 🗂️ Milestone M5 — Modelagem & Avaliação

O Milestone M5 fecha o ciclo supervisionado do Atlas, indo da
**representação** até a **decisão final de modelo campeão**, de forma:

- explícita
- determinística
- auditável
- comparável entre execuções

---

### 🔧 Builders & Registries

#### `representation.preprocess` (Builder)
Constrói o `ColumnTransformer` canônico a partir do contrato.

- Numéricas: scaler explícito
- Categóricas: encoder explícito
- Nenhuma inferência automática de colunas
- Usado por todos os Steps de treino

---

#### `ModelRegistry` (Registry)
Catálogo explícito de modelos suportados.

- Modelos iniciais:
  - Logistic Regression
  - Random Forest
  - KNN
- Define:
  - classe do estimador
  - parâmetros default
  - parâmetros expostos para UI
- Extensível via `register()`, sem inferência

---

#### `DefaultSearchGrids` (Registry)
Catálogo canônico de grids de busca por modelo.

- Grids conservadores e seguros
- Scoring explícito
- Estratégia de CV explícita e determinística
- Fonte padrão para `train.search`

---

### 🏋️ Training

#### `train.single` (Step — kind: train)
Treinamento simples e determinístico de um único modelo.

- Usa apenas `default params`
- Sem busca de hiperparâmetros
- Seed explícita
- Gera métricas padrão
- Serve como baseline confiável

**Artefatos produzidos:**
- `model.trained`
- métricas no Manifest

---

#### `train.search` (Step — kind: train)
Treinamento com busca explícita de hiperparâmetros.

- Suporta:
  - `GridSearchCV`
  - `RandomizedSearchCV`
- Nenhuma inferência automática de estratégia

**Fontes explícitas de grid (Grid Source):**
- `default` — via `DefaultSearchGrids`
- `paste` — grid fornecido diretamente na config
- `bank` — GridBank file-based (arquivo explícito)

**Determinismo:**
- seed explícita
- CV explícito
- scoring registrado

**Artefatos produzidos:**
- `model.best_estimator`
- resumo serializável de `cv_results_`
- registro completo no Manifest (grid source, scoring, cv, seed)

---

### 📊 Evaluation

#### `evaluate.metrics` (Step — kind: evaluate)
Avaliação padronizada de modelos treinados.

**Métricas obrigatórias:**
- accuracy
- precision
- recall
- f1

**Condicional:**
- `roc_auc` (somente quando aplicável)

**Outros outputs:**
- confusion matrix serializável
- métricas comparáveis entre modelos

**Artefatos produzidos:**
- `eval.metrics`
- registro no Manifest

---

#### `evaluate.model_selection` (Step — kind: evaluate)
Seleção explícita do modelo campeão.

- Métrica alvo configurável (ex.: f1, roc_auc)
- Direção explícita (`maximize | minimize`)
- Ranking completo e determinístico
- Regra de desempate documentada (ex.: ordem estável por `model_id`)

**Payload de decisão:**
```yaml
selection:
  metric: string
  direction: maximize | minimize
  champion_model_id: string
  champion_score: float
  ranking:
    - model_id: string
      score: float
```

**Artefatos produzidos:**
- `eval.model_selection`
- decisão registrada no Manifest

---

## 🚦 Princípios Globais do Pipeline

- Nada é inferido automaticamente
- Toda decisão é:
  - declarada
  - rastreável
  - serializável
- Determinismo é obrigatório
- Steps são composáveis, mas nunca implícitos

---

## 🔮 Extensões Futuras (não implementadas)

- Inference / Serving
- Exportação de modelos
- Leaderboards persistentes
- Comparação multi-métrica
- Explainability (SHAP, etc.)

Essas extensões não fazem parte do **M5** e devem ser introduzidas em milestones próprios.

---

📌 **Nota final**

Se um elemento não estiver neste catálogo, ele **não existe oficialmente no Atlas**.

# 📄 default_search_grids — Grids Canônicos de Busca (v1)

## Visão Geral

Esta spec define o componente **DefaultSearchGrids v1** do **Atlas DataFlow**, responsável por
centralizar **grids de busca de hiperparâmetros**, **métrica de scoring padrão** e
**configuração de cross-validation**, de forma **determinística e explícita**.

No Atlas, **nenhuma busca começa de forma implícita**: todo espaço de busca deve ser
declarado, auditável e alinhado ao domínio.

---

## Objetivo

- Definir grids de hiperparâmetros por modelo
- Garantir compatibilidade entre grid e estimador
- Estabelecer scoring e CV padrão
- Servir como base para GridSearchCV / RandomizedSearchCV (sem executar nesta etapa)

---

## Natureza do Componente

- **ID:** `default_search_grids`
- **Tipo:** Registry / Search
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Determinístico, sem dependência de dados

---

## Relação com o ModelRegistry

O DefaultSearchGrids **depende semanticamente** do `ModelRegistry`:

- todo `model_id` referenciado deve existir no `ModelRegistry`
- todo parâmetro do grid deve existir no estimador correspondente

---

## Estrutura Canônica

Interface mínima esperada:

```python
grids.get(model_id) -> SearchSpec
```

Onde `SearchSpec` contém:
- `param_grid` (dict serializável)
- `scoring` (string explícita)
- `cv` (config explícita / objeto configurado)

---

## Grids Suportados (v1)

### 1) Logistic Regression

- **model_id:** `logistic_regression`
- **param_grid:**
```python
{
  "C": [0.01, 0.1, 1.0, 10.0],
  "class_weight": [None, "balanced"]
}
```
- **scoring:** `f1`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

### 2) Random Forest

- **model_id:** `random_forest`
- **param_grid:**
```python
{
  "n_estimators": [100, 200, 500],
  "max_depth": [None, 10, 20],
  "min_samples_split": [2, 5, 10]
}
```
- **scoring:** `f1`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

### 3) K-Nearest Neighbors

- **model_id:** `knn`
- **param_grid:**
```python
{
  "n_neighbors": [3, 5, 7, 11],
  "weights": ["uniform", "distance"]
}
```
- **scoring:** `accuracy`
- **cv:** `StratifiedKFold(n_splits=5, shuffle=True, random_state=42)`

---

## Invariantes

- Grids são **conservadores** (baseline, não exaustivos)
- Nenhum parâmetro inexistente no estimador
- Scoring explícito (nada inferido)
- CV reprodutível (seed fixa)
- Falha explícita para `model_id` inválido

---

## Falhas Explícitas

O componente deve falhar quando:

- `model_id` não existir
- `param_grid` referenciar parâmetro inválido no estimador
- scoring não for reconhecido / suportado
- configuração de CV for inválida

---

## Testes Esperados

Os testes unitários devem cobrir:

- estrutura válida do grid
- compatibilidade grid ↔ estimador
- existência de scoring
- existência de CV
- falha explícita para `model_id` inválido

---

## Fora de Escopo (v1)

- AutoML
- Busca bayesiana
- Hyperband
- Execução da busca (GridSearchCV/RandomizedSearchCV)
- Persistência de resultados

---

## Evolução Futura (Planejada)

### 1) GridBank (file-based) — implementação futura

**Objetivo:** permitir que grids adicionais sejam mantidos como **arquivos declarativos** no repositório,
com organização por modelo, sem inferência automática.

Sugestão de layout (exemplo):

```text
grids/
  logistic_regression/
    baseline_v1.yaml
    wide_v1.yaml
  random_forest/
    rf_small_v1.yaml
    rf_medium_v1.yaml
  knn/
    knn_fast_v1.yaml
```

**Regras do GridBank:**
- o diretório é **fixo e conhecido**
- os grids são **declarativos** (YAML/JSON) e versionáveis
- a UI / pipeline apenas **lista e carrega** arquivos existentes
- nada é "descoberto" fora do diretório autorizado
- validação continua sendo feita contra o estimador (params existentes)

Isso preserva o princípio central do Atlas:
> **nenhum grid é inferido; tudo é declarado**

---

### 2) Seleção de grid default via config

Além do grid canônico embutido no `DefaultSearchGrids`, será suportado um mecanismo explícito de seleção
de *grid default* por modelo, via configuração.

Exemplo canônico (config):

```yaml
modeling:
  search_grids:
    defaults:
      logistic_regression: "baseline_v1.yaml"
      random_forest: "rf_small_v1.yaml"
      knn: "knn_fast_v1.yaml"
```

**Regras:**
- a seleção é explícita (por nome de arquivo)
- se o arquivo não existir, falha explícita
- o `DefaultSearchGrids` continua existindo como fallback estável

---

### 3) UI: 3 inputs (simple / paste / bank)

A UI de busca por hiperparâmetros deverá suportar três modos explícitos de entrada de grid:

#### A) Input Simples (Simple)
- interface com poucos controles (ex.: "grid pequeno/médio", ranges básicos)
- a UI gera um dict serializável **explicitamente** (sem inferência)

#### B) Input Paste (Paste)
- campo de texto onde o usuário cola o dict do grid (YAML/JSON)
- o conteúdo colado torna-se o grid utilizado (após validação)

#### C) Input Bank (Bank)
- seletor/lista de arquivos vindos do GridBank (file-based)
- ao selecionar um arquivo, a UI carrega o conteúdo e preenche o Paste

---

## Comportamento Esperado da UI (detalhamento)

### Dois modos de operação: Input Simples + Input Search

A UI terá um seletor principal entre:

- **Input Simples**
- **Input Search** (busca por hiperparâmetros)

Quando **Input Search** for selecionado:

1) O campo **“grids paste”** deve ser preenchido automaticamente com o **grid default** do modelo selecionado.  
   - Esse default pode vir da config (se existir) ou do `DefaultSearchGrids` (fallback).

2) Ao lado do campo **“grids paste”**, deve existir um seletor/listagem mostrando **apenas os nomes**
   dos arquivos de grid disponíveis para aquele `model_id` (GridBank).

3) Ao clicar em um nome de arquivo da listagem:
   - a UI **carrega o conteúdo** do arquivo
   - **preenche** o campo “grids paste” com esse conteúdo
   - e esse conteúdo passa a ser o **conteúdo default atual** daquele modelo (para a execução corrente)
     - (persistência dessa escolha como novo default global depende da config/fluxo do projeto, fora do v1)

**Observação importante:**  
Nenhuma dessas ações envolve inferência; todas são escolhas explícitas do usuário (ou config explícita).

---

## Referências

- `docs/spec/model_registry.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`

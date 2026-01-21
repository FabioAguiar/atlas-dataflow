# 📄 representation.preprocess — Builder de Pré-processamento (v1)

## Visão Geral

O Builder **`representation.preprocess`** é responsável por construir a camada de **pré-processamento de dados** do Atlas DataFlow de forma **determinística, declarativa e alinhada ao contrato interno**.

Ele materializa um **`ColumnTransformer` canônico**, garantindo que a representação dos dados seja **consistente entre treino, validação e inferência**, evitando inferências implícitas e vazamentos semânticos.

---

## Objetivo

- Construir um `ColumnTransformer` com base no contrato
- Separar explicitamente pipelines numéricos e categóricos
- Garantir consistência estrutural entre `train` e `test`
- Servir como base estável para modelagem supervisionada

---

## Natureza do Builder

- **ID:** `representation.preprocess`
- **Tipo:** Builder
- **Milestone:** M4 — Representação & Modelagem
- **Caráter:** Construção declarativa (não executa treino de modelo)

---

## Dependências Semânticas

O Builder pressupõe:

- contrato interno carregado (`contract.load`)
- colunas já tipadas e auditadas (M1–M3)
- decisões explícitas sobre categorias e imputação já tomadas

---

## Fonte de Configuração

O Builder consome **exclusivamente configuração e contrato**, por exemplo:

```yaml
representation:
  preprocess:
    numeric:
      columns: [age, income]
      scaler: standard
    categorical:
      columns: [country, gender]
      encoder: onehot
      handle_unknown: ignore
```

Nenhuma coluna pode ser inferida automaticamente.

---

## Componentes do ColumnTransformer

### Pipeline Numérico

Opções suportadas (v1):

- `StandardScaler`
- `MinMaxScaler`
- Nenhum scaler (`null`)

Exemplo:

```python
Pipeline([
  ("scaler", StandardScaler())
])
```

---

### Pipeline Categórico

Opções suportadas (v1):

- `OneHotEncoder`
  - `handle_unknown`
  - `drop`

Exemplo:

```python
Pipeline([
  ("encoder", OneHotEncoder(handle_unknown="ignore"))
])
```

---

## Estratégia de Execução

1. Ler contrato e configuração
2. Validar colunas numéricas e categóricas
3. Construir pipelines individuais
4. Compor `ColumnTransformer`
5. Retornar objeto construído

⚠️ O Builder **não executa** `fit` nem `transform`.

---

## Separação Treino / Teste

A responsabilidade de execução é do pipeline chamador:

- `fit_transform(X_train)` → treino
- `transform(X_test)` → teste

O Builder garante apenas que a **estrutura seja consistente**.

---

## Auditoria e Rastreabilidade

O Builder deve registrar no Manifest:

- colunas numéricas utilizadas
- colunas categóricas utilizadas
- opções de scaler e encoder
- ordem final das features transformadas

Nenhuma métrica estatística é calculada aqui.

---

## Falhas Explícitas

O Builder deve falhar quando:

- colunas declaradas não existem no dataset
- configuração inválida de scaler ou encoder
- conflito entre contrato e configuração

Falhas devem ser **explícitas e rastreáveis**.

---

## Testes Esperados

Os testes unitários devem cobrir:

- construção correta do `ColumnTransformer`
- pipelines corretos por tipo de coluna
- consistência estrutural entre train/test
- falha explícita em contrato inválido

---

## Fora de Escopo (v1)

- Feature selection automática
- Feature engineering
- Treinamento de modelos
- Inferência de tipos ou colunas

---

## Evolução Futura

Possíveis extensões:

- suporte a pipelines customizados
- integração com feature store
- versionamento explícito de representação
- exportação de schema de features

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`

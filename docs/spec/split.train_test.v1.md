# 📄 split.train_test — Separação Treino/Teste Reprodutível (v1)

## Visão Geral

O Step **`split.train_test`** é responsável por realizar a **separação explícita, reprodutível e auditável** dos dados em conjuntos de **treino** e **teste**, inaugurando o **Milestone M3 — Preparação Supervisionada** no Atlas DataFlow.

No Atlas, **nenhum split é implícito**.  
Toda separação deve ser **declarada em configuração**, **determinística** e **registrada no Manifest**, garantindo rastreabilidade total dos experimentos.

---

## Objetivo

- Separar dados em conjuntos de treino e teste
- Garantir **reprodutibilidade total** via seed explícita
- Suportar **estratificação opcional**
- Registrar auditoria estrutural do split

---

## Natureza do Step

- **ID:** `split.train_test`
- **Kind:** `TRANSFORM`
- **Categoria:** Preparação Supervisionada
- **Milestone:** M3 — Preparação Supervisionada
- **Caráter:** Mutação controlada com geração de novos artifacts

---

## Fonte de Dados

O Step consome:

```
data.raw_rows
```

E produz:

```
data.train
data.test
```

O dataset original **não é destruído**, mas dá origem a artifacts derivados.

---

## Configuração Esperada (v1)

```yaml
steps:
  split.train_test:
    enabled: true
    test_size: 0.2
    seed: 42
    stratify:
      enabled: true
      column: target
```

### Regras de Configuração

- `enabled`
  - obrigatório para execução
  - ausente ou `false` → Step não executa
- `test_size`
  - obrigatório
  - float entre 0 e 1
- `seed`
  - obrigatório
  - inteiro explícito
- `stratify`
  - opcional
  - quando habilitado:
    - `column` obrigatória
    - coluna deve existir no dataset

Configurações inválidas devem resultar em **falha explícita (`FAILED`)**.

---

## Estratégia de Split

- Implementação baseada em `sklearn.model_selection.train_test_split`
- Determinismo garantido por:
  - `random_state = seed`
- Estratificação aplicada somente quando configurada

Nenhuma inferência automática de target é permitida.

---

## Auditoria de Impacto (Payload v1)

```yaml
payload:
  impact:
    rows_total: int
    rows_train: int
    rows_test: int
    test_size: float
    stratified: bool
    stratify_column: string | null
    seed: int
```

### Invariantes

- `rows_train + rows_test == rows_total`
- Proporção de `test_size` respeitada (aproximadamente)
- Payload sempre serializável

---

## Ordem Canônica de Execução

1. Ler `data.raw_rows`
2. Validar configuração
3. Aplicar split conforme parâmetros
4. Produzir artifacts `data.train` e `data.test`
5. Registrar auditoria de impacto
6. Emitir `StepResult`

---

## Falhas Explícitas

O Step retorna **`FAILED`** quando:

- `data.raw_rows` não existe ou é `None`
- `test_size` inválido
- `seed` ausente
- Estratificação configurada incorretamente
- Coluna de estratificação inexistente

---

## Testes Esperados

Os testes unitários devem cobrir:

- Split determinístico com seed fixa
- Split sem estratificação
- Split com estratificação preservando proporções (aprox.)
- Configuração inválida
- Auditoria correta de shapes e parâmetros

---

## Fora de Escopo (v1)

- Cross-validation
- K-fold
- Time-series split
- Balanceamento automático
- Inferência de target

---

## Evolução Futura

Possíveis extensões:

- `split.kfold`
- `split.time_series`
- Estratégias avançadas de validação
- Integração com contratos supervisionados

---

## Referências

- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

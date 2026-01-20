# 📄 audit.duplicates — Diagnóstico de Duplicidade (v1)

## Visão Geral

O Step **`audit.duplicates`** é responsável por **diagnosticar a presença de registros duplicados** no dataset, atuando de forma **estritamente observacional** dentro do **Milestone M2 — Ingestão & Qualidade Estrutural** do Atlas DataFlow.

Duplicidade **não é tratada como erro automático**, mas como um **sinal estrutural crítico** que deve ser explicitado, medido e rastreável antes de qualquer decisão posterior.

Este Step **não realiza mutações**, **não remove registros** e **não aplica políticas de correção**.

---

## Objetivo

- Detectar **linhas duplicadas** considerando **todas as colunas**
- Quantificar a duplicidade de forma **determinística**
- Produzir payload **serializável, auditável e rastreável**
- Preparar o terreno para Steps futuros de tratamento (fora do escopo v1)

---

## Natureza do Step

- **ID:** `audit.duplicates`
- **Kind:** `DIAGNOSTIC`
- **Categoria:** Auditoria Estrutural
- **Milestone:** M2 — Ingestão & Qualidade Estrutural
- **Caráter:** Observacional puro

---

## Fonte de Dados

O Step consome exclusivamente o artifact:

```
data.raw_rows
```

- Proveniente do Step `ingest.load`
- Não é alterado sob nenhuma hipótese

---

## Estratégia de Diagnóstico

- As duplicidades são identificadas **por linha completa**
- Todas as colunas são consideradas
- A detecção utiliza lógica determinística:
  - Duplicatas são contadas a partir da **segunda ocorrência**
  - A primeira ocorrência é considerada referência (`keep="first"`)

Nenhuma inferência de chave de negócio é realizada.

---

## Payload Produzido (v1)

```yaml
payload:
  duplicates:
    rows: int
    ratio: float
    detected: bool
    treatment_policy: string
```

### Campos

| Campo | Tipo | Descrição |
|-----|-----|----------|
| `rows` | int | Número absoluto de linhas duplicadas |
| `ratio` | float | Proporção de duplicidade (`rows / total_rows`) |
| `detected` | bool | Indica se duplicidade foi detectada |
| `treatment_policy` | string | Informação diagnóstica não acionável |

### Valor padrão de `treatment_policy`

```
"avaliar deduplicação em etapa posterior"
```

---

## Regras e Invariantes

- Payload **sempre serializável**
- Métricas **determinísticas**
- Nenhuma mutação do dataset
- Nenhuma marcação de registros
- Nenhuma decisão automática
- Dataset vazio é tratado como cenário válido:
  - `rows = 0`
  - `ratio = 0.0`
  - `detected = false`

---

## Falhas Explícitas

O Step retorna **`FAILED`** quando:

- O artifact `data.raw_rows` não existe
- O artifact `data.raw_rows` é `None`
- A dependência `pandas` não está disponível

Nesses casos, o payload segue o padrão canônico de erro estruturado do Atlas.

---

## Testes Esperados

Os testes unitários devem garantir:

- Detecção correta de duplicados
- Dataset sem duplicados
- Dataset vazio
- Não mutação do dataset original
- Falha explícita quando o artifact obrigatório está ausente

---

## Fora de Escopo (v1)

- Remoção de duplicados
- Marcação de registros
- Consolidação por chaves
- Estratégias de deduplicação
- Inferência automática de regras

---

## Evolução Futura

Este Step **não toma decisões**.  
Ele **habilita decisões futuras**, como:

- `transform.deduplicate` (config-driven)
- Políticas condicionais de tratamento
- Auditorias comparativas antes/depois

---

## Referências

- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

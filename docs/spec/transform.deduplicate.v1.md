# 📄 transform.deduplicate — Deduplicação Controlada (v1)

## Visão Geral

O Step **`transform.deduplicate`** é responsável por **remover registros duplicados de forma controlada, declarativa e auditável**, atuando como o **primeiro Step transformacional** do **Milestone M2 — Ingestão & Qualidade Estrutural** do Atlas DataFlow.

No Atlas, **deduplicação é uma decisão explícita**, nunca uma correção automática.  
Este Step **somente executa** quando **explicitamente configurado**, e **toda remoção é registrada** com auditoria de impacto antes/depois.

---

## Objetivo

- Remover duplicados **apenas quando configurado**
- Suportar múltiplas políticas declarativas de deduplicação
- Garantir **determinismo**, **rastreabilidade** e **auditabilidade**
- Preparar o terreno para normalizações e contratos posteriores

---

## Natureza do Step

- **ID:** `transform.deduplicate`
- **Kind:** `TRANSFORM`
- **Categoria:** Qualidade Estrutural (Transformacional)
- **Milestone:** M2 — Ingestão & Qualidade Estrutural
- **Caráter:** Mutação controlada e auditável

---

## Dependências Semânticas

Este Step **pressupõe diagnóstico prévio** de duplicidade:

- `audit.duplicates`

Deduplicação **sem diagnóstico explícito** é considerada violação dos invariantes do Atlas.

---

## Fonte de Dados

O Step consome exclusivamente o artifact:

```
data.raw_rows
```

Esse artifact **é mutado somente quando o Step está habilitado**.

---

## Configuração Esperada (v1)

```yaml
steps:
  transform.deduplicate:
    enabled: true
    mode: full_row | key_based
    key_columns: [string] | null
```

### Regras de Configuração

- `enabled`
  - obrigatório quando o Step está presente
  - `false` ou ausente → Step não executa (no-op)
- `mode`
  - obrigatório quando `enabled: true`
  - valores válidos:
    - `full_row`
    - `key_based`
- `key_columns`
  - obrigatório **somente** quando `mode: key_based`
  - lista não vazia de strings
  - todas as colunas devem existir no dataset

Configurações inválidas resultam em **falha explícita (`FAILED`)**.

---

## Modos de Deduplicação

### 1️⃣ Deduplicação por Linha Completa (`full_row`)

- Todas as colunas são consideradas
- Registros idênticos são deduplicados
- Política fixa v1:
  - **manter a primeira ocorrência**
  - remover as demais

---

### 2️⃣ Deduplicação por Chave (`key_based`)

- Um subconjunto explícito de colunas define a chave lógica
- Duplicidade é avaliada apenas sobre essas colunas
- Política fixa v1:
  - **manter a primeira ocorrência por chave**
  - remover as demais

Nenhuma inferência automática de chaves é realizada.

---

## Estratégia Técnica

- Implementação baseada em `pandas.DataFrame.drop_duplicates`
- Política determinística:
  - `keep="first"`
- Nenhuma heurística implícita
- Nenhuma consolidação de registros

---

## Auditoria de Impacto (Payload v1)

```yaml
payload:
  impact:
    mode: full_row | key_based
    key_columns: [string] | null
    rows_before: int
    rows_after: int
    rows_removed: int
```

### Invariantes do Payload

- `rows_before >= rows_after`
- `rows_removed = rows_before - rows_after`
- Payload **sempre presente**, inclusive quando nada é removido

---

## Ordem Canônica de Execução

1. Ler `data.raw_rows`
2. Calcular `rows_before`
3. Aplicar deduplicação conforme configuração
4. Calcular `rows_after` e `rows_removed`
5. Registrar auditoria de impacto
6. Atualizar `data.raw_rows`
7. Emitir `StepResult`

---

## Falhas Explícitas

O Step retorna **`FAILED`** quando:

- `data.raw_rows` não existe
- `data.raw_rows` é `None`
- Configuração é inválida
- `key_columns` contém colunas inexistentes
- Dependências não estão satisfeitas

O payload segue o padrão canônico de erro estruturado do Atlas.

---

## Testes Esperados

Os testes unitários devem cobrir:

- Step desabilitado (no-op)
- Deduplicação por linha completa
- Deduplicação por chave
- Configuração inválida
- Auditoria correta de antes/depois
- Mutação apenas quando habilitado

---

## Fora de Escopo (v1)

- Deduplicação fuzzy
- Consolidação ou merge de registros
- Resolução de conflitos
- Inferência automática de chaves
- Estratégias probabilísticas

---

## Evolução Futura

Possíveis extensões (fora do v1):

- Políticas de escolha configuráveis (`keep=last`)
- Estratégias de consolidação
- Auditorias comparativas com `audit.duplicates`
- Deduplicação condicional por contrato

---

## Referências

- `docs/spec/audit.duplicates.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

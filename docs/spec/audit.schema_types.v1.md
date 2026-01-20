# Spec — `audit.schema_types` (v1)

> Status: **DRAFT** (especificação introduzida pela Issue #14)

## 1. Propósito

O Step **`audit.schema_types`** fornece uma visão **detalhada por coluna** do schema efetivo observado no dataset bruto, antes de qualquer decisão de contrato, coerção ou transformação.

Princípio central do Atlas DataFlow:
- **observar sem mutar**

## 2. Inputs

### 2.1 Artifacts obrigatórios (RunContext)

- `data.raw_rows`: `List[Dict[str, Any]]`

> Origem típica: Step `ingest.load`

### 2.2 Config (opcional)

Nenhuma chave é obrigatória no v1.

## 3. Outputs

### 3.1 Artifacts

- **Nenhum** (v1)

### 3.2 Payload (obrigatório)

O payload deve ser **totalmente serializável** e conter **um bloco por coluna**, incluindo colunas degeneradas.

Formato mínimo:

```yaml
payload:
  columns:
    <column_name>:
      dtype: string
      semantic_type: string   # numeric | categorical | temporal | other
      nulls:
        count: int
        ratio: float
      cardinality:
        unique_values: int
        is_constant: bool
      examples:
        - any   # até 5, serializáveis, preferindo não nulos
```

## 4. Regras e Invariantes

- O Step **não muta** o dataset.
- O Step **não aplica** coerções, defaults ou correções.
- Métricas devem ser **determinísticas**:
  - `nulls.count` = quantidade de valores nulos (inclui NaN/NaT)
  - `nulls.ratio` = `nulls.count / rows` (ou `0.0` se rows=0)
  - `cardinality.unique_values` = número de valores distintos (ignorando nulos)
  - `cardinality.is_constant` = `unique_values == 1` **e** existe pelo menos 1 valor não nulo
- `examples`:
  - no máximo **5** valores
  - preferir **não nulos**
  - valores devem ser **serializáveis** (ex.: numpy scalars → python, datetime → ISO)

## 5. Falhas

Se `data.raw_rows` estiver ausente, o Step deve retornar:

- `status = FAILED`
- `payload.error` estruturado:

```yaml
payload:
  error:
    type: ValueError
    message: "Missing required artifact: data.raw_rows"
```

## 6. Testes (obrigatórios)

- payload contém auditoria para todas as colunas
- dtypes reportados como string
- nulls e cardinalidade corretos
- exemplos serializáveis, limitados e sem nulos quando possível
- robustez com coluna totalmente nula
- nenhuma mutação em `data.raw_rows`

## 7. Não-objetivos (v1)

- validação contra contrato
- inferência automática de schema
- correção de tipos
- análises estatísticas avançadas / outliers

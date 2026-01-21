# 📄 transform.categorical_standardize — Normalização Categórica Declarativa (v1)

## Visão Geral

O Step **`transform.categorical_standardize`** é responsável por aplicar **normalização categórica explícita e declarativa**, baseada **exclusivamente nas regras definidas em contrato**, no contexto do **Milestone M3 — Preparação Supervisionada** do Atlas DataFlow.

No Atlas, **categorias nunca são normalizadas por inferência ou heurística**.  
Toda padronização é uma **decisão consciente**, documentada e auditável.

---

## Objetivo

- Normalizar valores categóricos conforme regras contratuais
- Garantir consistência semântica entre datasets
- Detectar e reportar **categorias novas ou fora do domínio esperado**
- Registrar auditoria detalhada de impacto

---

## Natureza do Step

- **ID:** `transform.categorical_standardize`
- **Kind:** `TRANSFORM`
- **Categoria:** Preparação Supervisionada
- **Milestone:** M3 — Preparação Supervisionada
- **Caráter:** Mutação controlada e auditável

---

## Dependências Semânticas

Este Step pressupõe:

- contrato interno carregado (`contract.load`)
- dataset tipado e coerido (`transform.cast_types_safe`)

Não depende de heurísticas nem de diagnósticos probabilísticos.

---

## Fonte de Dados

O Step consome:

```
data.raw_rows
```

E atualiza o mesmo artifact **somente após auditoria registrada**.

---

## Regras Contratuais Esperadas

As regras de normalização devem estar declaradas no contrato interno, por exemplo:

```yaml
contract:
  categorical_standardization:
    country:
      casing: upper
      mappings:
        brasil: BR
        brazil: BR
        br: BR
```

### Componentes da Regra

- **Coluna alvo** (`country`)
- **Casing** (opcional):
  - `upper`
  - `lower`
- **Mappings explícitos**:
  - `alias → valor canônico`

Nenhuma regra implícita é permitida.

---

## Estratégia de Normalização

Para cada coluna categórica declarada:

1. Aplicar regra de casing (se configurada)
2. Aplicar mapeamentos explícitos
3. Identificar valores não mapeados
4. Registrar auditoria
5. Atualizar o dataset

Valores desconhecidos **não são corrigidos automaticamente**.

---

## Auditoria de Impacto (Payload v1)

```yaml
payload:
  impact:
    columns_affected: [string]
    mappings_applied:
      column:
        from: string
        to: string
    new_categories:
      column:
        - value
```

### Invariantes

- Payload sempre serializável
- Auditoria presente mesmo quando nenhuma alteração ocorre
- Categorias novas **não geram mutação silenciosa**

---

## Ordem Canônica de Execução

1. Ler contrato interno
2. Validar regras de normalização
3. Ler `data.raw_rows`
4. Aplicar normalizações declaradas
5. Detectar categorias não mapeadas
6. Registrar auditoria de impacto
7. Atualizar dataset
8. Emitir `StepResult`

---

## Falhas Explícitas

O Step retorna **`FAILED`** quando:

- regras contratuais estão ausentes ou inválidas
- coluna declarada não existe no dataset
- configuração de casing inválida
- estrutura do contrato é inconsistente

---

## Testes Esperados

Os testes unitários devem cobrir:

- Aplicação correta de mapeamentos
- Padronização de casing
- Detecção de categorias novas
- Nenhuma alteração quando não configurado
- Auditoria correta de impacto

---

## Fora de Escopo (v1)

- Inferência automática de categorias
- Normalização fuzzy
- Correção automática de erros ortográficos
- Consolidação semântica de valores

---

## Evolução Futura

Possíveis extensões:

- Normalização hierárquica
- Regras condicionais por dataset
- Integração com métricas de qualidade categórica
- Feedback loop para enriquecimento de contrato

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`

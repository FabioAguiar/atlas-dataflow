# Spec — errors.schema v1

## Visão Geral

No **Atlas DataFlow**, erros fazem parte do **contrato operacional** do sistema.
Eles devem ser:

- explícitos
- padronizados
- serializáveis
- acionáveis
- rastreáveis

Esta especificação define o **schema canônico de erros (v1)**, utilizado por
Steps, engine e camadas de export/reporting.

---

## Princípios Fundamentais

Um erro no Atlas **DEVE**:

- falhar explicitamente (nunca silenciosamente)
- ser compreensível por humanos
- ser consumível por máquinas
- preservar rastreabilidade

Um erro no Atlas **NÃO DEVE**:

- corrigir dados automaticamente
- inferir decisões
- esconder causa raiz
- depender de contexto externo

---

## Estrutura Canônica do Erro

Todo erro **DEVE** ser representado como um payload estruturado:

```json
{
  "error": {
    "type": "ContractConformityError",
    "message": "Coluna obrigatória ausente: churn",
    "details": {
      "missing_columns": ["churn"]
    },
    "hint": "Declare a coluna no contrato ou ajuste o dataset",
    "decision_required": true
  }
}
```

---

## Campos Obrigatórios

### `type`

- Tipo ou classe lógica do erro
- Deve ser estável e identificável
- Usado para classificação e snapshots

Exemplos:
- `ContractConformityError`
- `InvalidSchemaError`
- `MissingArtifactError`
- `PreprocessNotFoundError`

---

### `message`

- Mensagem curta, humana e direta
- Deve explicar **o que falhou**
- Não deve conter stacktrace

---

### `details`

- Estrutura serializável (`dict`)
- Contém informações técnicas do erro
- Pode ser vazia, mas nunca omitida

---

### `hint`

- Texto curto com **ação sugerida**
- Indica onde e como resolver o problema
- Não deve prescrever decisões automáticas

---

### `decision_required`

- `true` quando o erro exige decisão humana explícita
- `false` quando é erro técnico direto
- Pode ser estendido para enum em versões futuras

---

## Tipos de Erro Comuns (v1)

### ContractConformityError

Usado quando dados violam o contrato:

- coluna ausente
- coluna extra (quando proibido)
- tipo incompatível
- categoria fora do domínio

`decision_required = true`

---

### MissingArtifactError

Usado quando artefato esperado não está disponível:

- preprocess ausente
- modelo ausente
- bundle inexistente

`decision_required = false`

---

### InvalidSchemaError

Usado quando payloads internos estão corrompidos
ou fora do schema esperado.

`decision_required = false`

---

## Uso no StepResult

Quando um Step falhar:

- `StepResult.status` = `FAILED`
- `StepResult.payload` **DEVE** conter o payload de erro
- O erro deve ser registrado no Manifest

---

## Determinismo

Para um cenário fixo:

- o payload de erro **DEVE ser idêntico**
- a ordem de campos **DEVE ser estável**
- mensagens não podem variar por ambiente

---

## Testabilidade

O schema de erro **DEVE** ser validado por:

- testes unitários
- snapshots por cenário
- validação estrutural

---

## Evolução e Versionamento

- Esta especificação define o **errors.schema v1**
- Mudanças incompatíveis exigem nova versão
- Campos novos devem ser opcionais em versões futuras

---

## Referências

- `docs/spec/contract.internal.v1.md`
- `docs/spec/contract.conformity_report.v1.md`
- `docs/spec/e2e.pipeline.v1.md`
- `docs/spec/report.md.v1.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
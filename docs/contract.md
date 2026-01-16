# Atlas DataFlow — Contract Canonical Specification

## 1. Propósito do Documento

Este documento define a **especificação canônica de Contrato (contract)** do Atlas DataFlow e estabelece, de forma inequívoca, a **separação conceitual e operacional entre Configuração (config) e Contrato (contract)**.

O contrato descreve a **semântica dos dados e do problema analítico**, enquanto o config controla **exclusivamente o comportamento funcional da execução**.

Este documento é **fonte de verdade** para:
- definição do problema analítico
- alinhamento semântico entre pipeline, modelos e inferência
- validação estrutural e semântica dos dados
- desenho de APIs e payloads de inferência
- testes de conformidade e compatibilidade

---

## 2. Princípio Fundamental

> **Config controla comportamento.  
> Contrato controla significado.**

Qualquer violação desta separação deve ser considerada **inconsistência arquitetural grave**.

---

## 3. Formato Oficial do Contrato

O formato oficial de contratos no Atlas DataFlow é:

> **JSON**

### Justificativa
- Estrutura rígida e não ambígua
- Adequado para validação formal via schema
- Compatível com múltiplas linguagens (Python, Java, JS, etc.)
- Seguro para uso em APIs e bundles de inferência
- Impede mutações semânticas informais

Contratos **não devem** ser definidos em YAML.

---

## 4. O que é Contrato no Atlas DataFlow

O **Contrato** é uma especificação declarativa e imutável que define:

- qual é o problema analítico
- qual é o target
- quais atributos fazem parte do espaço semântico interno
- quais tipos são aceitos
- quais valores são válidos
- quais defaults **semânticos** são permitidos
- quais regras de compatibilidade são aceitas

O contrato **não executa lógica**, ele **define invariantes semânticos**.

---

## 5. Imutabilidade Semântica

Um contrato, após utilizado em um run do pipeline:

- **não pode ser alterado**
- deve ser tratado como artefato imutável
- deve possuir hash persistido no manifest
- deve acompanhar qualquer artefato derivado (modelo, métricas, relatórios)

Qualquer mudança semântica exige:
- nova versão de contrato
- nova execução completa do pipeline
- novo manifest

---

## 6. O que NÃO é Contrato

O contrato **não deve** conter:

- parâmetros de execução
- flags de ativação/desativação de steps
- hiperparâmetros de modelos
- estratégias de split
- políticas de busca (grid/random)
- decisões de performance ou infraestrutura

Esses elementos pertencem **exclusivamente ao config**.

---

## 7. Diferença entre Config e Contrato

| Aspecto | Config | Contrato |
|------|------|--------|
| Natureza | Operacional | Semântica |
| Define | Como executar | O que os dados significam |
| Pode mudar por run | Sim | Não |
| Versionamento | Opcional | Obrigatório |
| Impacto em inferência | Indireto | Direto |
| Validação | Estrutural | Estrutural e semântica |

---

## 8. Estrutura Canônica de um Contrato (Exemplo)

```json
{
  "contract_version": "1.0",
  "problem": {
    "type": "classification",
    "description": "Customer churn prediction"
  },
  "target": {
    "name": "churn",
    "type": "binary",
    "positive_label": "yes"
  },
  "features": {
    "numeric": ["tenure", "monthly_charges"],
    "categorical": ["contract_type", "payment_method"]
  },
  "types": {
    "tenure": "int",
    "monthly_charges": "float",
    "contract_type": "category",
    "payment_method": "category"
  },
  "defaults": {
    "categorical": {
      "contract_type": "unknown"
    }
  },
  "rules": {
    "allowed_categories": {
      "contract_type": [
        "month-to-month",
        "one-year",
        "two-year",
        "unknown"
      ]
    }
  }
}
```

---

## 9. Validação Obrigatória

Todo contrato deve ser **validado obrigatoriamente** antes de qualquer execução.

Falhas de validação devem:
- interromper a execução
- gerar erro explícito
- ser registradas no manifest/event log

---

## 10. Regra de Ouro

Se uma regra:
- altera o significado dos dados,
- impacta validação semântica,
- influencia inferência,

**ela pertence ao contrato — nunca ao config.**

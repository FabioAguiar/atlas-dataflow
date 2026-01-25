# Spec — notebook.ui.adapter v1

## Visão Geral

A **Camada UI Notebook (adapter)** fornece utilitários opcionais para
**renderização de payloads** do Atlas DataFlow em notebooks.

Seu objetivo é **melhorar a legibilidade humana** durante a execução,
sem introduzir:

- lógica de negócio
- decisões implícitas
- dependências do core do pipeline

Esta camada atua estritamente como **adapter de apresentação**.

---

## Princípios Fundamentais

A camada UI **DEVE**:

- ser opcional
- ser pura (entrada → saída)
- ser determinística
- não modificar payloads

A camada UI **NÃO DEVE**:

- importar módulos do core do pipeline
- acessar Manifest
- inferir ou enriquecer dados
- manter estado interno

---

## Escopo (v1)

Incluído:

- Renderizadores simples de payload
- Saída em HTML ou string formatada
- Uso exclusivo em notebooks

Excluído (fora de escopo):

- Widgets interativos
- Dashboards
- Dependência de frameworks web
- Persistência de estado
- Customização visual avançada

---

## Fonte de Verdade

A camada UI trabalha **exclusivamente** sobre:

- payloads retornados pelos Steps
- estruturas Python básicas (`dict`, `list`, `str`, `int`, etc.)

Nenhuma outra fonte é permitida.

---

## Interface Esperada

Os renderizadores **DEVEM** seguir o padrão:

```python
def render(payload: Any) -> str:
    ...
```

Regras:

- retorno deve ser `str` (HTML ou texto)
- função deve ser pura
- exceções devem ser explícitas

---

## Tipos de Renderização (v1)

### Tabelas

- Payloads tabulares (`list[dict]`, `dict[str, list]`)
- Saída em HTML `<table>` ou string equivalente

### Cards

- Payloads pequenos (`dict` simples)
- Saída resumida e legível

### Fallback

- Payloads desconhecidos
- Serialização segura (`json.dumps` ou `str`)

---

## Determinismo

Para um payload fixo:

- a saída **DEVE ser idêntica**
- a ordem de campos **DEVE ser estável**
- nenhuma variação dependente de ambiente é permitida

---

## Testabilidade

Cada renderizador **DEVE** possuir testes unitários cobrindo:

- payload válido
- payload vazio
- payload inesperado
- garantia de não mutação do payload de entrada

---

## Erros e Falhas

O adapter **DEVE falhar explicitamente** quando:

- payload for inválido para o renderizador
- tipo de entrada não for suportado

Falhas silenciosas são proibidas.

---

## Versionamento

- Esta especificação define o **notebook.ui.adapter v1**
- Mudanças incompatíveis exigem nova versão
- A versão deve ser referenciada nas issues e documentação

---

## Referências

- `docs/spec/notebook.orchestrator.v1.md`
- `docs/spec/notebook.template.v1.md` *(ainda não existente)*
- `docs/testing.md`
- `docs/pipeline_elements.md`
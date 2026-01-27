
# Spec — notebook.ui.adapter v1

## Visão Geral

A **Camada UI Notebook (adapter)** fornece utilitários opcionais para
**renderização de payloads** do Atlas DataFlow em notebooks.

Seu objetivo é **melhorar a legibilidade humana** durante a execução,
sem introduzir:

- lógica de negócio
- decisões implícitas
- dependências do core do pipeline

Esta camada atua estritamente como **adapter de apresentação**,
consumindo payloads já produzidos pelo pipeline.

---

## Princípios Fundamentais

A camada UI **DEVE**:

- ser opcional
- ser pura (entrada → saída)
- ser determinística
- não modificar payloads
- ser totalmente desacoplada do core

A camada UI **NÃO DEVE**:

- importar módulos do core do pipeline (Engine, RunContext, Steps, etc.)
- acessar Manifest ou RunContext
- inferir, enriquecer ou reinterpretar dados
- manter estado interno
- executar qualquer lógica de pipeline

---

## Escopo (v1)

Incluído:

- Renderizadores simples de payload
- Saída em HTML (string) quando aplicável
- Fallback seguro em string formatada
- Uso exclusivo em notebooks

Excluído (fora de escopo):

- Widgets interativos
- Dashboards
- Dependência de frameworks web
- Persistência de estado
- Customização visual avançada
- Integração com execução do pipeline

---

## Fonte de Verdade

A camada UI trabalha **exclusivamente** sobre:

- payloads retornados pelos Steps
- estruturas Python básicas (`dict`, `list`, `str`, `int`, etc.)

Nenhuma outra fonte é permitida.

---

## Interface Esperada

Os renderizadores **DEVEM** seguir o padrão funcional:

```python
def render_payload(payload: Any) -> RenderResult:
    ...
```

Onde:

```python
@dataclass(frozen=True)
class RenderResult:
    html: Optional[str]  # HTML quando aplicável
    text: str            # fallback textual (sempre presente)
```

Regras:

- a função deve ser pura
- o payload de entrada não pode ser modificado
- exceções devem ser explícitas
- o retorno não pode depender de estado externo

---

## Tipos de Renderização (v1)

### Tabelas

- Payloads tabulares (`list[dict]`, `dict[str, Any]`)
- Saída em HTML `<table>`
- Ordem de colunas estável

### Cards

- Payloads pequenos e semânticos (`dict` simples)
- Saída resumida em HTML
- Uso opcional no notebook

### Fallback

- Payloads desconhecidos ou não tabulares
- Serialização segura (`json.dumps` ou `repr`)
- Sempre disponível via `RenderResult.text`

---

## Determinismo

Para um payload fixo:

- a saída **DEVE ser idêntica**
- a ordem de campos **DEVE ser estável**
- nenhuma variação dependente de ambiente é permitida

---

## Pureza e Segurança

Os renderizadores:

- **DEVEM** garantir que o payload de entrada não seja modificado
- **DEVEM** falhar explicitamente se mutação for detectada
- **NÃO DEVEM** capturar exceções silenciosamente

---

## Testabilidade

Cada renderizador **DEVE** possuir testes unitários cobrindo:

- payload válido
- payload vazio
- payload inesperado
- fallback seguro
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
- A versão deve ser referenciada em issues, commits e documentação

---

## Referências

- `docs/spec/notebook.orchestrator.v1.md`
- `docs/spec/notebook.template.v1.md` *(ainda não existente)*
- `docs/testing.md`
- `docs/pipeline_elements.md`

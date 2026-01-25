# Spec — notebook.orchestrator v1

## Visão Geral

O **Notebook Orquestrador** é o ponto de entrada humano canônico do
**Atlas DataFlow**.

Seu papel **não é executar lógica de negócio**, mas **orquestrar**
a execução do pipeline por meio de:

- configuração explícita
- contrato declarado
- DAG de Steps canônicos
- execução controlada
- visualização de resultados

O notebook é tratado como **interface**, não como engine.

---

## Princípios Fundamentais

O notebook orquestrador **DEVE**:

- ser declarativo
- ser determinístico
- ser auditável
- ser legível

O notebook orquestrador **NÃO DEVE**:

- conter lógica de Step
- conter heurísticas
- modificar dados diretamente
- tomar decisões implícitas

---

## Escopo (v1)

Incluído:

- Template de notebook canônico
- Orquestração explícita por DAG
- Uso exclusivo de APIs públicas do core
- Execução ponta a ponta do pipeline

Excluído (fora de escopo):

- Widgets avançados
- Execução distribuída
- Visual DAG editor
- Versionamento de notebooks
- Lint automático (ver M8-02)

---

## Fonte de Verdade

O notebook deve operar **exclusivamente** sobre:

- APIs públicas do core (`Pipeline`, `RunContext`, `StepRegistry`)
- contratos declarados
- configurações explícitas
- Steps canônicos

Nenhuma regra pode viver fora do core.

---

## Estrutura Canônica do Notebook

O notebook **DEVE** seguir a estrutura abaixo:

1. **Introdução**
   - propósito do pipeline
   - escopo da execução

2. **Configuração**
   - definição de `config`
   - parâmetros de execução

3. **Contrato**
   - carregamento ou definição do contrato
   - validação explícita

4. **Montagem do DAG**
   - instanciação explícita dos Steps
   - definição clara das dependências

5. **Execução**
   - chamada única e explícita do pipeline

6. **Resultados**
   - métricas
   - artefatos
   - caminhos gerados

7. **Referências**
   - Manifest
   - artefatos produzidos

---

## Regras de Orquestração

- A ordem de execução **DEVE** ser definida pelo DAG
- Nenhum Step pode ser executado fora do Pipeline
- O notebook não pode alterar o comportamento interno dos Steps
- Todas as decisões devem estar visíveis no código do notebook

---

## Determinismo

Para uma configuração e contrato fixos:

- a execução do notebook **DEVE ser reproduzível**
- os resultados **DEVEM ser equivalentes**
- a ordem dos Steps **DEVE ser estável**

---

## Erros e Falhas

O notebook **DEVE falhar explicitamente** quando:

- contrato estiver ausente ou inválido
- Steps obrigatórios não forem definidos
- o DAG estiver inconsistente
- APIs não públicas forem utilizadas

Falhas silenciosas são proibidas.

---

## Testabilidade

O notebook deve ser:

- executável em CI
- validável por smoke tests
- inspecionável estaticamente

---

## Versionamento

- Esta especificação define o **notebook.orchestrator v1**
- Mudanças estruturais exigem nova versão
- A versão deve ser referenciada nas issues e no notebook

---

## Referências

- `docs/spec/pipeline.dag.v1.md` *(ainda não existente)*
- `docs/spec/contract.internal.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/testing.md`
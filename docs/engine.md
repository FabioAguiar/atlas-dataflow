# Atlas DataFlow — Engine Canonical Specification (DAG Executor)

## 1. Propósito do Documento

Este documento define a **especificação canônica do Engine** do Atlas DataFlow: o executor de pipeline baseado em **DAG de Steps** e suas políticas formais de execução, falha, skip e rastreabilidade.

Este documento é **fonte de verdade** para:
- implementação do planejador/executor do DAG
- políticas de erro, retry e fail-fast
- integração com notebook (orquestração narrativa)
- integração com APIs/CLIs (execução automatizada)
- testes unitários e E2E do pipeline

---

## 2. Responsabilidade do Engine

O Engine é responsável por:

1. **Validar** um conjunto de Steps
2. **Planejar** a ordem de execução a partir de dependências
3. **Executar** Steps com políticas consistentes (fail/skip)
4. **Emitir rastreabilidade** (event log + atualização do manifest)
5. **Produzir resultado agregável** (payloads por step, status global)

O Engine **não** é responsável por:
- lógica de domínio de Steps
- inferir decisões semânticas
- renderização de UI
- leitura direta de dados (isso é do step `ingest.load`)

---

## 3. Entradas e Saídas

### 3.1 Entradas do Engine

- Lista de Steps (implementações da interface canônica `Step`)
- `RunContext` (config, contrato, store, logs)
- Opções de execução (derivadas de config):
  - `fail_fast`
  - `allow_skip`
  - `max_retries` (futuro)

### 3.2 Saídas do Engine

- Resultado global:
  - status final do run (`success | failed | partial`)
  - resumo textual
  - lista de `StepResult` agregados
- Atualização do manifest (via regras de `traceability.md`)

---

## 4. Validação Canônica do DAG

Antes de executar, o Engine deve validar:

1. **IDs únicos**
   - nenhum `step_id` duplicado

2. **Dependências resolvíveis**
   - todo `depends_on` referencia step existente

3. **Sem ciclos**
   - DAG deve ser acíclico
   - ciclos → erro antes de executar

4. **Kinds válidos**
   - kind ∈ `{diagnostic, transform, train, evaluate, export}`

5. **Pré-condições mínimas (opcional)**
   - steps export dependem de resultados anteriores (ex.: modelo treinado)
   - esta validação pode evoluir por policy

---

## 5. Planejamento (Topological Sort)

A ordem de execução deve ser derivada de uma ordenação topológica do DAG.

Propriedades:
- Steps só podem executar quando todas as dependências estiverem `success` (ou `skipped` conforme policy)
- A ordem não depende do notebook
- A execução deve ser determinística

---

## 6. Política de Status e Transições

### 6.1 Status Canônicos

- `PENDING`
- `RUNNING`
- `SUCCESS`
- `SKIPPED`
- `FAILED`
- `BLOCKED` (não executou por dependência falha)

### 6.2 Transições

- `PENDING → RUNNING`
- `RUNNING → SUCCESS | FAILED | SKIPPED`
- `PENDING → BLOCKED` (se dependência falha e policy bloqueia)

---

## 7. Política de Falhas

### 7.1 Fail-fast

Se `fail_fast = true`:
- ao primeiro `FAILED`, interromper execução de Steps restantes
- marcar dependentes como `BLOCKED`

Se `fail_fast = false`:
- continuar executando Steps independentes do step falho
- dependentes diretos/indiretos permanecem `BLOCKED`

---

### 7.2 Retry (futuro)

Retry não é obrigatório em v1, mas o Engine deve ser desenhado para suportar:
- `max_retries`
- backoff simples
- retry apenas em steps diagnostic ou IO

---

## 8. Política de Skip

Skip pode ocorrer por:

1. **Config** (step desabilitado)
2. **Pré-condição não atendida**
3. **Decisão explícita do usuário** (via notebook/config)

Regras:
- skip deve ser registrado em `StepResult` (`status=skipped`)
- skip nunca pode mascarar erro
- skip de step que é dependência crítica deve bloquear dependentes (a menos de policy explícita)

---

## 9. Integração com Traceability

O Engine deve emitir eventos e persistir:

- evento `step_started`
- evento `step_finished`
- evento `step_failed`
- evento `step_skipped`

Além disso, deve garantir:

- cada Step gera `StepResult` (mesmo falho/skip)
- `StepResult` é serializável
- payloads por step podem ser persistidos em `artifacts/runs/<run_id>/payloads/`
- manifest atualizado ao final

Regra:
- Engine nunca deve terminar sem escrever manifest final (mesmo em falha).

---

## 10. Interface Pública do Engine (v1)

A API do Engine deve ser minimalista:

- `Engine(steps: list[Step], ctx: RunContext)`
- `run() -> RunResult`

`RunResult` deve conter:
- status global
- lista de `StepResult`
- metadados do run (run_id, timestamps)

---

## 11. Testes Obrigatórios

O projeto deve possuir testes unitários para:

- validação de step_id único
- erro em dependência inexistente
- erro em ciclo (DAG inválido)
- ordenação topológica determinística
- fail_fast = true interrompe execução
- fail_fast = false continua steps independentes
- steps desabilitados via config → SKIPPED
- dependentes de falha → BLOCKED

Além disso, ao menos 1 teste E2E deve:
- executar um pipeline mínimo
- produzir manifest e payloads

---

## 12. Regra de Ouro

Se a execução:
- não é determinística,
- não registra falhas/skip,
- não atualiza manifest,

**não existe Engine no Atlas DataFlow.**

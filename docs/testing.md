# Atlas DataFlow — Testing Strategy (Canonical)

## 1. Propósito do Documento

Este documento define a **estratégia formal de testes** do Atlas DataFlow.

Ele estabelece **níveis de teste**, responsabilidades, escopo e critérios mínimos para garantir que o framework seja:
- correto
- reprodutível
- evolutivo
- seguro para uso por notebooks, APIs e CLIs

Este documento é **fonte de verdade** para a escrita, organização e validação de testes.

---

## 2. Princípios Fundamentais

1. **Testabilidade como requisito de domínio**
   - Código que não pode ser testado isoladamente é considerado mal estruturado.

2. **Testes protegem arquitetura**
   - Testes devem falhar quando invariantes do domínio são violados.

3. **Determinismo**
   - Testes devem ser reproduzíveis e independentes de ambiente.

4. **Fail early**
   - Erros estruturais devem ser detectados o mais cedo possível.

---

## 3. Pirâmide de Testes do Atlas DataFlow

A estratégia segue uma pirâmide clara:

```text
E2E (poucos, críticos)
↑
Integration
↑
Unit (muitos, rápidos)
```

---

## 4. Testes Unitários

### 4.1 Escopo

Testes unitários devem cobrir:

- Loader de config (merge, validações)
- Loader de contrato (validações estruturais)
- Protocolo `Step`
- `RunContext`
- Engine (validações internas)
- Manifest writer (schema mínimo)

### 4.2 Regras

- Nenhum teste unitário acessa filesystem real (usar tmp_path)
- Nenhum teste unitário executa DAG completo
- Falhas devem ser explícitas e isoladas

---

## 5. Testes de Integração

### 5.1 Escopo

Testes de integração validam a **colaboração entre componentes**, como:

- Engine + Steps dummy
- Engine + Manifest
- Config + Contract + RunContext

### 5.2 Regras

- Podem usar fixtures compartilhadas
- Devem validar efeitos colaterais controlados
- Não devem depender de datasets reais

---

## 6. Testes E2E (End-to-End)

### 6.1 Objetivo

Testes E2E validam o **fluxo completo do pipeline**, garantindo que:

- Steps são executados em ordem correta
- Manifest é gerado
- RunResult é consistente
- Invariantes do domínio são respeitados

### 6.2 Escopo mínimo obrigatório

Todo projeto Atlas DataFlow deve possuir ao menos:

- 1 teste E2E smoke
- dataset sintético mínimo
- contrato e config mínimos
- validação de schema do Manifest

---

## 7. Organização dos Testes

Estrutura recomendada:

```text
tests/
 ├── unit/
 ├── integration/
 ├── e2e/
 └── fixtures/
     ├── data/
     ├── config/
     └── steps/
```

---

## 8. Fixtures

Fixtures devem ser:

- pequenas
- determinísticas
- reutilizáveis
- versionadas

Fixtures não devem:
- conter lógica de negócio
- mascarar erros

---

## 9. Critérios de Qualidade

Um conjunto de testes é considerado adequado quando:

- `pytest -q` executa sem falhas
- erros estruturais quebram testes unitários
- erros de integração quebram testes de integração
- regressões quebram testes E2E

---

## 10. Integração com CI

O pipeline de CI deve:

- executar `pytest -q`
- falhar em qualquer erro
- não permitir merge sem testes passando

---

## 11. Integração com Outros Documentos

Este documento deve ser usado em conjunto com:

- `docs/domain/domain.core-pipeline.v1.md`
- `docs/config.md`
- `docs/contract.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/manifest.schema.v1.md`
- `docs/run_result.md`

---

## 12. Regra de Ouro

Se uma mudança:
- não pode ser validada por testes,
- não protege invariantes,
- não é reproduzível,

**ela não deve ser integrada ao Atlas DataFlow.**

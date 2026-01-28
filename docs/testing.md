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

## 6.3 E2E Suite: Telco-like e Bank-like via config

A suíte E2E canônica do Atlas DataFlow inclui **dois cenários de domínio
representativos**, executados **exclusivamente via configuração**:

- **Telco-like**
- **Bank-like**

O objetivo desta suíte é **provar que o mesmo core**:

- suporta múltiplos domínios,
- respeita contratos distintos,
- mantém invariantes,
- sem qualquer alteração de código.

### Características obrigatórias

- Execução 100% **config-driven**
- Mesmo conjunto de Steps e builders
- Variação apenas de:
  - dataset
  - contrato
  - parâmetros de config

### Isolamento por `run_dir`

Cada cenário E2E deve:

- criar seu próprio `run_dir`
- não compartilhar paths, arquivos ou estado
- ser executável de forma independente

A execução de um cenário **não pode poluir** outro.

### Fixtures sintéticas

Os testes E2E devem utilizar:

- datasets **sintéticos**
- contratos versionados
- configs explícitas

É proibido:

- uso de dados reais sensíveis
- dependência de serviços externos
- dependência de infraestrutura específica

### Artefatos esperados

Cada execução E2E **DEVE gerar**:

- preprocess persistido (`preprocess.joblib`)
- modelo treinado
- métricas finais
- bundle de inferência (`inference_bundle.joblib`)
- relatório consolidado (`report.md`)
- entradas correspondentes no Manifest

A ausência de qualquer artefato **deve falhar o teste**.

---



---

## 6.4 Como Executar a Suite E2E (M9 — Qualidade & Empacotamento)

Esta seção descreve **como executar** e **o que a suíte E2E garante** no Atlas DataFlow.

### Como rodar

```bash
pytest -q tests/e2e/test_pipeline_telco_like.py
pytest -q tests/e2e/test_pipeline_bank_like.py
pytest -q
```

### O que os testes garantem

- **Mesmo core / múltiplos domínios via config**  
  O pipeline executa cenários Telco-like e Bank-like sem qualquer alteração no core,
  variando exclusivamente dataset, contrato e configuração.

- **Determinismo (Run A vs Run B)**  
  Execuções repetidas com a mesma configuração produzem os mesmos artefatos lógicos,
  incluindo `report.md` (após normalização).

- **Isolamento total entre cenários**  
  A execução de um cenário não afeta o outro. Cada teste possui `run_dir` próprio
  e não compartilha estado, paths ou artefatos.

### Regras que não podem ser quebradas

- **Seeds explícitos**  
  Steps como `split.train_test` e `train.single` devem declarar `seed` explicitamente.

- **`target_metric` obrigatório no `evaluate.model_selection`**  
  A métrica alvo deve existir em `eval.metrics` e ser declarada de forma explícita.

- **Paths relativos ao `run_dir` (quando aplicável)**  
  Configs e contratos usados em E2E devem ser resolvidos a partir do diretório de execução
  para garantir reprodutibilidade e isolamento.

- **`assert_reports_equal` como verificador oficial de determinismo**  
  A igualdade entre relatórios deve ser validada exclusivamente por este helper,
  que normaliza hashes, paths e payloads voláteis.

Esta seção consolida as regras aprendidas durante a estabilização da suíte E2E
e passa a ser **normativa** para qualquer novo cenário end-to-end no Atlas DataFlow.

## 7. Organização dos Testes

Estrutura recomendada:

```text
tests/
 ├── unit/
 ├── integration/
 └── e2e/
     ├── _helpers.py
     ├── test_pipeline_telco_like.py
     ├── test_pipeline_bank_like.py
     └── fixtures/
         ├── telco/
         └── bank/
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
- `docs/spec/e2e.pipeline.v1.md`

---

## 12. Regra de Ouro

Se uma mudança:
- não pode ser validada por testes,
- não protege invariantes,
- não é reproduzível,

**ela não deve ser integrada ao Atlas DataFlow.**

# Atlas DataFlow — Domain Core Pipeline

## 1. Visão Geral

O **Atlas DataFlow** é um framework contrato-driven para construção de pipelines analíticos modulares, auditáveis e adaptáveis.  
Seu objetivo é servir como **base arquitetural canônica** para análise de dados, modelagem estatística e aplicações de machine learning, mantendo rastreabilidade, reprodutibilidade e evolução segura.

Este documento define o **Domain oficial** do Atlas DataFlow e deve ser tratado como **fonte de verdade** para:
- implementação do core
- definição de use cases
- desenho de APIs e adapters
- critérios de qualidade e testes

---

## 2. Problema que o Domain Core Pipeline

Pipelines analíticos tradicionais sofrem de:
- acoplamento entre etapas
- decisões implícitas e não auditáveis
- dificuldade de adaptação a novos datasets
- fragilidade ao evoluir regras e contratos

O Atlas DataFlow resolve isso ao tratar o pipeline como:
- um **sistema orientado a domínio**
- guiado por **contratos explícitos**
- composto por **etapas modulares nomeadas**
- com **auditoria de ponta a ponta**

---

## 3. Princípios Fundamentais

1. **Contrato como Fonte de Verdade**
   - O contrato governa target, features, tipos, defaults e regras semânticas.
   - Nenhuma etapa pode redefinir significado fora do contrato.

2. **Transformação Semântica Nunca é Silenciosa**
   - Toda transformação irreversível exige auditoria explícita.

3. **Pipeline como DAG de Etapas**
   - Etapas possuem identidade semântica estável.
   - A ordem é derivada por dependências, não por numeração.

4. **Separação Clara de Responsabilidades**
   - Core executa regras.
   - Notebook narra.
   - UI apenas renderiza.
   - APIs apenas adaptam.

5. **Reprodutibilidade Determinística**
   - Mesmas entradas + mesmo contrato = mesmos resultados.

---

## 4. Linguagem Ubíqua

- **Contrato Interno**: definição canônica do problema analítico.
- **Etapa (Step)**: unidade modular do pipeline.
- **Diagnóstico**: inspeção reversível.
- **Transformação**: operação irreversível.
- **Auditoria**: evidência estruturada do que ocorreu.
- **Manifest**: registro forense de uma execução.
- **Artefato**: saída persistida (modelo, relatório, preprocess).

---

## 5. Modelo de Pipeline

### 5.1 Etapas (Steps)

Cada etapa deve declarar:
- `id` (slug estável)
- `kind` (diagnostic | transform | train | evaluate | export)
- `depends_on`
- `inputs`
- `outputs`
- `payload` de auditoria

### 5.2 Execução

- O pipeline é executado como um **DAG**.
- Falhas interrompem fluxos dependentes.
- Etapas podem ser puladas apenas via decisão explícita.

---

## 6. Contratos

### 6.1 Contrato Interno

Define:
- target
- features internas
- tipos esperados
- defaults permitidos
- regras de normalização e imputação

### 6.2 Compatibilidade

- Divergências devem ser diagnosticadas.
- Compatibilidade legada ocorre apenas por adaptação explícita.

---

## 7. Manifest de Execução

Cada execução gera um **manifest canônico**, contendo:
- identificação do run
- snapshot de config e contrato
- lista de etapas executadas
- decisões registradas
- artefatos gerados

O manifest é base para:
- auditoria
- relatórios
- depuração
- reprodutibilidade

---

## 8. Testabilidade

- Etapas devem ser testáveis isoladamente.
- Contratos devem possuir testes de conformidade.
- O pipeline deve possuir ao menos um teste E2E com dataset sintético.

---

## 9. Escopo Futuro

Este Domain permite, sem alteração conceitual:
- APIs de inferência (FastAPI, Django, etc.)
- Gateways tecnológicos diversos
- UIs acopladas por adapters
- múltiplos domínios analíticos além de ML preditivo

---

## 10. Regra de Ouro

Se uma decisão:
- não está no contrato,
- não aparece no manifest,
- não possui auditoria,

**ela não existe para o Atlas DataFlow.**

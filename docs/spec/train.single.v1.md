# 📄 train.single — Treinamento Simples e Determinístico (v1)

## Visão Geral

Esta spec define o Step **train.single v1** do **Atlas DataFlow**, responsável pelo
**treinamento de um único modelo**, sem busca de hiperparâmetros, de forma
**determinística, auditável e reproduzível**.

O objetivo é fornecer um **baseline confiável** antes de qualquer estratégia de search/tuning.

---

## Objetivo

- Treinar um único modelo a partir do `ModelRegistry`
- Utilizar apenas **default params**
- Gerar métricas padrão
- Garantir reprodutibilidade via seed explícita
- Registrar métricas e parâmetros no Manifest

---

## Natureza do Step

- **ID:** `train.single`
- **Kind:** `train`
- **Milestone:** M5 — Modelagem & Avaliação
- **Caráter:** Transformacional (gera modelo treinado)

---

## Dependências

O Step depende semanticamente de:

- `ModelRegistry v1`
- `representation.preprocess`
- Dataset já dividido (train/test ou equivalente)

---

## Configuração Esperada

```yaml
steps:
  train.single:
    enabled: true
    model_id: logistic_regression
    seed: 42
```

Campos:
- `model_id` (obrigatório)
- `seed` (obrigatório)

---

## Comportamento Canônico

O Step deve:

1. Validar `model_id` no `ModelRegistry`
2. Instanciar o modelo com **default params**
3. Aplicar `seed` explicitamente (quando suportado)
4. Ajustar o modelo nos dados de treino
5. Avaliar nos dados de validação/teste
6. Gerar métricas padrão
7. Registrar outputs no Manifest

---

## Métricas Geradas (v1)

Obrigatórias:

- `accuracy`
- `precision`
- `recall`
- `f1`

Regras:
- Métricas calculadas de forma determinística
- Sem métricas inferidas automaticamente

---

## Payload Esperado (mínimo)

```yaml
payload:
  model_id: string
  seed: int
  metrics:
    accuracy: float
    precision: float
    recall: float
    f1: float
```

---

## Rastreabilidade

O Manifest deve registrar:

- `model_id`
- parâmetros do modelo
- seed utilizada
- métricas geradas
- status do Step

---

## Falhas Explícitas

O Step deve falhar quando:

- `model_id` não existir
- dados de treino não estiverem disponíveis
- preprocess não estiver disponível
- seed não for fornecida

---

## Testes Esperados

Os testes unitários devem cobrir:

- smoke test de treinamento
- determinismo com seed fixa
- geração correta de métricas
- falha explícita para `model_id` inválido

---

## Fora de Escopo (v1)

- Busca de hiperparâmetros
- Cross-validation
- Persistência do modelo treinado
- Métricas avançadas (ROC, PR)

---

## Evolução Futura

Possíveis extensões:

- Suporte a regressão
- Persistência de modelos
- Integração com `train.search`
- Métricas customizadas

---

## Referências

- `docs/spec/model_registry.v1.md`
- `docs/spec/representation.preprocess.v1.md`
- `docs/spec/default_search_grids.v1.md`
- `docs/pipeline_elements.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`

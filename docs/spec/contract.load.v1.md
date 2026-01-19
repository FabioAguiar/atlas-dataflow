# Atlas DataFlow — Step Specification: contract.load v1

## 1. Propósito

Este documento define a **especificação formal e canônica do Step `contract.load` (v1)** no Atlas DataFlow.

O Step `contract.load` é responsável por **materializar o contrato interno no contexto de execução**, garantindo que:
- o contrato exista,
- seja estruturalmente válido,
- seja semanticamente consistente,
- esteja disponível para todos os Steps subsequentes,
- seja rastreável no Manifest.

Este documento é **normativo** para implementações, testes e consumo por APIs.

---

## 2. Papel do Step no Pipeline

O Step `contract.load`:

- é um **Step de tipo `diagnostic`**
- deve ser executado **antes de qualquer Step que dependa de semântica**
- não modifica dados
- não executa coerções
- não aplica defaults

Ele apenas **carrega, valida e injeta** o contrato.

---

## 3. Identidade do Step

```yaml
step_id: contract.load
kind: diagnostic
depends_on: []
```

---

## 4. Entradas

### 4.1 Config

```yaml
contract:
  path: path/to/contract.yaml
```

- `contract.path` é obrigatório
- YAML preferencial, JSON alternativo

---

## 5. Processamento

### 5.1 Carregamento
- leitura de arquivo
- parsing YAML/JSON

### 5.2 Validação
- valida contra `internal_contract.v1`
- erros são fatais

### 5.3 Injeção no RunContext
- contrato validado armazenado em `ctx.contract`

---

## 6. Saídas

- contrato efetivo no RunContext
- registro completo no Manifest (path, hash, status)

---

## 7. Política de Falha

Qualquer erro é **fatal**.  
Não existe skip ou fallback em v1.

---

## 8. Testes Obrigatórios

- contrato válido
- contrato inválido
- arquivo inexistente
- erro bem reportado no Manifest

---

## 9. Referências

- `docs/spec/internal_contract.v1.md`
- `docs/contract.md`
- `docs/config.md`
- `docs/engine.md`
- `docs/traceability.md`
- `docs/testing.md`

---

## 10. Regra de Ouro

Sem `contract.load`, não existe semântica confiável no pipeline.

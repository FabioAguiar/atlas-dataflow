# Atlas DataFlow — Current Architecture Overview

> Visão geral fundamentada no estado atual do repositório. O cursor operacional autoritativo é `docs/project-status/milestone-state.json`; quando este resumo divergir dele, vale o arquivo de estado. Este documento descreve o comportamento implementado; decisões normativas e histórico de evolução permanecem em `docs/architecture.md`, `docs/vision.md` e `docs/milestones.md`.

## 1. Propósito e fronteira

Atlas DataFlow é uma camada de publicação para estudos pessoais de datasets e análise preditiva. Seu produto final é uma experiência web por dataset, composta por contexto, métricas, visualizações, documentação e, quando aplicável, interação preditiva.

O projeto deliberadamente possui uma interface com qualidade de produto, porém não é uma plataforma comercial, multi-tenant ou de MLOps. O admin atende um operador privado responsável por integrar, revisar e publicar os próprios estudos.

## 2. Estado atual

- Milestone operacional ativo: `M53 — Security Validation and Public Readiness`.
- Último milestone concluído: `M52 — Governed Public Inference Gateway and Usage Control`.
- M53 é um milestone de validação orientado a evidência: não adiciona capability de produto e ainda não possui resultado de readiness registrado (ver seção 9).
- Capabilities com perfil `current_supported`:
  - `binary-predictive-classification.v1`;
  - `multiclass-predictive-classification.v1`;
  - `continuous-predictive-regression.v1`;
  - `univariate-predictive-forecasting.v1`.
- Datasets públicos registrados:
  - `telco-customer-churn`;
  - `dry-bean`;
  - `concrete-compressive-strength`;
  - `nottem`.
- Cada dataset possui uma release ativa explícita no registry.
- O frontend oferece Home pública, Dataset Detail e área administrativa privada.
- O forecasting univariado pode declarar a predição pública como não aplicável; nesse caso o Dataset Detail omite a aba Inference e apresenta avaliação e diagnósticos.

## 3. Fluxo arquitetural

```mermaid
flowchart TB
    study["Estudo científico externo"] --> authoring["Autoria Atlas-native"]
    authoring --> pipeline["Pipeline e contratos"]
    pipeline --> candidate["Release candidate"]
    candidate --> publisher["Publisher"]
    publisher --> release["Release imutável"]
    release --> registry["Registry e snapshot público"]
    registry --> runtime["API e runtime"]
    runtime --> frontend["Frontend público"]
    admin["Admin privado"] --> publisher
    admin --> registry
```

### 3.1 Estudo científico externo

O estudo externo é uma referência de autoria. Ele possui notebooks, scripts, testes e evidências próprios para exploração, preparação, comparação de famílias, seleção e avaliação final.

O Atlas pode consultá-lo enquanto traduz conclusões científicas revisadas, mas não deve:

- importar o projeto como pacote de runtime;
- montar seu diretório em produção;
- ler seus paths, artifacts, evidence ou model bytes durante inferência;
- depender da continuidade do layout externo após a autoria.

Uma revisão específica do estudo pode ser pinada em um contrato científico (`pipeline/scientific-studies/<dataset>/study-<commit>/`) e reproduzida de forma independente pelo Atlas. Essa `scientific_reproduction_run` produz um relatório write-once comparado com a evidência de referência do estudo e é uma linhagem separada do treino nativo e das releases. Veja [scientific-reproduction.md](scientific-reproduction.md).

### 3.2 Notebook de integração

Cada dataset possui um notebook canônico em `notebooks/datasets/<dataset>/dataset_integration.ipynb`. Ele é a superfície humana de orquestração da integração e deve reutilizar os módulos genéricos do pipeline.

O notebook verifica o input Atlas-owned, registra intenção semântica, materializa artefatos governados e conduz a geração de uma run validada. Ele não deve concentrar regras genéricas, promover releases silenciosamente ou manter estado durável apenas na memória do kernel.

### 3.3 Pipeline

`pipeline/` materializa e valida:

- discovery evidence;
- semantic intent;
- preparação e splits/backtesting;
- capability profile;
- contratos público, de execução e de runtime;
- training records e model cards;
- métricas e visualizações;
- model artifact e inference bundle;
- release candidate e resultado terminal da run.

O comportamento genérico é selecionado por capability, não por condições do tipo `if dataset_slug == ...`.

### 3.4 Publisher e release

`publisher/` valida consistência, hashes, completude e compatibilidade antes de promover um candidate.

Uma release promovida é um pacote imutável que reúne contratos, bundle, modelo, métricas, model card, contexto e visualizações. O runtime resolve o modelo a partir da release ativa; não existe dependência operacional em um model store paralelo do estudo externo.

### 3.5 Registry e publicação editorial

`registry/` possui responsabilidades distintas:

- identidade pública do dataset;
- `active_release` explícita;
- predict views e customizações;
- profile draft privado;
- snapshot público publicado;
- visibilidade do snapshot;
- evidências e stores de estado.

O perfil editorial pode alterar título, texto, tema, card, documentação e apresentação. Ele não pode redefinir target, feature names, tipos, validação, semântica do resultado ou comportamento do modelo.

### 3.6 API e runtime

`api/` serve endpoints públicos para catálogo, Dataset Detail, contrato, métricas, contexto, model card, visualizações, views e inferência. Também expõe operações administrativas somente quando `ATLAS_ADMIN_ENABLED=true`.

Duas camadas de identidade ficam acima do runtime. A inferência pública chega por uma Supabase Edge Function (`inference-gateway`), que verifica o JWT de Anonymous Auth do visitante, reserva uma cota por sujeito e dataset (429 antes de chegar ao Atlas) e encaminha ao Atlas com uma credencial de gateway compartilhada; leituras públicas de Home e Dataset Detail vão direto à API. As operações administrativas exigem o modo runtime privado e a identidade exata do operador, verificada pelo backend a partir de um token de sessão Supabase. As proteções de contenção do runtime (limite de payload, limitador de concorrência, hardening) permanecem abaixo do gateway. Detalhes operacionais: `docs/operations/inference-gateway-operations.md` e `docs/operations/admin-operator-provisioning.md`.

O processo principal da API é o runtime de inferência canônico. `runtime/inference.py` é o boundary governado de carregamento e execução, e `api/` resolve release, manifest, bundle e contrato antes de delegar a ele — não há um segundo serviço de inferência nem um cliente HTTP interno. O pacote de release é o boundary de ownership do modelo. Um modelo ou runtime incompatível é bloqueado/reconciliado no gate, nunca despachado para um serviço alternativo.

### 3.7 Frontend

`web/` implementa:

- Home pública;
- Dataset Detail orientado pela release e capability;
- métricas, visualizações e tooltips adaptativos;
- formulários e resultados por tipo de problema;
- documentação Markdown;
- Dashboard privado;
- Dataset Admin com oito áreas de curadoria;
- Settings e Help.

Os componentes de Live Preview reutilizam os mesmos componentes públicos, evitando uma segunda implementação visual divergente.

## 4. Superfícies e rotas

### Públicas

| Rota | Responsabilidade |
|---|---|
| `/` | catálogo de datasets publicados |
| `/dataset/:slug` | Dataset Detail |
| `/dataset/:slug/view/:viewId` | view preditiva específica |

O Dataset Detail possui `Overview`, `Inference` e `Documentation` quando a release declara predição pública disponível. Quando a capability indica `not_applicable`, a aba `Inference` é omitida.

### Privadas

| Rota | Responsabilidade |
|---|---|
| `/admin/dashboard` | runs, Dataset Details e promoção |
| `/admin/dataset-detail` | curadoria e publicação |
| `/admin/settings` | nome exibido do operador |
| `/admin/help` | orientação do fluxo administrativo |

`/admin` redireciona para o Dashboard. `/admin/dataset-admin` é um alias legado que redireciona para `/admin/dataset-detail`.

## 5. Abas do Dataset Admin

| Aba | Responsabilidade |
|---|---|
| Public Content | título, subtítulo, resumo, fonte e data editorial |
| Metadata & Card | ícone/imagem, descrição da Home e foco de performance |
| Theme Preset | seleção de tokens visuais controlados |
| Inference Form | composição do formulário público sem alterar o contrato técnico |
| Result Card | copy e apresentação do resultado por capability |
| Documentation | edição e preview de Markdown |
| Publishing | visibilidade, aprovação e console operacional |
| Live Preview | preview real do Dataset Detail ou card da Home |

`Inference Form` e `Result Card` são ocultadas quando a capability não oferece autoria de predição pública. Estado editorial dormente pode ser preservado sem ser exposto.

## 6. Autoridade dos artefatos

| Artefato | Autoridade |
|---|---|
| Capability profile | aplicabilidade de roles e modo de runtime/publicação |
| Execution/runtime/public contract | schema, validação, input e projeção pública segura |
| Inference bundle | feature order, preprocessing, modelo e output |
| Model card e metrics | evidência reduzida da release |
| Visualizations | dados analíticos públicos governados |
| Release manifest | integridade e referências content-addressed |
| Registry | dataset e release ativa |
| Profile draft | edição privada |
| Published snapshot | apresentação pública determinística |
| Visibility record | exposição pública do snapshot |

## 7. Modos de execução

### Privado/local

`docker-compose.yml` habilita admin no backend e no frontend e publica o web apenas em `127.0.0.1:15174` por padrão. É apropriado para operação local ou por túnel SSH.

### Público

`docker-compose.prod.yml` desabilita admin no backend e no build web. O stack expõe serviços apenas para composição com uma camada de proxy/rede externa. HTTPS, domínio público e certificados válidos devem ser fornecidos pelo ambiente de deployment; o `Caddyfile` versionado usa TLS interno e não representa uma configuração pronta para internet.

Não existe login público no admin; o acesso privado exige a identidade do operador provisionado (sessão Supabase verificada pelo backend). Portanto, habilitar o admin e expô-lo diretamente à internet é uma configuração inválida para a primeira versão.

## 8. Organização de `.py` e `.json`

Separar arquivos apenas por extensão não é recomendado. `pipeline/`, `publisher/` e `registry/` são bounded areas: os módulos Python, schemas, exemplos e pequenos documentos de configuração possuem ownership comum e podem ser revisados atomicamente.

A separação que realmente importa é por função e lifecycle:

- schemas e configurações estáveis;
- código produtor/validador/consumer;
- instâncias por dataset;
- runs geradas;
- evidências;
- candidates;
- releases imutáveis;
- estado editorial mutável.

O repositório já aplica boa parte dessa separação com subdiretórios como `pipeline/capabilities/`, `pipeline/evidence/`, `pipeline/training-runs/`, `publisher/runs/`, `registry/profile-snapshots/` e `releases/`.

Uma migração ampla para `schemas/` ou `state/` dentro de cada área pode ser considerada no futuro se a navegação continuar difícil, mas não é uma correção obrigatória antes da abertura pública. Muitos paths são parte de contratos, manifests, testes e hashes; mover arquivos agora teria custo de compatibilidade desproporcional. O ganho imediato mais seguro é documentar ownership e adicionar READMEs locais às áreas com maior densidade.

Nunca criar um diretório global `json/`: ele misturaria schemas, configuração, evidência, estado mutável e pacotes de release que possuem lifecycle e responsáveis diferentes.

## 9. Segurança e fronteira de readiness (M53)

### 9.1 Controles mantidos pelo repositório

Os milestones M50–M52 e as specs de hardening subsequentes deixaram no repositório os seguintes controles. Eles descrevem o que está implementado e versionado, não o resultado de uma validação ao vivo:

- **Fronteira privado/público** — o modo privado (`docker-compose.yml`) habilita o Admin e exige a identidade do operador provisionado; o modo público (`docker-compose.prod.yml`) desabilita o Admin no backend e no build web, e a superfície Admin não é exposta publicamente (seção 7).
- **Identidade e gateway (Supabase)** — o Supabase é dono da identidade do operador Admin, da identidade anônima do visitante, do estado de cota de inferência e do boundary do gateway (`inference-gateway`); o Atlas aceita inferência pública apenas pela credencial do gateway (seção 3.6). Operação: `docs/operations/inference-gateway-operations.md` e `docs/operations/admin-operator-provisioning.md`.
- **Contenção do runtime** — limite de payload, limitador de concorrência e hardening de contêiner (usuário não-root, filesystem read-only, `no-new-privileges`, `cap_drop: ALL`) permanecem abaixo do gateway.
- **Proveniência da imagem da API** — `tests/test_api_deployment_image_invariants.py` verifica estaticamente que as definições pública e privada da API compartilham o mesmo build e o mesmo envelope de segurança. Isso é uma invariante das definições de deployment, não prova de que as imagens em execução sejam idênticas.
- **Recuperação de desastre** — `docs/operations/disaster-recovery.md` define o contrato de recuperação (classes de ativos, cenários de perda, ordem de restauração e evidência reduzida). A existência do runbook não comprova que backup ou restore tenham sido executados.

### 9.2 Fronteira de evidência

A readiness do M53 é derivada exclusivamente de evidência registrada, conforme o contrato do milestone em `docs/milestones.md`. O resultado agregado só pode ser `ready`, `ready_with_documented_reservations` ou `blocked`, e nenhum desses valores foi registrado até o momento. Este documento não declara o M53 concluído nem o Atlas pronto para exposição pública.

Itens que permanecem pendentes de evidência ao vivo e não devem ser lidos como concluídos:

1. limites de CPU, memória e PID — nenhum valor está definido no repositório; a medição e o mecanismo de enforcement estão pendentes (`docs/operations/inference-gateway-operations.md`);
2. backup e restore — o contrato existe, mas nenhum exercício de restauração está registrado como evidência (`docs/operations/disaster-recovery.md`);
3. identidade das imagens em produção — a igualdade de proveniência é estática; a identidade das imagens efetivamente implantadas não está evidenciada;
4. suítes de auth, gateway/cota, runtime, payload, infraestrutura e regressão exigidas pelo M53 — devem ser executadas e registradas antes de qualquer resultado de readiness;
5. deployment público com domínio e certificado válidos — o `Caddyfile` versionado usa `tls internal`.

O checklist histórico de abertura pública da primeira versão (M49) foi substituído por esta fronteira; seus resultados permanecem em `docs/operations/first-version-readiness.md`.

## 10. Referências

- `docs/architecture.md` — decisões normativas e arquitetura acumulada;
- `docs/vision.md` — propósito e não objetivos;
- `docs/milestones.md` — evolução planejada;
- `docs/project-status/milestone-state.json` — cursor operacional;
- `docs/operations/inference-gateway-operations.md` — gateway, cota e limites pendentes;
- `docs/operations/admin-operator-provisioning.md` — provisionamento do operador Admin;
- `docs/operations/disaster-recovery.md` — contrato de recuperação de desastre;
- `docs/operations/dataset-onboarding-path.md` — narrativa de onboarding;
- `docs/operations/release-flow.md` — checklist de release;
- `pipeline/capabilities/` — capabilities atualmente contratadas;
- `registry/datasets.json` — datasets e releases ativas.


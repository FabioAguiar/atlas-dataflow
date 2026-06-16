# Architecture

## Purpose

This document records the high-level architecture of Atlas DataFlow.

It guides future technical decisions, milestone planning, issue generation, and implementation handoffs. The document defines responsibilities, boundaries, flows, artifacts, and architectural validation criteria, without executing implementation and without replacing future planning or operational documents.

This document is not a roadmap, backlog, task list, execution plan, patch, complete infrastructure specification, or implementation map.

## Architecture Summary

Atlas DataFlow is a web platform for publishing predictive experiences per dataset.

The proposed architecture is `dataset-centric`, `contract-first`, `release-oriented`, and suitable for deployment on a VPS with containers. Each published dataset has its own identity, an active release, and an associated public experience.

In the first public cycle, Atlas should operate with:

- one public experience per dataset;
- one active release per dataset;
- an initial file-based registry;
- runtime resolving publications by `dataset_slug` and `active_release`;
- contracts as the source of truth for validation, inference, and guided rendering;
- published releases treated as immutable;
- an internal publisher for generating, validating, and promoting releases;
- no public administration in the first cycle;
- eventual internal administration accessible only through a private surface, such as a local network, SSH tunnel, or equivalent mechanism.

The initial architecture does not depend on a database, multi-user operation, marketplace, public upload, complex administrative panel, or complete administrative framework.

## Context Derived from the Vision

The Atlas vision defines a platform capable of transforming data studies into web-based predictive experiences that can be published per dataset.

The points from the vision that most influence the architecture are:

- each published dataset must have its own identity;
- the public experience must present context, data information, metrics, visualizations, and predictive interaction;
- contracts must act as the source of truth for forms, inference, and consistency;
- the interface must not concentrate business logic;
- published artifacts must maintain a traceable link between dataset, contract, model, metrics, and publication;
- exploration, artifact generation, publication, and public consumption must be separated;
- internal services must not be part of the public surface;
- the first delivery must be small, safe, and demonstrable;
- the architecture must be simple enough to publish early and flexible enough to support new datasets later.

## Architectural Objectives

The architecture must ensure:

- publication of predictive experiences per dataset;
- explicit resolution of dataset and active release;
- separation between public runtime, internal tooling, and published artifacts;
- contracts as the primary reference for validation and guided rendering;
- low coupling between interface, model, contract, and pipeline;
- secure public operation, with minimal exposure;
- traceability between contract, bundle, metrics, model card, and release;
- clear versioning of structural artifacts;
- ability to validate releases before publication;
- preservation of previous releases;
- simplicity proportional to the first public cycle;
- possibility of evolving toward multiple datasets without a complete redesign.

## Architectural Non-Objectives

The initial architecture does not intend to solve:

- public upload of datasets;
- public creation of pipelines by third parties;
- model retraining through the public interface;
- public editing of contracts;
- complete administrative panel;
- multi-user operation;
- multiple organizations;
- marketplace for models or datasets;
- complex authentication and authorization;
- sophisticated versioning of experiments;
- distributed orchestration of pipelines;
- mandatory queues and workers;
- database as a mandatory source of truth;
- public exposure of internal tools;
- full coverage of the MLOps lifecycle.

These points may be reevaluated in future stages, but they should not guide the architecture of the first public cycle.

## Architectural Drivers

The main architectural drivers are:

- real web publication, not only local execution;
- operation on a VPS with containers and HTTPS;
- need to keep the public surface small;
- use of contracts to reduce rule duplication between backend and frontend;
- need to trace published artifacts;
- expectation of multiple datasets in the future;
- low initial maintenance cost;
- low tolerance for coupling between pipeline and runtime;
- need to validate releases before making them active;
- incremental evolution, without anticipating complex administration;
- documentation searchable by humans and technical support tools.

## Principles and Constraints

The architecture must respect the following principles:

- The dataset is the main unit of publication.
- The release is the main unit of public versioning.
- The public runtime resolves inference by `dataset_slug` and `active_release`.
- There must not be a global contract or bundle as the platform's source of truth.
- The contract defines structure, validation, input domain, and interface hints.
- The public interface interprets the public contract, but does not redefine validation semantics.
- The model executes inference, but does not redefine the schema.
- Publications must be explicit, validated, and traceable.
- Published releases must not be silently overwritten.
- The internal publisher must exist before any web administration.
- Internal administration, when it exists, must orchestrate publisher operations, not duplicate logic.
- Internal services must not be exposed publicly.
- Secrets, real environment variables, local databases, volumes, and raw logs must not be versioned.
- Technical decisions must remain proportional to the goal of publishing a functional experience early.

## Main Components or Areas

The architecture is organized into the following main areas:

### Public Web Experience

Layer responsible for navigation and presentation of published experiences.

It must present datasets, context, visualizations, metrics, predictive form, and inference result. The public web experience must consume data and contracts exposed by the public API, without concentrating business rules.

### Public Runtime API

Layer responsible for providing public endpoints for querying datasets, public contracts, metrics, and inference.

The public API must resolve the requested dataset, identify the active release, load the required published artifacts, validate inputs, and execute inference.

### Published Dataset Registry

Source of resolution between datasets and active releases.

In the first public cycle, the registry must be file-based. It declares which datasets are published, which release is active for each dataset, and which public metadata can be consumed.

### Published Releases

Immutable packages that materialize a dataset publication.

A release must contain the artifacts required for the public experience and for the inference runtime, including contracts, predictive bundle, metrics, model card, context, and manifest.

### Contract Layer

Area responsible for defining and validating contracts used by the runtime and by the interface.

The architecture must differentiate runtime contract and public contract. The runtime contract guides validation and inference. The public contract provides a safe projection for rendering and consumption by the web experience.

### Inference Runtime

Area responsible for loading published artifacts and executing predictions.

The runtime must be deterministic with respect to the active release and must not execute training, data preparation, notebooks, or publication.

### Internal Publisher

Internal tooling responsible for generating, validating, and promoting releases.

The publisher transforms artifacts generated by the pipeline into controlled publications. It validates completeness, calculates hashes, generates the manifest, and updates the registry explicitly.

### Artifact Build Pipeline

Area responsible for preparation, training, evaluation, and generation of candidate artifacts.

The pipeline is not part of the public surface. It produces artifacts that can be validated and promoted by the publisher.

### Future Internal Administration

Optional private surface for operating publication, validation, and querying internal states.

This layer is not part of the first public cycle. When it exists, it must be accessible only through a private surface, such as an SSH tunnel, internal network, or equivalent mechanism, and must call existing publisher operations.

### Deployment and Operations

Area responsible for packaging, configuration, container execution, HTTPS, environment variables, and separation between public and internal surfaces.

Operation must consider VPS and containerized environment from the beginning.

## Responsibilities

### Public Web Experience

Responsibilities:

- list published datasets;
- present public dataset information;
- render predictive form from the public contract;
- send inference payloads to the API;
- present public responses and errors in an understandable way;
- avoid duplicated business logic;
- not access internal artifacts directly.

### Public Runtime API

Responsibilities:

- expose a simple public healthcheck;
- list published datasets;
- expose public dataset metadata;
- expose public contract;
- expose public metrics;
- receive inference requests;
- validate payloads against the runtime contract;
- load the active release bundle;
- execute prediction;
- return structured response;
- hide internal paths and sensitive details.

### Registry

Responsibilities:

- declare published datasets;
- declare active release per dataset;
- point to publication metadata and artifacts;
- avoid heuristic discovery of publications;
- allow structural validation of the published state.

### Release

Responsibilities:

- group artifacts of a publication;
- preserve the link between contract, model, metrics, and experience;
- record hashes and relevant metadata;
- allow high-level operational reproducibility;
- remain immutable after publication.

### Contracts

Responsibilities:

- define accepted features;
- define types, domains, and validations;
- define interface hints when applicable;
- guide inference payloads;
- separate public projection from internal details;
- carry schema version when applicable.

### Inference Runtime

Responsibilities:

- load artifacts from the active release;
- validate inputs;
- execute prediction;
- produce stable response;
- handle predictable errors;
- not modify published artifacts.

### Internal Publisher

Responsibilities:

- validate release candidate;
- calculate hashes;
- generate manifest;
- promote validated release;
- update registry explicitly;
- preserve previous releases;
- prevent publication of incomplete packages;
- provide a future foundation for internal administration.

### Pipeline

Responsibilities:

- prepare data;
- train model;
- evaluate model;
- generate metrics;
- generate contracts;
- export bundle;
- produce candidate artifacts for publication.

### Future Internal Administration

Potential responsibilities:

- query releases and candidates;
- trigger publisher validations;
- promote release through controlled operation;
- query operational evidence;
- operate only on a private surface.

It is not the responsibility of internal administration to expose features to the external public.

## Boundaries

### Public Experience vs Internal Surface

The public experience includes pages and endpoints required for consuming published datasets.

Internal surfaces include publisher, pipeline, sensitive logs, operational tools, private administration, databases, volumes, and infrastructure.

The internal surface must not be exposed directly to the public internet.

### Pipeline vs Runtime

The pipeline builds artifacts.

The runtime consumes published artifacts.

The runtime must not train models, execute notebooks, prepare datasets, or publish releases during public requests.

### Run vs Release Candidate vs Published Release

A run is a technical execution.

A release candidate is a package candidate for publication.

A published release is a validated and promoted package.

Not every run should become a release. Promotion must be explicit.

### Dataset vs Release

Dataset is the public identity.

Release is the materialized version of that identity.

A dataset may have multiple releases over time, but the first public cycle must operate with only one active release per dataset.

### Contract vs Model

The contract defines the valid input structure and metadata required for consistency.

The model executes inference.

The model does not redefine the schema, and the contract must not assume nonexistent artifacts.

### Contract vs Interface

The public contract guides the interface.

The interface must not invent canonical validations or accept payloads that the runtime contract would reject.

### Publisher vs Internal Administration

The publisher contains the operational logic for validation and promotion.

Internal administration, when it exists, must only orchestrate or trigger operations already available in the publisher.

### Application vs Infrastructure

Containers, VPS, proxy, HTTPS, volumes, environment variables, and deployment tooling belong to infrastructure.

These elements must support the application, but they do not compose the product's public experience.

## Main Flows

### Internal Publication Flow

Data study or pipeline

→ generation of candidate artifacts

→ assembly of release candidate

→ validation by the publisher

→ hash calculation and manifest generation

→ explicit promotion to published release

→ registry update

→ availability in the public runtime

### Public Query Flow

Visitor accesses a dataset experience

→ interface requests public metadata

→ API resolves `dataset_slug`

→ registry informs `active_release`

→ API returns public dataset information

→ interface presents context, visualizations, and metrics

### Public Inference Flow

Visitor fills out form

→ interface builds payload from the public contract

→ API receives inference request

→ API resolves `dataset_slug` and `active_release`

→ API loads runtime contract

→ API validates payload

→ API loads bundle from the active release

→ runtime executes prediction

→ API returns structured response

→ interface presents result

### Future Internal Administration Flow

Operator accesses private surface

→ queries release candidates or existing releases

→ triggers controlled validation or promotion

→ internal layer calls the publisher

→ publisher validates and updates published state

→ operator queries result

This flow must remain outside the public surface.

## Relevant Data, Artifacts, or Documents

Artifacts relevant to the architecture:

- `docs/vision.md`: source of the project's high-level direction;
- `docs/architecture.md`: source of boundaries and architectural decisions;
- `docs/milestones.md`: future incremental planning document;
- published dataset registry;
- public dataset metadata;
- release manifest;
- runtime contract;
- public contract;
- inference bundle;
- public metrics;
- model card;
- public dataset context;
- publishable visualizations or descriptions;
- release validation evidence, when applicable.

Artifacts that must not be treated as the formal public source of truth:

- exploratory notebooks;
- raw logs;
- local volumes;
- local databases;
- real `.env`;
- sensitive payloads;
- temporary execution outputs;
- intermediate files that have not been promoted.

## Runtime, Tooling, and Workflows

### Public Runtime

The public runtime is composed of the public API and the public web experience.

It must operate only on published datasets and releases. It must not depend on temporary pipeline state, recent runs, or implicit local paths.

### Internal Tooling

Internal tooling includes publisher, controlled scripts, validations, and eventual operational commands.

This tooling may generate and promote releases, but it must not be exposed as a public feature.

### Workflows

Relevant workflows must remain simple in the first public cycle:

- generation of candidate artifacts;
- release validation;
- release promotion;
- public consumption of the experience;
- inference by contract and active release.

More advanced automation may be added later, as long as it does not break the boundaries between pipeline, publisher, and runtime.

### Internal Administration

Internal administration is optional and future-facing.

When it exists, it must be accessible only through a private surface and must consume publisher operations. It must not duplicate publication rules or turn long HTTP requests into fragile execution of heavy pipelines.

## Security, Versioning, and Traceability

### Security

The architecture must preserve:

- HTTPS on the public surface;
- CORS restricted to the expected public domain;
- no secrets in the frontend;
- no versioned real `.env`;
- no public endpoints for training, upload, or publication;
- no public administrative panel in the first cycle;
- hiding internal paths in error responses;
- payload limit for inference;
- logs without unnecessary sensitive data;
- internal services outside the public internet.

### Versioning

The architecture must explicitly version or identify:

- registry schema;
- release manifest schema;
- contract schemas;
- dataset release;
- inference bundle;
- published metrics;
- model card or public release documentation.

### Traceability

Each publication must make it possible to identify:

- which dataset was published;
- which release is active;
- which contracts were used;
- which bundle was used;
- which metrics were published;
- which hashes validate the artifacts;
- when the release was created or promoted;
- which manifest describes the publication.

### Immutability

Published releases must not be silently overwritten.

Changes to contract, model, metrics, or public dataset documentation must generate a new release or a new controlled promotion, preserving history compatible with the stage of the project.

### Public Error Policy

The public API must expose predictable and non-sensitive errors.

Expected categories include:

- dataset not found;
- release not available;
- contract invalid or unavailable;
- invalid payload;
- inference unavailable;
- internal failure without leaking sensitive details.

## Implementation Documentation Strategy

Selected strategy: `milestones-only`.

Justification:

Atlas is still at the initial architectural definition stage. The architecture has multiple relevant areas, but the implementation should still start small, with one dataset, one active release, file-based registry, public runtime, and internal publisher. At this stage, `docs/milestones.md` should be sufficient to guide continuity without creating additional documentation maintenance cost.

The absence of an Implementation Map is not a failure at this stage. A dedicated map would be premature before there is enough concrete implementation to justify navigation by area.

The decision must be reviewed when one or more of the following conditions occur:

- the project has multiple implemented areas evolving in parallel;
- the context cost for AI-assisted continuity becomes high;
- handoffs begin to require navigation across many files and modules;
- there is recurring difficulty locating responsibilities;
- multiple internal flows start evolving independently;
- publisher, runtime, contracts, frontend, pipeline, and deployment have their own operational documentation.

If this review indicates a need for cumulative documentation, the next candidate strategy should be `implementation-map-single`. If the project grows into highly independent areas, `implementation-map-hierarchical` may be evaluated.

When created, cumulative documentation must guide navigation and context. It must not replace real files, contracts, tests, manifests, code, or execution evidence.

Cumulative documentation must not be used as a changelog, commit list, backlog, or absolute source of truth. Future issues and handoffs authorize concrete execution; architectural documentation and milestones only provide guidance.

## Expected Impact on Milestones

The architecture should guide future milestones to prioritize:

- documented foundation and boundaries before broad implementation;
- minimal bootstrap of the public API and web experience;
- definition of the file-based registry;
- definition of the minimum release format;
- validation of contract and release before public inference;
- implementation of the internal publisher before any web administration;
- publication of a first dataset experience;
- secure public deployment with containers and HTTPS;
- security validations before public exposure;
- postponement of multi-user operation, marketplace, public upload, and complex administration.

Future milestones must preserve small, validatable, regression-safe increments, avoiding turning the architecture into a plan that is too large for the first public cycle.

## Risks and Trade-offs

### Simplicity vs Extensibility

File-based registry reduces initial complexity, but may require future migration if there are many datasets, richer administration, or multi-user operation.

### Internal Publisher vs Admin Web

Starting with the internal publisher reduces risk and improves testability. The disadvantage is less operational comfort until an internal interface exists.

### Immutable Release vs Manual Agility

Immutable releases increase traceability, but require discipline to generate a new publication when artifacts change.

### Public Contract vs Runtime Contract

Separating public contract and runtime contract increases security and clarity, but adds responsibility for keeping projections consistent.

### No Database Initially vs Advanced Querying

Avoiding a database simplifies the first public cycle. Historical queries, permissions, and advanced administration may require structured persistence in the future.

### Private Admin vs Convenience

Keeping admin outside the public surface reduces risk, but requires operation through an SSH tunnel, private network, or equivalent mechanism.

### No Complete Administrative Framework Initially

Avoiding a complete administrative framework keeps the focus on runtime and publisher. Future adoption can be reevaluated if requirements emerge for persistent CRUD, multi-user operation, permissions, and frequent manual management.

## Accepted First-Cycle Architectural Decisions

The following decisions are accepted for the first public cycle and define boundaries for later bootstrap issues. They are documentation-level architectural decisions, not implementation steps.

- Atlas starts as a dataset-centric, contract-first, release-oriented platform for publishing predictive experiences.
- The first public cycle supports one public experience per dataset and one active release per dataset.
- The public runtime resolves publications by `dataset_slug` and `active_release`.
- The initial registry remains file-based, explicit, and validatable.
- Published releases are immutable packages that connect dataset, contract, predictive bundle, metrics, model card, context, and manifest.
- Traceability between dataset, contract, model, metrics, release, and publication is mandatory.
- Pipeline, publisher, public runtime, public web experience, contracts, and published artifacts remain separate responsibilities.
- The internal publisher validates completeness, calculates hashes, generates the manifest, and promotes releases explicitly before any web administration exists.
- The public surface exposes only public experiences, public contracts, public metadata, metrics, and inference endpoints required for application consumption.
- Internal tooling, publisher operations, pipeline work, sensitive logs, operational tools, databases, volumes, infrastructure, and future administration remain outside the public surface.
- No public administration exists in the first public cycle.
- Future internal administration, if introduced, must use a private surface and orchestrate existing publisher operations instead of duplicating publication logic.
- The first public cycle does not require a database, multi-user operation, marketplace, public upload, public retraining, or complex administration.
- Public deployment is considered part of the initial path and must preserve secure boundaries around secrets, internal services, logs, and runtime artifacts.
- The implementation documentation strategy for the initial stage is `milestones-only`; a dedicated Implementation Map is deferred until concrete implementation complexity justifies it.

Pending product and technical choices remain outside this accepted list. In particular, the first dataset, final API and web stack, exact registry and contract formats, release manifest schema, dataset and release naming conventions, published artifact directory structure, backup strategy, log policy, visualization approach, and future internal administration access mechanism still require explicit decisions.

## Gaps and Pending Decisions

Pending decisions:

- choose the first published dataset;
- define the final technical stack for API and web;
- define the exact registry format;
- define the release manifest schema;
- define the public contract format;
- define the runtime contract format;
- define the minimum format of published metrics;
- define the model card standard;
- define the `dataset_slug` convention;
- define the `release_id` convention;
- define the final directory structure for published artifacts;
- define the operational backup strategy for releases;
- define the minimum log policy;
- define the exact access mechanism for future internal administration;
- define whether the publisher will be exposed only as a CLI or also as an internal service in a later stage;
- define whether visualizations will be static, derived from artifacts, or served by the API.

Known gaps:

- the expected scale of datasets is not yet defined;
- the expected inference volume is not yet defined;
- the future need for a database is not yet confirmed;
- the way public visualizations will be generated still needs to be defined;
- the observability strategy still needs to be made proportional;
- the semantic versioning policy for schemas still needs to be detailed.

## Architectural Validation Criteria

The architecture will be considered adequate if it:

- is aligned with the Atlas vision;
- allows a first public experience per dataset;
- resolves runtime by `dataset_slug` and `active_release`;
- avoids a global contract or bundle as the source of truth;
- keeps the initial registry file-based;
- separates pipeline, publisher, runtime, and web experience;
- preserves the contract as the source of truth for validation and guided rendering;
- prevents the interface from concentrating business logic;
- treats published releases as immutable;
- keeps administration outside the public surface;
- does not require a database, multi-user operation, or complex admin in the first cycle;
- preserves traceability between dataset, contract, bundle, metrics, and release;
- considers public deployment with containers, HTTPS, and environment-based configuration;
- does not expose secrets, raw logs, internal paths, or internal services;
- guides future milestones without becoming a roadmap;
- declares a proportional documentation strategy;
- records risks and pending decisions without resolving them by inference.

## Notes for Future Milestones

Future milestones must use this architecture as a scope boundary, not as an implementation list.

Incremental planning should begin with the minimum foundations:

- contracts and registry;
- release manifest;
- public runtime;
- internal publisher;
- public web experience;
- minimum security;
- containerized deployment.

Internal administration should be considered only after the publisher is defined, testable, and capable of validating and promoting releases without depending on a web interface.

Features such as public upload, multi-user operation, marketplace, multiple organizations, complex administration, mandatory database, and public retraining must remain outside the first stages unless there is an explicit future architectural decision.

# Architecture

## Purpose

This document records the high-level architecture of Atlas DataFlow.

It guides future technical decisions, milestone planning, issue generation, and implementation handoffs. The document defines responsibilities, boundaries, flows, artifacts, and architectural validation criteria, without executing implementation and without replacing future planning or operational documents.

This document is not a roadmap, backlog, task list, execution plan, patch, complete infrastructure specification, or implementation map.

At the current stage, this architecture also authorizes the transition from a contract-driven runtime foundation into a design-backed product surface composed of public dataset experiences and a private administrative curation layer.

## Architecture Summary

Atlas DataFlow is a web platform for publishing predictive experiences per dataset.

The architecture is `dataset-centric`, `contract-first`, `release-oriented`, `profile-aware`, and suitable for deployment on a VPS with containers. Each published dataset has its own identity, an active release, an associated public experience, and public presentation state derived from controlled artifacts rather than frontend hardcoding.

The project has already established a contract-driven foundation. The next architectural stage makes that foundation visible through product screens while preserving deterministic boundaries between generated runs, release candidates, public profiles, drafts, previews, published snapshots, visibility, and runtime inference.

In the next complete public/admin cycle, Atlas should operate with:

- one public experience per published dataset;
- one active release per published dataset;
- registry-driven dataset discovery;
- published releases treated as immutable artifact packages;
- contracts as the source of truth for validation, inference, form structure, and guided rendering;
- public contract projections that expose only public-safe rendering data;
- public dataset profiles for presentation metadata, home-card content, theme, ordering, and descriptive content;
- deterministic draft, preview, published snapshot, and visibility semantics;
- generated runs discoverable only through a private administrative surface;
- a private Dashboard for run discovery and dataset publication preparation;
- a private Dataset Admin screen for curation, preview, publishing, and visibility control;
- minimal private Settings and Help screens;
- Telco and Bank allowed as seeded examples or fixtures, but not as permanent hardcoded product assumptions;
- public runtime resolving publications by `dataset_slug`, `active_release`, public snapshot, and visibility state;
- internal publisher and validation logic remaining authoritative over publication rules;
- no public upload, public retraining, public administration, marketplace, multi-tenant administration, or broad MLOps platform behavior.

The initial architecture still does not require a database, multi-user operation, marketplace, public upload, complex authorization model, or complete administrative framework. These may be considered later only if they become necessary for correctness, security, or maintainability.

## Context Derived from the Vision

The Atlas vision defines a platform capable of transforming data studies into web-based predictive experiences that can be published per dataset.

The points from the vision that most influence the architecture are:

- each published dataset must have its own identity;
- the public experience must present context, data information, metrics, visualizations, and predictive interaction;
- contracts must act as the source of truth for forms, inference, validation, and consistency;
- public-safe contract projections must provide categorical/select options and UI hints without leaking internal details;
- the interface must not concentrate business logic;
- published artifacts must maintain a traceable link between dataset, run, contract, model, metrics, public profile, snapshot, and publication;
- exploration, artifact generation, run discovery, curation, publication, runtime inference, and public consumption must be separated;
- internal services, generated runs, operational tools, draft states, and administration routes must not be part of the public surface;
- the first complete product surface must be small, safe, demonstrable, and aligned with the design documentation under `design/`;
- design prototypes are implementation references for UX and layout, but they do not override contracts, publisher rules, artifact schemas, API boundaries, or tests;
- hardcoded example datasets can bootstrap development, but the product architecture must evolve toward registry/artifact/profile-driven datasets;
- the architecture must be simple enough to publish early and flexible enough to support new datasets later.

## Architectural Objectives

The architecture must ensure:

- publication of predictive experiences per dataset;
- explicit resolution of dataset, active release, public profile, published snapshot, and visibility state;
- separation between public runtime, private administration, internal tooling, and published artifacts;
- contracts as the primary reference for validation, inference, form structure, and guided rendering;
- public contract projections that are safe and sufficient for frontend rendering;
- low coupling between interface, model, contract, profile, publisher, and pipeline;
- secure public operation, with minimal exposure;
- private-only access to administrative routes and run discovery;
- traceability between run, contract, bundle, metrics, model card, public profile, public snapshot, and release;
- clear versioning of structural artifacts and published state;
- ability to validate releases and public publication state before activation;
- preservation of previous releases or snapshots compatible with the current stage;
- deterministic semantics for draft, preview, publish, and visibility;
- removal of permanent Telco/Bank hardcoding as product logic;
- simplicity proportional to the first complete public/admin cycle;
- possibility of evolving toward multiple datasets without a complete redesign.

## Architectural Non-Objectives

The current architecture does not intend to solve:

- public upload of datasets;
- public creation of pipelines by third parties;
- public dataset creation by third parties;
- public editing of contracts;
- public execution of notebooks;
- model retraining through the public interface;
- public administration;
- complex multi-user administration;
- multiple organizations;
- marketplace for models or datasets;
- complex authentication and authorization beyond what is necessary to keep the administrative surface private;
- sophisticated experiment management;
- distributed orchestration of pipelines;
- mandatory queues and workers;
- database as a mandatory source of truth;
- public exposure of internal tools, generated runs, operational logs, databases, or volumes;
- complete coverage of the MLOps lifecycle;
- making visual prototypes override runtime contracts, publisher validation, or artifact schemas.

These points may be reevaluated in future stages, but they should not guide the next implementation cycle.

## Architectural Drivers

The main architectural drivers are:

- real web publication, not only local execution;
- operation on a VPS with containers and HTTPS;
- need to keep the public surface small;
- need to keep admin private, proportional, and deterministic;
- use of contracts to reduce rule duplication between backend and frontend;
- need to project contract fields safely for public rendering;
- need to trace published artifacts and public presentation state;
- expectation of multiple datasets in the future;
- low initial maintenance cost;
- low tolerance for coupling between pipeline, publisher, runtime, public profile, and frontend;
- need to validate releases and publication state before making them active;
- need to replace hardcoded datasets with registry/artifact/profile-driven availability;
- need to use `design/` as the closest available deterministic UX reference;
- incremental evolution, without anticipating a complex backoffice;
- documentation searchable by humans and technical support tools.

## Principles and Constraints

The architecture must respect the following principles:

- The dataset is the main unit of publication.
- The release is the main unit of artifact versioning.
- The public snapshot is the main unit of public presentation publication.
- The public runtime resolves publications by `dataset_slug`, `active_release`, public snapshot, and visibility state.
- There must not be a global contract or bundle as the platform's source of truth.
- The contract defines structure, validation, input domain, and interface hints.
- The public contract is a safe projection of runtime-relevant contract information.
- The public interface interprets public contract and public profile data, but does not redefine validation semantics.
- The model executes inference, but does not redefine the schema.
- The public profile may customize presentation metadata, labels, ordering, theme, home-card content, and documentation, but it must not silently alter technical contract meaning.
- Draft configuration, preview state, published snapshot, and public visibility must be explicit and deterministic.
- Publications must be validated, explicit, and traceable.
- Published releases must not be silently overwritten.
- Published public snapshots must not be silently confused with drafts.
- The internal publisher remains authoritative over release validation and promotion.
- Private administration must orchestrate publisher/profile operations, not duplicate runtime or publication rules.
- Generated runs are internal operational artifacts and must not be exposed through the public surface.
- Internal services must not be exposed publicly.
- Secrets, real environment variables, local databases, volumes, and raw logs must not be versioned.
- Telco and Bank may remain as seeded examples, but new dataset support must not require frontend hardcoding.
- Technical decisions must remain proportional to the goal of publishing a functional experience early.

## Main Components or Areas

The architecture is organized into the following main areas.

## Dataset Integration Authoring Architecture

Dataset integration authoring is the governed bridge between reviewed
scientific evidence and Atlas-owned artifacts. It separates dataset-specific
semantic authoring from capability-specific generic behavior and from
downstream release, publisher, registry, and runtime operations.

### External analysis project boundary

An external analysis project may be methodologically dataset-specific and is
the source of scientific-analysis evidence. It should expose structured,
evidence-rich outputs under a future external-project standard. Lumen may
inspect those outputs at authoring time, but the project is not an Atlas
package, operational handoff, or deployed dependency. After authoring, Atlas
runtime does not mount, resolve, or require an external analysis project root,
and generic Atlas core does not infer dataset semantics from that project at
runtime.

### Lumen semantic-authoring role

Lumen performs semantic interpretation during authoring. It may consult the
external project artifacts and the current Atlas repository, review the
scientific conclusions, and translate them into dataset-specific Atlas
authoring decisions. That translation must produce governed Atlas-native
artifacts; it must not create an ongoing external filesystem dependency or
bypass Atlas contracts, integrity gates, release validation, publisher
boundaries, or public/internal evidence controls.

### Dataset integration notebook

The dataset integration notebook is dataset-specific and is the single
canonical, human-facing orchestration entrypoint for its dataset. The
canonical Telco name is
`notebooks/datasets/telco-customer-churn/dataset_integration.ipynb`.

Project Spec S0179 extended this notebook's orchestration boundary beyond
authoring alone. The notebook:

- performs controlled verification of the exact Atlas-owned input, including
  identity, drift-sensitive observations, target and identifier candidates,
  missing-value conditions, and assumptions needed for contract correctness;
- verifies external scientific evidence at authoring time against the real
  `external-evidence-index.v1` producer contract, hash-verifying every
  referenced item before use and never persisting the absolute external
  project root into a durable Atlas artifact;
- authors dataset-specific semantic intent from reviewed evidence;
- declares/resolves a capability profile by reference and invokes
  capability-aware projection;
- orchestrates external fitted-model governed materialization, governed
  inference-bundle generation, release-candidate assembly, publisher
  structural validation, and manifest generation when the current generic
  structural gate permits it -- reusing generic Atlas materializers and
  services (`pipeline/`, `publisher/`) rather than implementing reusable
  projection, release, or publisher policy in cells;
- materializes one explicit validated-run terminal outcome, persisting the
  schema-valid result the generic terminal producer returns without
  reimplementing its eligibility/hash/schema logic;
- persists durable decisions through governed Atlas-native artifacts and is
  never the sole durable source of truth;
- stops unconditionally before publisher promotion, registry
  `active_release` mutation, public visibility/profile activation, or
  runtime prediction; and
- does not repeat exploratory scientific analysis, model training, model
  selection, final-test evaluation, or threshold optimization already owned by
  an authoritative external analysis, unless a separately governed workflow
  explicitly requires it.

Atlas-owned input verification is therefore not the same activity as
re-performing scientific exploratory analysis or modeling. The former protects
the identity and correctness of the input Atlas will govern; the latter belongs
to the scientific-analysis workflow.

### Atlas-native authoring artifact suite

The architecture selects one principal coordination index over narrow,
Atlas-native artifacts with these roles:

- principal authoring manifest/index;
- source/input verification evidence;
- dataset semantic intent;
- preparation/input policy;
- capability-profile declaration;
- capability-conditional modeling and prediction evidence;
- runtime capability/profile references;
- analytical visual evidence; and
- internal provenance and integrity references.

Downstream specs implement this suite progressively. Not every named future
artifact, contract, or schema exists yet, and this architecture must not be
read as a schema, notebook, candidate, publisher, runtime, or release
implementation claim.

### Principal authoring manifest invariants

The future principal authoring manifest is a dataset-specific, immutable index
for one authoring generation. It owns coordination, generation identity,
artifact-role references, and the selected capability-profile identity and
version. Each artifact reference uses a safe repository- or package-relative
path, contract identity/version, and SHA-256 integrity binding.

The manifest does not duplicate complete narrow-artifact payloads, embed model
bytes, or retain an absolute external project root. Logical producer identity,
an immutable revision, and a content hash may preserve corroborative provenance
without retaining an operational path. The manifest is an Atlas authoring
index, not an external-analysis handoff.

### Capability profiles and artifact applicability

A registered, versioned capability profile is the normal architecture-level
selector of artifact applicability. It may govern semantic requirements,
applicable contract families, artifact-role applicability, prediction/runtime
applicability, and publication capability. It must not contain dataset-specific
feature semantics, concrete training metrics, model hashes or bytes,
release-instance content, or external filesystem paths.

Role applicability has three base states:

- **required:** the role must be present at its governed cardinality and pass
  contract, cross-reference, and integrity validation;
- **optional:** the role may be absent, but when present it must pass the same
  complete validation; and
- **forbidden:** the role must be absent, and its presence is a validation
  error.

Future contracts may formalize richer cardinality or group rules. They must not
infer requiredness only from filesystem presence, select it by `dataset_slug`
or a hardcoded dataset identity, derive it from historical milestone IDs, or
use empty/dummy placeholder artifacts for non-applicable roles.

Current binary predictive classification is the only currently evidenced
operational capability. Regression, forecasting, clustering, and no-model
studies are architecture-extension probes only; they are not current Atlas
functionality until separately contracted, implemented, and evidenced.

### Generic core and capability-aware publication direction

Dataset-specific semantic authoring records what a particular dataset means.
Capability-specific generic behavior applies typed contracts and policies to
that intent. Generic Atlas core must not use dataset identity as the normal
selector of business behavior or expand through branches such as
`if dataset_slug == ...`.

Candidate and publisher completeness is intended to become capability-aware in
future implementation. Universal artifacts remain universal;
training/model/prediction artifacts are capability-conditional; forbidden
artifacts are absent rather than represented by placeholders; every present
artifact remains schema-, cross-reference-, and integrity-validated; and
public/internal evidence boundaries remain explicit. Existing candidate and
publisher behavior is not claimed to implement this direction yet.

### Analysis, runtime, and model-delivery separation

Analysis capability, prediction capability, deployment runtime profile, and
model delivery are related but distinct concerns. A study need not imply a
prediction runtime, and a prediction capability does not by itself select how
or where its model is delivered. Governed runtime isolation remains a
legitimate compatibility mechanism, but no runtime implementation may depend
on an external analysis path.

Executable model delivery is owned by the immutable Atlas release lifecycle.
The governed active release identifies its predictive bundle and
release-relative model artifact, and runtime loading must resolve and verify
those artifacts beneath the releases root. The legacy `external-models/`
lifecycle, which duplicated model delivery outside a release, has been retired
and is no longer an operational or compatibility mechanism.

`external-inference/` is distinct from that retired storage lifecycle. It
remains the current internal inference service and runtime/dependency boundary
for governed bundles that select isolated-service dispatch. The API delegates
to it using release and bundle identity, and the service resolves the model
from the governed release rather than from a parallel model tree. This
isolation remains necessary when a bundle requires a runtime or dependency
profile that cannot safely execute in the main API process; it is not a model
store, a parallel release lifecycle, or a component made obsolete by retiring
`external-models/`.

### Backward compatibility and accepted authoring decisions

Historical v1 release artifacts remain valid under their v1 contracts. Future
structurally incompatible capability-aware contracts must use explicit
contract evolution and versioning rather than weakening or reinterpreting v1.
The current active Telco release remains unchanged until a separately governed
replacement migration and cutover succeeds. Architecture documentation alone
does not activate, migrate, publish, or modify a release or registry.

The accepted current-cycle decisions are the authoring-time-only external
analysis boundary, Lumen-assisted semantic interpretation, the dataset
integration authoring notebook boundary, the narrow Atlas-native artifact
suite, immutable integrity-bound principal manifest, versioned capability
profiles, and required/optional/forbidden applicability semantics. Their
schemas and downstream candidate, publisher, runtime, model-delivery, and
release changes remain work for subsequent implementation specs.

### Public Web Experience

Layer responsible for navigation and presentation of published experiences.

It must present the public Home, Dataset Detail, context, visualizations, metrics, predictive form, inference result, and public error states. The public web experience must consume data and contracts exposed by the public API, without concentrating business rules.

### Public Runtime API

Layer responsible for providing public endpoints for querying datasets, public presentation state, public contracts, metrics, visualizations, and inference.

The public API must resolve the requested dataset, identify the active release, respect visibility state, load the required published artifacts, validate inputs, execute inference, and hide internal details.

### Published Dataset Registry

Source of resolution between datasets and active releases.

The registry must be explicit, file-based for the current stage, and validatable. It declares which datasets exist as publishable or published entries, which release is active for each dataset, and which public metadata or snapshot can be consumed.

### Published Releases

Immutable packages that materialize a dataset publication.

A release must contain or reference the artifacts required for runtime inference and public explanation, including contracts, predictive bundle, metrics, model card, dataset context, public-safe metadata, visualization artifacts when available, and manifest.

### Public Dataset Profile

Presentation-oriented configuration associated with a dataset.

A public profile stores curated fields such as title, subtitle, description, source information, home-card content, theme/icon selection, public documentation text, preferred score highlight, form presentation ordering, and other public-facing metadata. It must not replace the runtime contract, model, metrics, or release manifest as technical sources of truth.

### Dataset Profile Draft

Editable administrative state used before publication.

A draft represents unpublished curation changes. It may be previewed privately, saved, updated, or discarded. A draft must not automatically change the public experience and must not be confused with a published snapshot.

### Published Public Snapshot

Versioned public presentation state produced from a validated draft/public profile publication operation.

A snapshot is what the public surface consumes together with the active release. Publishing changes promotes the current draft/profile state into a deterministic public snapshot. Public visibility applies to the published snapshot, not to arbitrary draft edits.

### Contract Layer

Area responsible for defining and validating contracts used by the runtime and by the interface.

The architecture differentiates runtime contract and public contract. The runtime contract guides validation and inference. The public contract provides a safe projection for rendering and consumption by the web experience, including categorical/select options when public-safe.

### Inference Runtime

Area responsible for loading published artifacts and executing predictions.

The runtime must be deterministic with respect to the active release. It must not execute training, data preparation, notebooks, curation, or publication during public requests.

### Internal Publisher

Internal tooling responsible for generating, validating, and promoting releases and publication state.

The publisher transforms artifacts generated by the pipeline into controlled publications. It validates completeness, calculates hashes, generates manifests, promotes releases, and updates registries explicitly. Future admin operations must call or reuse this logic rather than duplicating publication rules.

### Generated Run Store

Internal area where notebook or pipeline executions produce candidate artifacts.

Runs are not public publications. They may contain technical outputs that can be inspected privately, promoted into release candidates, or removed. Run discovery must remain private.

### Artifact Build Pipeline

Area responsible for preparation, training, evaluation, and generation of candidate artifacts.

The pipeline is not part of the public surface. It produces runs and candidate artifacts that can be validated, promoted, and published by controlled internal operations.

### Private Administrative Web Experience

Private UI surface for operators.

It includes the Dashboard, Dataset Admin, Settings, and Help screens. It exists to discover runs, prepare dataset details, curate public profiles, preview drafts, publish snapshots, control visibility, and guide operation. It must remain outside the public surface and must not become the authority for contracts, models, validations, or publication rules.

### Private Admin API or Internal Operations Layer

Private backend surface or command layer used by the administrative UI.

It may expose controlled operations for run listing, run promotion, draft management, preview data, publication, visibility, settings, and help content. It must remain private and must not expose internal paths, secrets, raw logs, or unrestricted filesystem access.

### Design Documentation Layer

The `design/` directory contains the closest available deterministic UX reference for upcoming screen implementation.

Design markdown, visual specifications, responsive notes, and executable HTML/CSS/JS prototypes should guide layout, naming, interaction, and presentation. Inconsistencies between markdown and executable prototypes must be documented and resolved through implementation issues. Design documents do not override contracts, runtime semantics, publisher rules, artifact schemas, tests, or security boundaries.

### Deployment and Operations

Area responsible for packaging, configuration, container execution, HTTPS, environment variables, public/private surface separation, and controlled access to admin.

Operation must consider VPS and containerized environment from the beginning.

## Responsibilities

### Public Web Experience

Responsibilities:

- list publicly visible published datasets;
- present public dataset information;
- render public Home cards from registry/profile/snapshot state;
- render Dataset Detail from public metadata, active release, metrics, visualizations, public contract, and public profile;
- render predictive forms from the public contract;
- render categorical/select inputs from public-safe contract options;
- send inference payloads to the API;
- present public responses and errors in an understandable way;
- avoid duplicated business logic;
- not access internal artifacts directly;
- not expose draft state, run state, publisher operations, or admin controls.

### Public Runtime API

Responsibilities:

- expose a simple public healthcheck;
- list publicly visible datasets;
- expose public dataset metadata;
- expose public published snapshot/profile data;
- expose public contract projections;
- expose public metrics;
- expose public visualization metadata or artifacts when available;
- receive inference requests;
- validate payloads against the runtime contract;
- load the active release bundle;
- execute prediction;
- return structured responses;
- hide internal paths and sensitive details;
- return predictable errors.

### Registry

Responsibilities:

- declare publishable and published datasets according to the current stage;
- declare active release per dataset;
- point to publication metadata, snapshots, and artifacts;
- avoid heuristic discovery of public publications;
- allow structural validation of published state;
- avoid frontend hardcoding as the mechanism for dataset availability.

### Release

Responsibilities:

- group artifacts of a publication;
- preserve the link between run, contract, model, metrics, and experience;
- record hashes and relevant metadata;
- allow high-level operational reproducibility;
- remain immutable after publication.

### Public Dataset Profile and Snapshot

Responsibilities:

- store public-facing presentation metadata;
- represent curated content without mutating technical contract fields;
- provide data for Home cards and Dataset Detail presentation;
- support draft, preview, published snapshot, and visibility semantics;
- preserve traceability to dataset, release, and publication operation;
- avoid becoming the authority for runtime validation, model execution, or contract meaning.

### Contracts

Responsibilities:

- define accepted features;
- define types, domains, options, and validations;
- define interface hints when applicable;
- guide inference payloads;
- separate public projection from internal details;
- carry schema version when applicable;
- keep public rendering data consistent with runtime validation.

### Inference Runtime

Responsibilities:

- load artifacts from the active release;
- validate inputs;
- execute prediction;
- produce stable responses;
- handle predictable errors;
- not modify published artifacts;
- not depend on frontend-invented validation rules.

### Internal Publisher

Responsibilities:

- validate release candidates;
- calculate hashes;
- generate manifests;
- promote validated releases;
- update registry explicitly;
- preserve previous releases;
- prevent publication of incomplete packages;
- validate or produce public publication state when required;
- provide the foundation for private administration.

### Generated Run Store

Responsibilities:

- retain generated run outputs produced by notebooks or pipelines;
- expose run summaries only through private operations;
- support promotion of eligible runs into release candidates or dataset preparation state;
- support controlled removal of obsolete runs when allowed;
- avoid becoming a public dataset catalog.

### Pipeline

Responsibilities:

- prepare data;
- train model;
- evaluate model;
- generate metrics;
- generate contracts;
- export bundle;
- produce candidate artifacts for publication;
- avoid performing public runtime or admin UI responsibilities.

### Private Administrative Web Experience

Responsibilities:

- provide private Dashboard navigation;
- list generated runs through private operations;
- promote a run into dataset preparation when eligible;
- show curated dataset detail configurations;
- open Dataset Admin for curation;
- edit public-facing metadata without changing technical contract fields;
- configure Home card and theme presentation;
- configure inference form presentation without changing runtime validation;
- preview draft changes in a private Live Preview;
- save drafts;
- publish deterministic public snapshots;
- control public visibility of the published snapshot;
- provide clear drag-and-drop visual feedback;
- provide minimal Settings and Help routes;
- remain private.

### Private Admin API or Internal Operations Layer

Responsibilities:

- mediate administrative actions;
- enforce allowed operations;
- call or reuse publisher/profile logic;
- validate input payloads;
- avoid leaking sensitive filesystem details;
- avoid exposing public routes for admin behavior;
- maintain deterministic state transitions.

### Design Documentation Layer

Responsibilities:

- document intended screen content, visual structure, responsive behavior, and interactions;
- provide executable prototypes for implementation guidance;
- identify inconsistencies between markdown specifications and prototypes;
- avoid becoming an API contract or runtime source of truth;
- remain aligned with implemented behavior as milestones are completed.

## Boundaries

### Public Experience vs Private Administrative Surface

The public experience includes pages and endpoints required for consuming published datasets.

The private administrative surface includes Dashboard, Dataset Admin, Settings, Help, run discovery, draft editing, preview, publishing, and visibility controls.

The private administrative surface must not be exposed directly to the public internet.

For the first version, operator access to that surface is provided by the private runtime and network boundary, such as the local/private stack or an SSH tunnel. Admin screens must not require a visible shared-token field, and any backend defense-in-depth must remain infrastructure/runtime behavior rather than a public login or multi-user authentication model.

### Public Runtime API vs Private Admin API

The public API serves public Home, Dataset Detail, public contract, public metrics, public visualizations, and inference.

The private admin API or internal operations layer serves generated runs, drafts, previews, publication operations, and administrative settings.

Public endpoints must never expose generated runs, draft states, internal paths, publisher controls, raw logs, operational files, or internal services.

### Pipeline vs Runtime

The pipeline builds artifacts.

The runtime consumes published artifacts.

The runtime must not train models, execute notebooks, prepare datasets, curate profiles, or publish releases during public requests.

### Run vs Release Candidate vs Published Release

A run is a technical execution.

A release candidate is a package candidate for publication.

A published release is a validated and promoted artifact package.

Not every run should become a release. Promotion must be explicit.

### Draft vs Preview vs Published Snapshot vs Visibility

A draft is editable private curation state.

A preview is a private rendering of draft state combined with active release/public contract data.

A published snapshot is deterministic public presentation state produced by a publish operation.

Visibility controls whether a published snapshot is publicly listed or reachable according to public rules. Visibility does not publish unsaved or unpublished draft changes.

### Dataset vs Release

Dataset is the public identity.

Release is the materialized artifact version of that identity.

A dataset may have multiple releases over time, but the current cycle operates with one active release per published dataset.

### Contract vs Model

The contract defines valid input structure and metadata required for consistency.

The model executes inference.

The model does not redefine the schema, and the contract must not assume nonexistent artifacts.

### Contract vs Public Profile

The contract defines technical and validation semantics.

The public profile defines presentation metadata and curation state.

The public profile may change labels, descriptions, ordering, theme, documentation, and home-card content. It must not silently redefine valid input domains, feature types, model behavior, or runtime validation.

### Contract vs Interface

The public contract guides the interface.

The interface must not invent canonical validations, select options, or payload semantics that the runtime contract would reject.

### Publisher vs Private Administration

The publisher contains operational logic for validation and promotion.

Private administration must only orchestrate or trigger operations already available in publisher/profile logic. It must not duplicate publication rules.

### Design Prototype vs Implementation Contract

The design prototypes guide visual and interaction implementation.

They do not override backend contracts, schemas, release manifests, API response contracts, tests, security boundaries, or publisher validation.

When design markdown and executable HTML/CSS/JS disagree, the inconsistency must be documented and resolved explicitly before implementation relies on that behavior.

### Seeded Examples vs Product Model

Telco and Bank may remain as example datasets, fixtures, or seeded records.

They must not remain embedded in frontend logic or backend branching as the mechanism that defines what Atlas can publish.

### Application vs Infrastructure

Containers, VPS, proxy, HTTPS, volumes, environment variables, private admin access, and deployment tooling belong to infrastructure.

These elements must support the application, but they do not compose the product's public experience.

## Dataset Profile Lifecycle Definition

This section gives the draft/preview/publish/visibility vocabulary used throughout this document an explicit, non-overlapping, action-by-action definition, and states which parts are implemented today versus still pending. It extends the "Draft vs Preview vs Published Snapshot vs Visibility" boundary above; it does not introduce new states beyond the ones already named there.

### States

- **Draft profile state** — editable, private curation state for a dataset's public profile. Exists independently of publication.
- **Preview state** — a private rendering of draft state combined with public-safe active-release data. Not a separate persisted state; it is a read-time composition of the draft.
- **Published profile snapshot** — deterministic public presentation state produced by a publish operation from validated draft state. Distinct from both the draft and from release artifacts.
- **Public visibility state** — whether the latest published profile snapshot is publicly reachable. Applies to the published snapshot, never to draft state.

### Actions

**Save Draft** persists edited profile curation as private draft state and must not publish changes or become publicly reachable. Implemented: `registry/dataset_public_profile_store.py` (`create_draft`/`update_draft`/`get_draft`) persists drafts per `dataset_slug`, validated against `contracts/dataset-public-profile.schema.json` and reference rules before any write, and never writes to `releases/` or a snapshot path; `api/admin_profile_drafts.py` exposes this privately to the Dataset Admin screen.

**Preview** renders private draft state through the same presentation components the public experience uses, without changing or exposing public state. Implemented: the Dataset Admin Live Preview tab renders draft state through the shared public Home-card and Dataset Detail components in a non-submitting mode.

**Publish Changes** creates or replaces a versioned published profile snapshot from the current validated draft state; it must not mutate release artifacts, runtime contracts, model artifacts, or metrics, and it must not by itself change public visibility. Implemented: `registry/dataset_public_profile_snapshot_store.py` (`publish_snapshot`/`get_snapshot`) validates the current draft against `contracts/dataset-public-profile-snapshot.schema.json` and the dataset's active release before writing a single deterministic snapshot per `dataset_slug`, and never writes to `releases/` or `publisher/`'s own output directories or mutates `registry/datasets.json`; `api/admin_profile_publish.py` exposes this privately to the Dataset Admin Publishing tab.

**Visible Publicly** controls public exposure of the latest published profile snapshot; it must never publish unpublished draft changes, and toggling it off must hide or suppress the public presentation without altering draft or snapshot content. Implemented: `registry/dataset_public_profile_publication_store.py` (`get_visibility`/`set_visibility`) persists a publication record per `dataset_slug`, decoupled from and never mutating `registry/datasets.json`'s legacy per-dataset `visibility` field or the published snapshot itself; a dataset with no publication record yet defaults to visible, preserving prior observable behavior. `api/admin_profile_visibility.py` exposes this privately to the Dataset Admin Publishing tab.

### Boundary this definition preserves

- A published profile snapshot is presentation state only; it must never mutate release artifacts, runtime contracts, model artifacts, metrics, or become a competing source of technical truth for them.
- Draft state must remain private and must never be read by a public route. `api/public_profile_loader.py`'s `load_dataset_profile` already composes a draft (falling back to a generated profile only when no draft exists) with no publish/visibility gate at all; it is confirmed not wired to any route in `api/main.py` today, so no public/private leak currently exists, but it must not be wired into a public route until a published-snapshot/visibility gate exists, since doing so unchanged would serve unpublished draft content publicly.
- The backend logic referenced above is organized as top-level modules (`api/`, `registry/`, `publisher/`, `pipeline/`) at the repository root; there is no `backend/` directory in this repository.

## Main Flows

### Internal Artifact Generation Flow

Data study or notebook

→ pipeline execution

→ generated run under controlled internal location

→ generated contracts, metrics, model artifacts, bundle, model card, and candidate metadata

→ run becomes eligible or ineligible for promotion based on validation rules.

### Run Promotion Flow

Operator accesses private Dashboard

→ private layer lists generated runs

→ operator selects eligible run

→ private layer validates minimal promotion prerequisites

→ run is promoted into release candidate or dataset preparation state

→ publisher/profile logic creates or updates controlled publication preparation artifacts

→ operator can open Dataset Admin for curation.

### Dataset Profile Draft Flow

Operator opens Dataset Admin

→ private layer loads active release, public contract projection, metrics, visualizations, and current public profile/draft

→ operator edits public-facing metadata, Home card, theme, documentation, form presentation, or score highlight

→ draft is saved as private state

→ public experience remains unchanged until publication.

### Private Live Preview Flow

Operator opens Live Preview

→ private layer combines draft profile state with public-safe active release data

→ UI renders the same public Dataset Detail and Home-card patterns expected in the public experience

→ preview reflects draft changes without changing public state

→ preview must not expose internal-only artifacts to public users.

### Publishing Snapshot Flow

Operator chooses Publish changes

→ private layer validates draft/profile state

→ publisher or publication service creates deterministic public snapshot

→ snapshot is linked to dataset, active release, profile version, and publication metadata

→ registry or publication index is updated explicitly

→ public runtime can consume the new snapshot if visibility allows it.

### Visibility Flow

Operator toggles public visibility for a published snapshot

→ private layer changes visibility state for the published snapshot

→ public Home and Dataset Detail respect visibility rules

→ draft changes remain private regardless of visibility.

### Public Query Flow

Visitor accesses public Home or Dataset Detail

→ interface requests public metadata

→ API resolves `dataset_slug`

→ registry informs `active_release`, public snapshot, and visibility

→ API returns public dataset information

→ interface presents context, visualizations, metrics, profile content, and inference form.

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

→ interface presents result.

### Settings Flow

Operator accesses private Settings

→ private layer loads minimal settings

→ operator changes displayed user name

→ setting is saved through controlled private state

→ admin shell reflects the updated display name.

### Help Flow

Operator accesses private Help

→ private layer or static admin bundle presents usage guidance

→ help content explains Dashboard, Dataset Admin, draft/preview/publish/visibility semantics, and public/private boundaries.

## Relevant Data, Artifacts, or Documents

Artifacts relevant to the architecture:

- `docs/vision.md`: source of the project's high-level direction;
- `docs/architecture.md`: source of boundaries and architectural decisions;
- `docs/milestones.md`: future incremental planning document;
- `design/`: deterministic UX reference for public/admin screen implementation;
- `design/screens/home/`: public Home design reference;
- `design/screens/dataset-detail/`: public Dataset Detail design reference when present;
- `design/screens/dataset-admin-home/`: private Dashboard design reference;
- `design/screens/dataset-admin/`: private Dataset Admin design reference;
- published dataset registry;
- run index or generated run summaries;
- dataset public profile;
- dataset profile draft;
- published public snapshot;
- public dataset metadata;
- release manifest;
- runtime contract;
- public contract projection;
- inference bundle;
- public metrics;
- model card;
- public dataset context;
- publishable visualizations or visualization metadata;
- release validation evidence;
- publication validation evidence.

Artifacts that must not be treated as the formal public source of truth:

- exploratory notebooks;
- raw logs;
- local volumes;
- local databases;
- real `.env`;
- sensitive payloads;
- temporary execution outputs;
- generated runs that have not been promoted;
- draft states that have not been published;
- design mockups when they conflict with contracts, schemas, publisher rules, or tests;
- frontend hardcoded dataset objects.

## Runtime, Tooling, and Workflows

### Public Runtime

The public runtime is composed of the public API and the public web experience.

It must operate only on published datasets, active releases, public snapshots, visibility state, and public-safe contract/profile data. It must not depend on temporary pipeline state, recent runs, implicit local paths, draft profile state, or frontend hardcoding.

### Private Administration

Private administration is composed of admin screens and controlled private operations.

It may list generated runs, promote eligible runs, manage profile drafts, render previews, publish snapshots, control visibility, and expose minimal Settings and Help. It must remain private and must not duplicate publisher/runtime authority.

### Internal Tooling

Internal tooling includes publisher, controlled scripts, validations, and operational commands.

This tooling may generate and promote releases or publication state, but it must not be exposed as a public feature.

### Workflows

Relevant workflows in the next product stage are:

- generation of candidate artifacts;
- run discovery;
- run promotion;
- release validation;
- release promotion;
- public profile draft editing;
- private live preview;
- deterministic snapshot publication;
- public visibility control;
- public consumption of the experience;
- inference by contract and active release.

More advanced automation may be added later, as long as it does not break the boundaries between pipeline, publisher, runtime, profile, private administration, and public experience.

## Security, Versioning, and Traceability

### Security

The architecture must preserve:

- HTTPS on the public surface;
- CORS restricted to the expected public domain;
- no secrets in the frontend;
- no versioned real `.env`;
- no public endpoints for training, upload, run discovery, draft state, publication, or administration;
- hiding internal paths in error responses;
- payload limit for inference;
- logs without unnecessary sensitive data;
- internal services outside the public internet;
- private administrative access only through a private mechanism such as localhost-bound service, SSH tunnel, internal network, or equivalent control;
- no admin route forwarded from the public HTTPS server block;
- no public port mapping or public DNS entry for admin;
- validation of all private admin payloads even when admin is private.

### Versioning

The architecture must explicitly version or identify:

- registry schema;
- release manifest schema;
- contract schemas;
- public contract projection schema;
- dataset release;
- inference bundle;
- published metrics;
- public dataset profile schema;
- draft profile schema when persisted;
- published public snapshot schema;
- visualization metadata schema when present;
- model card or public release documentation.

### Traceability

Each publication must make it possible to identify:

- which dataset was published;
- which run or release candidate originated the publication when applicable;
- which release is active;
- which contracts were used;
- which public contract projection was exposed;
- which bundle was used;
- which metrics were published;
- which public profile or snapshot was published;
- which hashes validate the artifacts;
- when the release was created or promoted;
- when the public snapshot was published;
- which manifest describes the publication;
- whether the published snapshot is publicly visible.

### Immutability

Published releases must not be silently overwritten.

Published public snapshots must not be silently replaced by draft edits.

Changes to contract, model, metrics, or public dataset documentation must generate a new release, profile version, public snapshot, or controlled promotion according to the stage of the project.

### Public Error Policy

The public API must expose predictable and non-sensitive errors.

Expected categories include:

- dataset not found;
- dataset not visible;
- release not available;
- public snapshot not available;
- contract invalid or unavailable;
- invalid payload;
- inference unavailable;
- internal failure without leaking sensitive details.

### Private Admin Error Policy

The private admin layer must expose actionable but non-sensitive errors.

Expected categories include:

- run not found;
- run not eligible for promotion;
- release candidate invalid;
- draft invalid;
- profile validation failed;
- snapshot publication failed;
- visibility update failed;
- settings update failed;
- operation unavailable;
- internal failure without leaking unrestricted filesystem paths, secrets, or raw logs.

## Implementation Documentation Strategy

Selected current strategy: `milestones-only with explicit design alignment notes`.

Justification:

Atlas is moving from a contract-driven foundation into a multi-surface product implementation. The project now includes contracts, runtime, publisher, public UI, private admin UI, design references, public profiles, drafts, snapshots, and deployment/security boundaries. A full implementation map may become useful, but creating a large documentation framework before the new seams are implemented would add maintenance cost and may become inaccurate quickly.

For the next stage, milestones and issues should explicitly document:

- which design directory or prototype is being implemented;
- which design inconsistencies were accepted, corrected, or deferred;
- which API and artifact contracts support the screen;
- which public/private boundary is affected;
- which tests validate behavior;
- which hardcoded assumptions were removed or retained as fixtures;
- how draft, preview, publish, and visibility semantics are preserved.

The absence of an Implementation Map is not a failure at this stage. A dedicated map should be reviewed when one or more of the following conditions occur:

- public Home, Dataset Detail, Dashboard, Dataset Admin, Settings, and Help are all implemented;
- public profile and snapshot persistence become stable;
- frontend/backend contracts become difficult to locate;
- context cost for AI-assisted continuity becomes high;
- handoffs begin to require navigation across many files and modules;
- multiple internal flows start evolving independently;
- publisher, runtime, contracts, frontend, pipeline, deployment, and admin have their own operational documentation.

If this review indicates a need for cumulative documentation, the next candidate strategy should be `implementation-map-single`. If the project grows into highly independent areas, `implementation-map-hierarchical` may be evaluated.

When created, cumulative documentation must guide navigation and context. It must not replace real files, contracts, tests, manifests, code, execution evidence, or issue handoffs.

Cumulative documentation must not be used as a changelog, commit list, backlog, or absolute source of truth. Future issues and handoffs authorize concrete execution; architectural documentation and milestones only provide guidance.

## Expected Impact on Milestones

The architecture should guide future milestones to prioritize:

- documented reauthorization of public/admin product surfaces before broad implementation;
- design inventory and design consistency review before coding each screen;
- frontend shell, routing, layout primitives, and design-system alignment before deep screen behavior;
- public Home and Dataset Detail implementation using API/state instead of hardcoded frontend datasets;
- public contract projection improvements, especially for categorical/select fields;
- metrics and visualization presentation derived from published artifacts;
- private Dashboard backend foundation for generated run discovery;
- run promotion into dataset preparation state;
- dataset public profile and draft persistence;
- Dataset Admin curation and Live Preview behavior;
- deterministic publication snapshot and visibility semantics;
- removal of Telco/Bank as hardcoded product assumptions while preserving them as examples when useful;
- minimal Settings and Help routes;
- secure public/private deployment boundaries;
- regression-safe increments validated by tests.

Future milestones must preserve small, validatable increments, avoiding turning the architecture into a plan that is too large for the next product stage.

## Risks and Trade-offs

### Simplicity vs Extensibility

File-based registry and profile state reduce initial complexity, but may require future migration if there are many datasets, richer administration, multi-user operation, audit queries, or concurrent operators.

### Internal Publisher vs Admin Web

Keeping the publisher authoritative reduces risk and improves testability. The disadvantage is that admin implementation must be careful not to duplicate publisher rules or create parallel publication behavior.

### Immutable Release vs Manual Agility

Immutable releases increase traceability, but require discipline to generate a new publication when artifacts change.

### Draft/Snapshot Semantics vs UI Convenience

Explicit draft, preview, publish, and visibility semantics reduce ambiguity. The trade-off is more state modeling than a simple form directly editing public data.

### Public Contract vs Runtime Contract

Separating public contract and runtime contract increases security and clarity, but adds responsibility for keeping projections consistent, especially for select/categorical options.

### Public Profile vs Contract Authority

Public profile curation improves presentation, but it creates a risk of semantic drift if operators can rename, reorder, or describe fields in ways that conflict with technical meaning. Validation and documentation must keep this boundary clear.

### No Database Initially vs Advanced Querying

Avoiding a database simplifies the current cycle. Historical queries, permissions, concurrent editing, audit logs, and advanced administration may require structured persistence in the future.

### Private Admin vs Convenience

Keeping admin outside the public surface reduces risk, but requires operation through an SSH tunnel, private network, localhost-bound server block, or equivalent mechanism.

### Design Fidelity vs Contract Correctness

The design prototypes are useful for deterministic UI implementation, but copying them mechanically may cause regressions if prototype data conflicts with real contracts, metrics, or API schemas.

### Seeded Examples vs Hardcoded Product Logic

Telco and Bank are useful examples. The risk is allowing them to remain embedded as product assumptions instead of migrating toward registry/artifact/profile-driven dataset availability.

## Accepted Current-Cycle Architectural Decisions

The following decisions are accepted for the next public/admin cycle and define boundaries for later bootstrap issues. They are documentation-level architectural decisions, not implementation steps.

- Atlas remains a dataset-centric, contract-first, release-oriented platform for publishing predictive experiences.
- The next product stage implements both public dataset experiences and a private administrative curation layer.
- The public runtime resolves publications by `dataset_slug`, `active_release`, published public snapshot, and visibility state.
- The registry remains explicit, file-based for the current stage, and validatable.
- Published releases are immutable packages that connect dataset, run, contract, predictive bundle, metrics, model card, context, and manifest.
- Public dataset profiles may curate presentation metadata, but must not redefine contract, model, metrics, or inference semantics.
- Draft, preview, published snapshot, and visibility are distinct states.
- Visibility applies to the published public snapshot, not to unpublished draft edits.
- The private Dashboard may discover generated runs and initiate controlled promotion.
- The private Dataset Admin may curate public profile state, preview drafts, publish snapshots, and control visibility.
- Minimal private Settings and Help routes are in scope.
- Drag-and-drop UX must provide clear visual feedback when used for ordering or curation interactions.
- Public Home and Dataset Detail must move toward registry/artifact/profile-driven data rather than frontend hardcoded datasets.
- Telco and Bank may remain as seeded examples or fixtures, but not as permanent product assumptions in UI logic.
- Traceability between dataset, run, contract, model, metrics, profile, snapshot, release, and publication is mandatory.
- Pipeline, publisher, public runtime, private administration, public web experience, contracts, public profiles, and published artifacts remain separate responsibilities.
- The internal publisher validates completeness, calculates hashes, generates manifests, and promotes releases explicitly.
- Private administration must orchestrate existing publisher/profile operations instead of duplicating publication logic.
- The public surface exposes only public experiences, public contracts, public metadata, metrics, visualizations when available, and inference endpoints required for application consumption.
- Internal tooling, publisher operations, generated runs, draft states, pipeline work, sensitive logs, operational tools, databases, volumes, infrastructure, and private administration remain outside the public surface.
- The current cycle does not require a database, multi-user operation, marketplace, public upload, public retraining, or complex administration.
- Public deployment must preserve secure boundaries around secrets, internal services, logs, runtime artifacts, and admin routes.
- The implementation documentation strategy is `milestones-only with explicit design alignment notes`; a dedicated Implementation Map remains deferred until concrete implementation complexity justifies it.

Pending product and technical choices remain outside this accepted list.

## Gaps and Pending Decisions

Pending decisions:

- define the operational backup strategy for releases, public profiles, drafts, and published snapshots;
- define the minimum log policy for public and private operations;
- define the exact persistence model for dataset public profiles, drafts, snapshots, and visibility state;
- define how generated notebook runs should be indexed, validated, promoted, and removed;
- define whether run promotion creates a release candidate, a dataset preparation record, or both;
- define which visualization artifacts are required for a complete public dataset experience and which remain optional;
- define how public-safe categorical/select options are projected from runtime contracts;
- define how metrics nested in artifacts should be normalized for public display;
- define whether the publisher will be exposed only as a CLI, as an internal service, or through shared backend functions;
- define the specific localhost/private port for the admin surface when deployed;
- define the minimum privacy/security mechanism required before the administrative surface can be considered private;
- define whether publication snapshots need human-readable version names in addition to technical identifiers;
- define whether Settings should remain local/simple or evolve into a broader admin preference model later.

Known gaps:

- the expected scale of datasets is not yet defined;
- the expected inference volume is not yet defined;
- the future need for a database is not yet confirmed;
- the observability strategy still needs to be made proportional;
- the semantic versioning policy for schemas still needs to be detailed;
- the exact relationship between design markdown, visual specs, responsive specs, and executable prototypes must be checked per screen before implementation;
- the design currently covers primary admin/public screens, while Settings and Help still need minimal design/implementation definition.

## Architectural Validation Criteria

The architecture will be considered adequate if it:

- is aligned with the Atlas vision;
- allows a public experience per published dataset;
- supports a private Dashboard for run discovery and dataset preparation;
- supports a private Dataset Admin for profile curation, preview, publishing, and visibility;
- resolves runtime by `dataset_slug`, `active_release`, public snapshot, and visibility state;
- avoids a global contract or bundle as the source of truth;
- keeps the initial registry explicit, file-based, and validatable;
- separates pipeline, generated run store, publisher, profile state, runtime, private administration, and public web experience;
- preserves contracts as the source of truth for validation, inference, and guided rendering;
- exposes public-safe contract projections for frontend rendering;
- prevents the interface from concentrating business logic;
- treats published releases as immutable;
- treats draft, preview, published snapshot, and visibility as distinct states;
- keeps administration outside the public surface;
- does not require a database, multi-user operation, or complex admin in the current cycle;
- preserves traceability between dataset, run, contract, bundle, metrics, profile, snapshot, release, and publication;
- considers public deployment with containers, HTTPS, and environment-based configuration;
- does not expose secrets, raw logs, internal paths, generated runs, draft states, publisher controls, or internal services through public routes;
- uses `design/` as a deterministic UX reference without making it override contracts, tests, schemas, or security boundaries;
- removes hardcoded dataset assumptions from product logic while allowing seeded examples;
- guides future milestones without becoming a roadmap;
- declares a proportional documentation strategy;
- records risks and pending decisions without resolving them by inference.

## Notes for Future Milestones

Future milestones must use this architecture as a scope boundary, not as an implementation list.

Incremental planning should begin with the minimum foundations for the next stage:

- architecture/vision alignment for the design-backed product surface;
- design inventory and consistency review;
- frontend shell and route structure;
- public Home implementation;
- public Dataset Detail implementation;
- public contract projection repair for categorical/select fields;
- metrics and visualization normalization;
- private Dashboard backend foundation;
- generated run discovery;
- run promotion into controlled preparation state;
- dataset public profile and draft model;
- Dataset Admin curation UI;
- private Live Preview aligned with public Dataset Detail behavior;
- deterministic snapshot publication;
- public visibility control;
- hardcoded dataset exit;
- minimal Settings and Help;
- security review for public/private separation.

Features such as public upload, public dataset creation by third parties, multi-user operation, marketplace, multiple organizations, complex permissions, mandatory database, and public retraining must remain outside the current stage unless there is an explicit future architectural decision.

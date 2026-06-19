# Milestones

## Purpose

This document records the milestone plan for Atlas DataFlow.

It organizes the evolution of the project into completable, derivable capabilities aligned with the vision and architecture. The document should guide future stages of issue draft generation, formal issue creation, and implementation handoffs.

This document does not execute implementation, does not publish issues, does not define the current milestone, does not replace operational State, and does not create an implementation map.

## Reading Rules

- Milestones are planning units, not formal issues.
- Milestones are not microtasks or a detailed backlog.
- Expected issues or derivation criteria indicate future possibilities, not publications.
- The current milestone, when it exists, must be controlled by a separate operational State.
- Implementation depends on a later stage authorized by an issue or handoff.
- The textual order of milestones indicates logical dependency, but does not replace an operational cursor.
- Cumulative implementation documentation should only be created or updated when a future issue or handoff authorizes it.
- The out-of-scope items declared in each milestone must be respected to prevent uncontrolled growth.
- Registered gaps must not be resolved by inference during issue derivation.

## Per-Issue Derivation Criteria

This section defines what each individual future bootstrap issue must satisfy before it is formalized or implemented. These criteria are distinct from the milestone-level derivability criteria declared in each milestone section, which describe when a milestone as a whole is ready to start generating issues.

Each derived issue must individually satisfy all of the following:

### Traceability

- The issue must be traceable to at least one accepted decision or boundary established in `docs/vision.md`, `docs/architecture.md`, or `docs/milestones.md`.
- The issue must not rely on pending decisions listed in those documents without an explicit prior resolution of the pending item.
- The issue must not infer architecture, stack, dataset, or publication behavior from absent or undecided information.

### Scope and Type Separation

Issues must belong to one of the following types, defined by what the issue is authorized to change — not by expected complexity:

- **Documentation issue**: authorized to change only foundational documents (`docs/vision.md`, `docs/architecture.md`, `docs/milestones.md`). Must not start implementation.
- **Decision issue**: authorized to resolve a specific pending decision and record it in an appropriate foundational document. Must not execute implementation or derive secondary decisions not explicitly scoped.
- **Bootstrap issue**: authorized to create, modify, or delete implementation artifacts (code, configuration, schemas, tests). Must reference accepted decisions and must not introduce scope outside the current milestone's authorized boundaries.

An issue must not conflate types. A documentation issue must not introduce bootstrap scope; a bootstrap issue must not resolve undocumented decisions by inference.

### Out-of-Scope Validation

Before formalization, each issue must confirm the following are absent from its scope:

- Registry, publisher, inference, deployment, or administration capabilities not authorized for the current milestone.
- Architecture changes not supported by accepted decisions in `docs/architecture.md`.
- GitHub publication, issue backlog creation, or Implementation Map creation not explicitly authorized.
- Commands, code, patches, branches, commits, or pull requests during documentation or decision formalization stages.

### Derivation Boundary

- An issue must not resolve a pending decision that is outside its declared type scope.
- If formalizing or implementing an issue would require resolving an undocumented decision, the issue must declare a blocker rather than inferring a resolution.
- An issue must not become an implementation plan. Its deliverable must be traceable to one of: a documentary change, a recorded decision, or an authorized implementation artifact.

## Relationship with docs/vision.md

`docs/vision.md` defines the high-level direction of Atlas DataFlow: a platform for transforming data studies into web-based predictive experiences that can be published per dataset.

The milestones preserve this direction by prioritizing:

- publication per dataset;
- understandable public experience;
- contracts as the source of truth;
- inference based on published artifacts;
- traceability between dataset, contract, model, metrics, and publication;
- separation between public surface and internal processes;
- simplicity proportional to the first public cycle.

Items outside the initial vision, such as public upload, marketplace, multi-user operation, complex administration, and public retraining, must not appear as mandatory scope in the first milestones.

## Relationship with docs/architecture.md

`docs/architecture.md` is the main source of boundaries, responsibilities, and constraints for this plan.

The milestones reflect the following architectural decisions:

- `dataset-centric`, `contract-first`, and `release-oriented` architecture;
- public runtime resolving publications by `dataset_slug` and `active_release`;
- initial file-based registry;
- one active release per dataset in the first public cycle;
- one public experience per dataset in the first public cycle;
- no predict views at the beginning;
- published releases treated as immutable;
- internal publisher before any web administration;
- no public administration in the first public cycle;
- eventual internal administration accessible only through a private surface;
- separation between pipeline, publisher, runtime, contracts, artifacts, and web experience;
- implementation documentation strategy defined as `milestones-only`.

## Relationship with Operational State

This document is not operational State.

It does not define the current milestone, real progress, execution status, implementation cursor, current issue, or dynamic priority.

If the project adopts milestone operational control, that control must exist in its own artifact, such as `docs/project-status/milestone-state.json`, or a future equivalent. The order of the sections in this document must not be used in isolation as the operational source of truth.

## Relationship with Implementation Documentation

Applicable strategy: `milestones-only`.

The architecture defines that, at this stage, `docs/milestones.md` is sufficient to guide continuity without creating the premature cost of dedicated cumulative documentation.

Consequences for this document:

- no Implementation Map should be created at this stage;
- milestones should evaluate implementation documentation without making it mandatory by default;
- future issues and handoffs authorize concrete execution;
- cumulative documentation, if adopted in the future, should guide navigation and not replace real files;
- cumulative documentation must not be used as a changelog, backlog, operational State, or absolute source of truth;
- the strategy should be reviewed when multiple areas begin to evolve in parallel and context cost increases.

Conditions that may motivate a future review of the strategy:

- runtime, publisher, contracts, web, pipeline, and deployment evolving independently;
- handoffs requiring navigation across many modules;
- recurring difficulty locating responsibilities;
- need for onboarding or AI-assisted continuity with lower context cost;
- dedicated operational documentation emerging in multiple areas.

## Milestones Overview

| Milestone | Focus | Expected result | Derivable? |
|---|---|---|---|
| M1 | Documented foundation and initial technical scope | Document base and minimum decisions ready to guide bootstrap | Yes |
| M2 | Minimal public technical bootstrap | Initial structure with API, web, configuration, and basic validations | Yes |
| M3 | File-based registry and publication model | Datasets and active releases resolved without heuristics | Yes |
| M4 | Contracts and contract-first validation | Runtime/public contracts guiding API and interface | Yes |
| M5 | Internal publisher and release candidate | Publications generated, validated, and promoted by internal tooling | Yes |
| M6 | Inference runtime by dataset and active release | Public prediction based on `dataset_slug` and `active_release` | Yes |
| M7 | First public dataset experience | Published dataset with context, metrics, visualizations, and prediction | Yes |
| M8 | Public deployment and minimum security | Atlas accessible through a public URL with a secure surface | Yes |
| M9 | First public cycle closure | First demonstrable cycle reviewed, with production release gaps recorded | Yes |
| M10 | Initial private internal administration | Internal admin explicitly deferred because publisher operation is not mature enough | Closed with documented deferral |
| M11 | Publisher operational release flow | Publisher becomes an executable, repeatable release operation | Yes |
| M12 | First real dataset release | First non-fixture dataset release is materialized and traceable | With reservations |
| M13 | Contract artifact build pipeline foundation | Study/dataset inputs can produce governed contract artifacts | With reservations |
| M14 | Run evidence and traceability layer | Runs, candidates, releases, and evidence become traceable | With reservations |
| M15 | Controlled expansion to a second dataset | Architecture is validated beyond the first dataset | With reservations |
| M16 | Published dataset context foundation | Published datasets gain governed semantic context | With reservations |
| M17 | Published shell and dataset home experience | Published dataset experience becomes navigable and dataset-centered | With reservations |
| M18 | Predict view foundation | Multiple governed prediction views can be associated with a dataset | With reservations |
| M19 | Predict experience customization | Prediction experiences become configurable without duplicating contracts | With reservations |
| M20 | Internal admin re-evaluation | Private administration is reconsidered after real operations exist | With reservations |
| M21 | Publication stabilization and operational hardening | Publication layer is hardened for continued operation | With reservations |

## M1 — Documented Foundation and Initial Technical Scope

### Objective

Establish the documentation base and the minimum technical decisions required to start Atlas without scope ambiguity.

### Problem or Gap

The project needs to start with explicit boundaries to avoid disorganized growth, confusion between runtime, pipeline, publication, and administration, or early anticipation of capabilities outside the first public cycle.

### Context

The vision defines Atlas as a platform for predictive experiences per dataset. The architecture defines a simple approach, with a file-based registry, immutable releases, public runtime, and internal publisher.

Before implementation, it is necessary to ensure that the foundational documents are aligned and that critical pending decisions are classified.

### Core Scope

- Review of `docs/vision.md`.
- Review of `docs/architecture.md`.
- Consolidation of `docs/milestones.md`.
- Record of accepted decisions for the first public cycle.
- Record of gaps that do not block bootstrap.
- Definition of scope limits for future issues.

### Out of Scope

- Implementing code.
- Creating formal issues.
- Creating operational State.
- Creating an Implementation Map.
- Choosing the final technical stack by inference.
- Defining the initial dataset without an explicit decision.
- Planning advanced administration.

### Expected Deliverables

- Versionable foundational documents.
- Clear list of accepted architectural decisions.
- Clear list of pending decisions.
- Derivation criteria for future bootstrap issues.
- Confirmation that the first public cycle remains small and safe.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: confirm that foundational documents are sufficient to guide the first issues.
- Candidate documents: not applicable at this stage.
- Criterion to create: do not create cumulative documentation before concrete implementation exists.
- Criterion to update: update only foundational documents if there is a change in vision, architecture, or planning.
- Criterion not to update: do not create a dedicated map to record decisions that are still conceptual.

### Dependencies

- `docs/vision.md` approved.
- `docs/architecture.md` approved.
- Architectural confirmations for the first public cycle.

### Components or Areas Affected

- Foundational documentation.
- Milestone planning.
- Project boundaries.
- Implementation documentation strategy.

### Expected Issues or Derivation Criteria

- Criterion: foundational document needs scope adjustment.
  - Possible issue type: documentation.
  - Note: the issue should change only documents and should not start implementation.
- Criterion: pending decision blocks technical bootstrap.
  - Possible issue type: technical decision.
  - Note: the issue should record the decision before generating code.
- Criterion: inconsistency between vision, architecture, and milestones.
  - Possible issue type: documentation alignment.
  - Note: the correction should preserve the accepted architectural boundaries.

### Definition of Done

- `docs/vision.md`, `docs/architecture.md`, and `docs/milestones.md` are coherent.
- The first public cycle is delimited.
- Initial out of scope is explicit.
- The `milestones-only` strategy is reflected.
- Pending decisions are recorded without undue blocking.
- The document allows issues to be derived without inventing architecture.

### Minimum Evidence

- Foundational documents present and reviewed.
- Human review completed.
- List of pending decisions recorded.
- Confirmation that no implementation was executed in this milestone.

### Risks and Gaps

- Risk of turning documentation into a detailed execution plan.
- Risk of trying to resolve all decisions before bootstrap.
- Gap: final technical stack may remain pending.
- Gap: first dataset may remain pending, as long as it does not block structural bootstrap.

### Classified Pending Decisions

The following pending decisions are identified from `docs/vision.md` and `docs/architecture.md`. No item was resolved by inference. All retain pending status until an explicit source document or human decision resolves them. None blocks M2 structural bootstrap.

**First dataset (which dataset will be published first)**
- Status: pending.
- Source: `docs/vision.md` (Pending Decisions); `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2. M2 scope explicitly excludes choosing the initial dataset.
- Required before: M7 at latest; potentially M6 for inference validation with a real model.

**Final technical stack (API and web)**
- Status: pending.
- Source: `docs/vision.md` (Risks and Uncertainties, Pending Decisions); `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2 as a final decision. M2 requires a working initial choice; final lock-in is not required before bootstrap begins.
- Required before: a preliminary choice must be made before M2 begins; the final definition can be deferred.

**Exact registry format**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M3.

**Release manifest schema**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5.

**Public contract format**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M4.

**Runtime contract format**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M4.

**Minimum format of published metrics**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5 at latest.

**Model card standard**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5 at latest; required before M7.

**`dataset_slug` convention**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M3.

**`release_id` convention**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5.

**Final directory structure for published artifacts**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5.

**Operational backup strategy for releases**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M8.

**Minimum log policy**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M8.

**Exact access mechanism for future internal administration**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M10.

**Publisher exposure mode (CLI only or also internal service)**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5 for the first decision; revisited at M10.

**Visualization approach (static, derived from artifacts, or served by API)**
- Status: pending.
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M7.

**Initial persistence or storage approach for published artifacts**
- Status: pending.
- Source: `docs/vision.md` (Pending Decisions).
- Bootstrap classification: nonblocking for M2. File-based storage is the accepted first-cycle direction from the architecture.
- Required before: M3 at latest.

**Versioning strategy for dataset publications**
- Status: pending.
- Source: `docs/vision.md` (Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M5.

**Initial model for public domain, routes, and URLs**
- Status: pending.
- Source: `docs/vision.md` (Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M8.

**Minimum level of operational documentation for deployment and maintenance**
- Status: pending.
- Source: `docs/vision.md` (Pending Decisions).
- Bootstrap classification: nonblocking for M2.
- Required before: M8–M9.

### Classified Nonblocking Gaps

The following known gaps are identified from `docs/architecture.md` (Gaps and Pending Decisions). None blocks M2 structural bootstrap. They remain open until a future issue or human decision resolves them.

**Expected scale of datasets not yet defined**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. Relevant from M11 onward.

**Expected inference volume not yet defined**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. Relevant from M6–M8 for sizing and load considerations.

**Future need for a database not yet confirmed**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. File-based registry is accepted for the first cycle; database is an architectural non-objective for M1–M9.

**Way public visualizations will be generated not yet defined**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. Relevant before M7.

**Observability strategy not yet made proportional**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. Relevant before M8.

**Semantic versioning policy for schemas not yet detailed**
- Source: `docs/architecture.md` (Gaps and Pending Decisions).
- Status: open.
- Bootstrap impact: does not block M2. Relevant before M3–M4 for registry and contract schemas.

### Derivability Criteria

The milestone will be ready to derive issues when:

- objective and scope are clear;
- foundational documents are aligned;
- out of scope is separated;
- blocking gaps are identified;
- future issues can be separated into documentation, decision, and bootstrap.

### Continuity Notes

This milestone should avoid implementation. The natural next step is to start the minimal technical bootstrap without anticipating registry, publisher, or inference before the public application foundations.

## M2 — Minimal Public Technical Bootstrap

### Objective

Create the minimum technical foundation for the public Atlas application, separating web experience, public API, and basic execution configuration.

### Problem or Gap

Atlas needs a minimal executable foundation before introducing registry, contracts, releases, or inference. Without this foundation, later capabilities would become coupled or difficult to validate.

### Context

The architecture provides for a public web experience and a public runtime API. The first public cycle must be simple, containerizable, and prepared for operation on a VPS.

### Core Scope

- Initial technical structure for the public API.
- Initial technical structure for the public web experience.
- Simple public healthcheck.
- Basic environment-based configuration.
- Initial separation between public surface and internal tooling.
- Minimum local execution validations.
- Conceptual preparation for containers.

### Out of Scope

- Dataset registry.
- Real inference.
- Internal publisher.
- Data pipeline.
- Internal admin.
- Database.
- Complex authentication.
- Final public deployment.
- Choosing the initial dataset as a bootstrap requirement.

### Expected Deliverables

- Initial minimal public application.
- Minimal public API with healthcheck.
- Minimal web experience able to load.
- Basic configuration without real secrets.
- Initial structure compatible with evolution toward containers.
- Minimum validations documented.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: record only relevant bootstrap decisions in existing documents when they change boundaries.
- Candidate documents: not applicable at this stage.
- Criterion to create: do not create an implementation map.
- Criterion to update: update foundational documentation only if bootstrap reveals an architectural change.
- Criterion not to update: do not document every technical adjustment as cumulative documentation.

### Dependencies

- M1 completed.
- Minimum decision about initial technical organization sufficient for bootstrap.

### Components or Areas Affected

- Public Web Experience.
- Public Runtime API.
- Deployment and Operations.
- Environment configuration.
- Minimum tests or validations.

### Expected Issues or Derivation Criteria

- Criterion: create executable base of the public API.
  - Possible issue type: public runtime bootstrap.
  - Note: should be limited to the minimum surface.
- Criterion: create executable base of the public web.
  - Possible issue type: web experience bootstrap.
  - Note: must not include business logic.
- Criterion: prepare initial containerized execution.
  - Possible issue type: operational bootstrap.
  - Note: must not include final public deployment.

### Definition of Done

- Minimal public API responds to healthcheck.
- Minimal public web loads.
- Configuration does not depend on versioned real secrets.
- Structure allows separation between public runtime and internal tooling.
- Minimum validations are executable and understandable.
- No capability outside the MVP was introduced.

### Minimum Evidence

- Versionable minimal application.
- Healthcheck validated.
- Minimal web validated.
- Example configuration without secrets.
- Record of minimum manual or automated validation.

### Risks and Gaps

- Risk of anticipating dataset domain before the public base.
- Risk of mixing internal tooling with public API.
- Gap: final stack may require organizational adjustments.
- Gap: final deployment strategy will mature in a later milestone.

### Derivability Criteria

The milestone will be ready to derive issues when:

- the API/web boundary is clear;
- minimum validation is defined;
- out of scope prevents premature inference and publisher;
- dependencies with M1 are met.

### Continuity Notes

This milestone should deliver a small executable base. Registry, contracts, and inference should enter only after the minimum public surface is stable.

## M3 — File-Based Registry and Publication Model

### Objective

Define and validate the file-based registry and the minimum publication model by dataset and active release.

### Problem or Gap

The public runtime must not depend on a global contract, global bundle, latest run, or heuristic file discovery. An explicit mechanism is required to resolve published datasets and releases.

### Context

The architecture defines that Atlas resolves publications by `dataset_slug` and `active_release`, with an initial file-based registry and one active release per dataset in the first public cycle.

### Core Scope

- Conceptual model of the file-based registry.
- Public dataset identity by `dataset_slug`.
- Declaration of `active_release`.
- Minimum structure for public dataset metadata.
- Structural validation of the registry.
- Rejection of inconsistent registry.
- Absence of heuristic publication discovery.

### Out of Scope

- Database.
- Multi-user operation.
- Rich administrative history.
- Admin interface.
- Real inference.
- Release generation by the publisher.
- Public upload of datasets.
- Multiple experiences per dataset.

### Expected Deliverables

- Initial validatable registry.
- Minimum convention for published dataset.
- Initial `dataset_slug` convention.
- Ability to list published datasets.
- Ability to resolve declared active release.
- Predictable errors for unavailable dataset or release.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: verify that the registry remains simple enough to be understood through milestones and architecture.
- Candidate documents: not applicable initially.
- Criterion to create: do not create a dedicated map while there is only one simple registry area.
- Criterion to update: update architecture if the registry stops being file-based.
- Criterion not to update: do not document every schema change as a map; schemas and validations should be the primary technical source.

### Dependencies

- M1 completed.
- M2 completed or sufficiently advanced to allow integration with the public API.
- Maintained decision of file-based registry in the first public cycle.

### Components or Areas Affected

- Published Dataset Registry.
- Public Runtime API.
- Published Releases.
- Security and Traceability.
- Environment configuration.

### Expected Issues or Derivation Criteria

- Criterion: define minimum registry schema.
  - Possible issue type: artifact contract.
  - Note: must preserve schema versioning.
- Criterion: validate dataset and active release resolution.
  - Possible issue type: registry runtime.
  - Note: must not load model or execute inference.
- Criterion: expose public dataset listing.
  - Possible issue type: public API.
  - Note: must expose only safe metadata.

### Definition of Done

- File-based registry is defined and validatable.
- Published dataset can be identified by slug.
- Active release is declared explicitly.
- API or runtime layer can resolve dataset and release without heuristics.
- Invalid states are rejected with predictable errors.
- There is no database dependency.

### Minimum Evidence

- Validatable registry example.
- Registry validation executed.
- Dataset resolution demonstrated.
- Invalid cases documented or tested.
- Review that no sensitive internal information is exposed.

### Risks and Gaps

- Risk of initial schema being too rigid.
- Risk of initial schema being too weak and difficult to validate.
- Risk of coupling registry to local paths.
- Gap: exact registry format still needs to be defined.
- Gap: future database migration strategy, if needed, remains pending.

### Derivability Criteria

The milestone will be ready to derive issues when:

- minimum registry fields are identifiable;
- validity rules are clear;
- expected errors are defined;
- boundary between registry and release is preserved;
- dependency with public runtime is clear.

### Continuity Notes

The registry must be small, explicit, and validatable. It must not try to solve administration, rich history, or automatic artifact discovery in the first cycle.

## M4 — Contracts and Contract-First Validation

### Objective

Define the contract layer required for validation, inference, and guided rendering of the public experience.

### Problem or Gap

The public experience and inference API need to share a source of truth about valid inputs, types, domains, and interface hints. Without this, the UI tends to duplicate business rules or accept payloads incompatible with the runtime.

### Context

The architecture differentiates runtime contract and public contract. The runtime contract guides validation and inference. The public contract provides a safe projection for the web experience.

### Core Scope

- Definition of the runtime contract.
- Definition of the public contract.
- Schema versioning for contracts.
- Minimum payload validation rules.
- Minimum hints for form rendering.
- Safe projection of the public contract.
- Predictable errors for invalid or unavailable contract.
- Consistency between public contract and runtime contract.

### Out of Scope

- Public contract editor.
- Advanced administrative editing of contracts.
- Multiple active contracts per dataset in the first cycle.
- Predict views.
- Real inference, except necessary validations.
- Complete automatic generation from notebook.
- Compatibility with every possible modeling type.

### Expected Deliverables

- Minimum runtime contract schema.
- Minimum public contract schema.
- Structural validation of contracts.
- Safe public projection.
- Guided rendering capability through public contract.
- Minimum contract error policy.
- Contract examples for the initial dataset or demonstration dataset.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: confirm that schemas and tests are sufficient as the primary source.
- Candidate documents: not applicable initially.
- Criterion to create: consider cumulative documentation only if contracts become an extensive area with multiple versions and projections.
- Criterion to update: update architecture if the runtime/public separation changes.
- Criterion not to update: do not use a map as a substitute for real schemas and validations.

### Dependencies

- M3 completed or in a sufficient state to associate contracts with releases.
- Decision to keep contract as the source of truth.
- Minimum definition of how the public experience will consume the public contract.

### Components or Areas Affected

- Contract Layer.
- Public Runtime API.
- Public Web Experience.
- Inference Runtime.
- Published Releases.

### Expected Issues or Derivation Criteria

- Criterion: runtime contract schema needs to be materialized.
  - Possible issue type: artifact contract.
  - Note: must include versioning.
- Criterion: public contract needs to be derived or declared.
  - Possible issue type: public projection.
  - Note: must avoid exposure of internal details.
- Criterion: UI needs to render fields from the contract.
  - Possible issue type: contract-first web experience.
  - Note: must not duplicate canonical validation.

### Definition of Done

- Runtime contract is defined and validatable.
- Public contract is defined and validatable.
- Relationship between public and runtime contract is clear.
- UI can interpret hints without assuming business logic.
- Invalid payload can be rejected in a predictable way.
- Contracts carry schema version.
- No unnecessary internal detail is exposed in the public contract.

### Minimum Evidence

- Contract examples.
- Contract validation.
- Valid payload case.
- Invalid payload case.
- Public exposure review.
- Confirmation that UI depends on public contract, not semantic hardcoding.

### Risks and Gaps

- Risk of public contract diverging from runtime contract.
- Risk of initial contract trying to cover too many types.
- Risk of UI compensating for incomplete contract.
- Gap: exact interface hint format needs to be defined.
- Gap: policy for defaults and optional values needs to be detailed.

### Derivability Criteria

The milestone will be ready to derive issues when:

- contract responsibilities are separated;
- minimum fields are known;
- expected validations are delimited;
- out of scope prevents premature editor/admin;
- dependency with registry and release is clear.

### Continuity Notes

The contract layer should remain small in the first cycle. The goal is to ensure consistent inference and form rendering, not to create a complete language for defining experiences.

## M5 — Internal Publisher and Release Candidate

### Objective

Create the internal flow for generating, validating, and promoting releases without exposing public administration.

### Problem or Gap

Atlas needs to transform candidate artifacts into traceable publications. Without an internal publisher, the registry could be modified manually in an unsafe way, or incomplete releases could be exposed.

### Context

The architecture defines that the internal publisher must exist before any web administration. It validates completeness, calculates hashes, generates the manifest, and promotes releases explicitly.

### Core Scope

- Release candidate model.
- Release completeness validation.
- Generation or validation of release manifest.
- Calculation or verification of hashes.
- Explicit promotion to published release.
- Controlled registry update.
- Preservation of previous releases.
- Minimum release states, when applicable.

### Out of Scope

- Web admin.
- Public publication endpoint.
- Public upload.
- Public execution of notebooks.
- Retraining through the interface.
- Mandatory queue or worker.
- Mandatory database.
- Multi-user publication management.

### Expected Deliverables

- Internal publisher defined as tooling.
- Validatable release candidate.
- Validatable release manifest.
- Explicit promotion rules.
- Safe registry update.
- Rejection of incomplete release.
- Minimum evidence of publication validation.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: assess whether publisher begins to justify its own operational documentation, but do not create a map yet.
- Candidate documents: minimum operational publisher documentation, if required by a future issue.
- Criterion to create: create operational documentation only if the flow is not self-explanatory through contracts, validations, and milestones.
- Criterion to update: update when the publication flow changes conceptually.
- Criterion not to update: do not record each publication as cumulative documentation.

### Dependencies

- M3 completed.
- M4 completed or with sufficient minimum contracts.
- Minimum definition of release manifest.
- Maintained decision not to expose public admin.

### Components or Areas Affected

- Internal Publisher.
- Published Dataset Registry.
- Published Releases.
- Artifact Build Pipeline.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: release candidate needs to be validated.
  - Possible issue type: internal tooling.
  - Note: must reject incomplete artifacts.
- Criterion: manifest needs to record hashes.
  - Possible issue type: traceability.
  - Note: must preserve immutability.
- Criterion: registry needs to be updated through explicit promotion.
  - Possible issue type: controlled publication.
  - Note: there must be no silent mutation.

### Definition of Done

- Internal publisher can validate release candidate.
- Release manifest is produced or validated.
- Relevant hashes are recorded.
- Registry is updated only through explicit promotion.
- Incomplete release is rejected.
- Published release is not silently overwritten.
- No public publication endpoint exists.

### Minimum Evidence

- Example release candidate.
- Manifest validated.
- Promotion validation.
- Incomplete release rejection case.
- Record that previous releases are preserved.
- Public surface review without admin.

### Risks and Gaps

- Risk of publisher accumulating pipeline logic.
- Risk of manual promotion outside the publisher.
- Risk of release states becoming too complex too early.
- Gap: exact release states need to be defined proportionally.
- Gap: final publication evidence format needs to be defined.

### Derivability Criteria

The milestone will be ready to derive issues when:

- minimum release artifacts are defined;
- validation rules are clear;
- publisher/pipeline boundary is preserved;
- publisher/admin boundary is preserved;
- rejection criteria are clear.

### Continuity Notes

This milestone should consolidate the publisher before any administrative interface. A future admin should only trigger existing and testable operations.

## M6 — Inference Runtime by Dataset and Active Release

### Objective

Enable public inference based on published dataset, active release, runtime contract, and inference bundle.

### Problem or Gap

The platform needs to execute predictions without depending on a global bundle, global contract, or temporary pipeline state. The runtime must be deterministic with respect to the dataset's active release.

### Context

The architecture defines that the public runtime resolves by `dataset_slug` and `active_release`, validates payload against the runtime contract, loads the bundle from the active release, and returns a structured response.

### Core Scope

- Dataset resolution by slug.
- Active release resolution via registry.
- Runtime contract loading.
- Payload validation.
- Release bundle loading.
- Inference execution.
- Structured response.
- Predictable public errors.
- Isolation of internal paths and details.

### Out of Scope

- Model training in runtime.
- Dataset preparation in public request.
- Notebook execution.
- Release publication during inference.
- Predict views.
- Multiple models per dataset.
- A/B testing.
- Streaming or real-time events.
- Sensitive payload logs.

### Expected Deliverables

- Public inference endpoint per dataset.
- Contract-first payload validation.
- Integration with published bundle.
- Predictable error handling.
- Separation between public contract and runtime contract.
- Guarantee that runtime does not modify published artifacts.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: verify whether runtime remains navigable without a dedicated map.
- Candidate documents: not applicable initially.
- Criterion to create: consider cumulative documentation if runtime starts supporting multiple model types, multiple routes, or multiple loading strategies.
- Criterion to update: update architecture if runtime stops being release-oriented.
- Criterion not to update: do not create a map for a single inference flow.

### Dependencies

- M3 completed.
- M4 completed.
- M5 completed or published release available through a controlled mechanism.
- Inference bundle compatible with the runtime contract.

### Components or Areas Affected

- Public Runtime API.
- Inference Runtime.
- Published Dataset Registry.
- Published Releases.
- Contract Layer.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: inference endpoint needs to resolve active release.
  - Possible issue type: public runtime.
  - Note: must not use a global bundle.
- Criterion: payload needs to be validated against contract.
  - Possible issue type: contract-first validation.
  - Note: errors must be public and safe.
- Criterion: bundle needs to be loaded from the release.
  - Possible issue type: published artifact integration.
  - Note: runtime must not mutate release.

### Definition of Done

- Inference works for a published dataset.
- Runtime resolves by `dataset_slug` and `active_release`.
- Valid payload returns structured response.
- Invalid payload fails with predictable error.
- Nonexistent dataset fails with predictable error.
- Unavailable release fails with predictable error.
- No sensitive internal path is exposed.
- No published artifact is modified during inference.

### Minimum Evidence

- Inference validated with valid payload.
- Invalid payload validation.
- Nonexistent dataset validation.
- Unavailable release validation.
- Public response review.
- Record that runtime does not execute pipeline.

### Risks and Gaps

- Risk of coupling runtime to the first dataset.
- Risk of hiding transformation rules outside the contract.
- Risk of exposing internal details in errors.
- Gap: final prediction response format needs to be defined.
- Gap: bundle cache or loading policy needs to be made proportional.

### Derivability Criteria

The milestone will be ready to derive issues when:

- minimum contract format is defined;
- minimum release format is defined;
- expected inference bundle is available;
- public errors are delimited;
- out of scope prevents training/publication in runtime.

### Continuity Notes

The runtime must be treated as a consumer of releases, not as a generator of artifacts. The first dataset should validate the mechanism, but must not become a special case.

## M7 — First Public Dataset Experience

### Objective

Publish a first dataset web experience with context, essential information, visualizations, metrics, and predictive interaction.

### Problem or Gap

Atlas only demonstrates its value when it connects technical artifacts to an understandable and interactive experience. The inference API alone is not enough to validate the product proposal.

### Context

The vision defines that each published dataset should be able to have its own environment. The architecture defines one public experience per dataset in the first cycle, without predict views.

### Core Scope

- Public dataset page.
- Context of the problem and data.
- Display of essential metrics.
- Relevant and proportional visualizations.
- Predictive form guided by the public contract.
- Integration with public inference.
- Display of prediction result.
- Understandable loading and error states.

### Out of Scope

- Multiple experiences per dataset.
- Predict views.
- Visual editor.
- Advanced customization.
- Public admin.
- Public upload.
- Retraining.
- Marketplace.
- Complex authentication.
- Highly customized visualizations without need for the first dataset.

### Expected Deliverables

- Accessible public dataset experience.
- Form rendered from public contract.
- Functional integration with prediction endpoint.
- Minimum public context content.
- Display of metrics/model card.
- Relevant visualization or visual description.
- Public error handling.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: verify whether the public experience requires design or usage documentation beyond existing documents.
- Candidate documents: minimum public dataset documentation, when applicable as a release artifact.
- Criterion to create: create dataset documentation only as part of publication, not as an implementation map.
- Criterion to update: update when the public experience changes product concepts.
- Criterion not to update: do not use cumulative documentation to record minor visual adjustments.

### Dependencies

- M2 completed.
- M3 completed.
- M4 completed.
- M6 completed.
- Initial dataset chosen or demonstration dataset accepted.

### Components or Areas Affected

- Public Web Experience.
- Public Runtime API.
- Contract Layer.
- Published Releases.
- Public dataset data.
- Metrics and model card.

### Expected Issues or Derivation Criteria

- Criterion: public page needs to display context and metrics.
  - Possible issue type: public experience.
  - Note: must remain understandable for external visitors.
- Criterion: form needs to come from the public contract.
  - Possible issue type: contract-first UI.
  - Note: do not duplicate canonical validation.
- Criterion: inference result needs to be presented.
  - Possible issue type: web/runtime integration.
  - Note: handle public errors without technical leakage.

### Definition of Done

- Dataset has accessible public page.
- Experience presents dataset context.
- Experience presents metrics or model card.
- Form is guided by public contract.
- Prediction works from the web experience.
- Errors are understandable and safe.
- The experience does not expose internal services.
- There are no predict views in the first cycle.

### Minimum Evidence

- Access to the public dataset page validated in test or staging environment.
- Prediction executed through the interface.
- Form checked against public contract.
- Context content reviewed.
- Metrics/model card displayed.
- Public surface review.

### Risks and Gaps

- Risk of the experience becoming too technical.
- Risk of visualizations turning into excessive scope.
- Risk of hardcoding the first dataset.
- Gap: first dataset still needs to be confirmed.
- Gap: final visualization format needs to be defined proportionally.

### Derivability Criteria

The milestone will be ready to derive issues when:

- initial dataset is defined or there is an accepted demonstration dataset;
- public contract is available;
- prediction endpoint is functional;
- minimum public content is identified;
- limits against predict views and advanced customization are clear.

### Continuity Notes

This milestone should prove the central thesis of Atlas. The experience should be good enough for public demonstration, but does not need to solve administration, multiple experiences, or advanced customization.

## M8 — Containerized Public Deployment and Minimum Security

### Objective

Make Atlas publicly accessible in a secure, containerized way compatible with operation on a VPS.

### Problem or Gap

A functional local experience does not validate Atlas's public proposal. The project needs to be operable in a real environment without exposing internal services or secrets.

### Context

The vision requires real web publication. The architecture defines operation on a VPS with containers, HTTPS, environment variables, restricted CORS, and a minimal public surface.

### Core Scope

- Containerized packaging of the public API.
- Containerized packaging of the public web.
- Environment-based configuration without versioned secrets.
- HTTPS on the public surface.
- Restricted CORS.
- Public healthcheck.
- Minimum inference payload limit.
- Public exposure review.
- Separation of internal services.
- Post-deploy smoke validation.

### Out of Scope

- Complex multi-environment infrastructure.
- Distributed orchestration.
- Auto-scaling.
- Advanced observability.
- Advanced secrets management.
- Mandatory database.
- Public admin.
- Public upload.
- Pipeline running in public production.

### Expected Deliverables

- Public application accessible through URL.
- Containers or equivalent packaging defined.
- Environment configuration documented without sensitive values.
- HTTPS active.
- API and web integrated.
- Internal services not exposed.
- Smoke validation of dataset and prediction.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: assess the need for minimum operational deployment documentation.
- Candidate documents: short operational deployment documentation, if authorized by a future issue.
- Criterion to create: create operational documentation only if needed to repeat deployment safely.
- Criterion to update: update when deployment parameters or public surface change.
- Criterion not to update: do not record deployment logs or sensitive details as cumulative documentation.

### Dependencies

- M2 completed.
- M6 completed.
- M7 completed or available in an integrable environment.
- Decision about domain/URL and publication environment.
- Minimum infrastructure configuration available.

### Components or Areas Affected

- Deployment and Operations.
- Public Web Experience.
- Public Runtime API.
- Security.
- Environment configuration.
- Registry and published artifacts.

### Expected Issues or Derivation Criteria

- Criterion: API needs to run in a public container.
  - Possible issue type: runtime deployment.
  - Note: do not expose internal tooling.
- Criterion: web needs to run in a public build.
  - Possible issue type: frontend deployment.
  - Note: do not use a development server in production.
- Criterion: minimum security needs to be validated.
  - Possible issue type: public surface hardening.
  - Note: review CORS, HTTPS, secrets, and endpoints.

### Definition of Done

- Atlas is accessible through a public URL.
- HTTPS is active.
- Public web consumes API correctly.
- Published dataset can be queried.
- Prediction can be executed publicly.
- Internal services are not exposed.
- Secrets are not versioned and are not present in the frontend.
- Post-deploy smoke validation was completed.

### Minimum Evidence

- Public URL validated.
- Healthcheck validated.
- Dataset query validated.
- Public prediction validated.
- CORS and public surface review.
- Confirmation of absence of public admin.
- Smoke validation record.

### Risks and Gaps

- Risk of exposing internal endpoints through incorrect configuration.
- Risk of overly permissive CORS.
- Risk of public error leaking internal path.
- Risk of volumes/artifacts being mounted incorrectly.
- Gap: exact deployment mechanism depends on the chosen infrastructure.
- Gap: backup policy for releases needs to be defined.

### Derivability Criteria

The milestone will be ready to derive issues when:

- runtime and web are functional;
- published artifacts are available;
- minimum domain/environment configuration is decided;
- minimum security criteria are clear;
- deployment does not depend on public administration.

### Continuity Notes

This milestone should prioritize safe publication, not sophisticated infrastructure. Advanced observability, scalability, and complex automation should remain for later stages.

## M9 — First Public Cycle Closure

### Objective

Consolidate the first public cycle of Atlas as a demonstrable, stable, traceable delivery aligned with the vision.

### Problem or Gap

After publishing the first experience, it is necessary to stabilize the cycle, review gaps, validate success criteria, and prepare continuity without expanding scope improperly.

### Context

The vision considers initial success achieved when a published experience allows understanding the dataset, interacting with the model, and preserving traceability. The architecture defines validation criteria to confirm that boundaries were preserved.

### Core Scope

- Review of the public experience.
- Review of release traceability.
- Review of minimum security.
- Review of public errors.
- Review of foundational documentation.
- Confirmation that the first dataset was not hardcoded as a special case.
- Record of gaps for future cycles.
- Evaluation of the `milestones-only` strategy.

### Out of Scope

- Mandatory new dataset.
- Mandatory internal admin.
- Broad refactoring.
- Marketplace.
- Multi-user operation.
- Public upload.
- Predict views.
- Complete product replanning.
- Mandatory Implementation Map.

### Expected Deliverables

- First public cycle reviewed.
- Success criteria evaluated.
- Architectural boundaries confirmed.
- Future gaps recorded.
- Decision to maintain or review `milestones-only` evaluated.
- Base ready for controlled expansion.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: review whether the strategy remains sufficient after the first public cycle.
- Candidate documents: possible short operational documentation, if deployment and publication require controlled repetition.
- Criterion to create: consider `implementation-map-single` only if there is real difficulty navigating implemented areas.
- Criterion to update: update milestones or architecture if there is a boundary change.
- Criterion not to update: do not create a map only because the MVP is closed.

### Dependencies

- M7 completed.
- M8 completed.
- Vision success criteria evaluable in a public environment.

### Components or Areas Affected

- Public Web Experience.
- Public Runtime API.
- Registry.
- Published Releases.
- Security.
- Foundational documentation.
- Deployment and Operations.

### Expected Issues or Derivation Criteria

- Criterion: success criteria need to be evaluated.
  - Possible issue type: cycle validation.
  - Note: must not introduce new capability.
- Criterion: minimum security gap was identified.
  - Possible issue type: hardening correction.
  - Note: should have priority over expansion.
- Criterion: documentation became misaligned with real implementation.
  - Possible issue type: documentation update.
  - Note: adjust documents without turning them into a changelog.

### Definition of Done

- First public experience meets the vision's success criteria.
- Dataset, contract, bundle, metrics, and release are traceable.
- Public surface was reviewed.
- There is no public admin.
- There is no dependency on global contract/bundle.
- Foundational documentation is coherent with the achieved state.
- Next gaps are recorded without becoming automatic scope.

### Minimum Evidence

- Public URL review.
- Public prediction validated.
- Manifest and registry reviewed.
- Minimum security reviewed.
- Foundational documents reviewed.
- List of future gaps recorded.

### Risks and Gaps

- Risk of turning closure into expansion.
- Risk of accepting hardcoding of the first dataset.
- Risk of ignoring security gaps due to focus on demonstration.
- Gap: future documentation strategy may need to be reevaluated after real use.
- Gap: the choice of the next capability depends on the result of the first cycle.

### Derivability Criteria

The milestone will be ready to derive issues when:

- success criteria are clear;
- minimum evidence is known;
- limits against expansion are explicit;
- implementation documentation has a review criterion;
- residual risks are recorded.

### Continuity Notes

This milestone should close the first public cycle before starting a second dataset, internal administration, or advanced capabilities.

## M10 — Initial Private Internal Administration

### Objective

Evaluate whether Atlas should introduce a private internal administrative surface after the first public cycle, and record the decision without forcing premature implementation.

### Outcome

Status: `closed_with_documented_deferral`.

M10 evaluated the need for a private internal administration layer and recorded the decision to defer it. The remaining issues in this milestone were conditional on the decision to create the admin surface. Because the recorded decision was `defer`, those dependent issues are considered non-executable for this milestone.

This milestone is not treated as a normal implementation failure. It is treated as a valid decision milestone whose implementation branch was intentionally not taken.

### Problem or Gap

The project considered whether publication operations had become mature and repetitive enough to justify a private control plane. During the milestone, the observed state showed that the publisher is not yet a complete executable release operation. Without a mature publisher, an admin surface would either duplicate business rules, operate against incomplete publication mechanics, or create a false sense of operational readiness.

### Context

The architecture requires internal publisher capabilities before private web administration. The evaluation found that the next bottleneck is not a missing admin screen, but the absence of a fully operational publisher flow that can validate release candidates, generate manifests, promote releases, update the registry, and record evidence.

The conditional downstream issues in this milestone depended on an explicit `decision=create`. Since the decision was `defer`, the correct continuation is to pause the admin branch and move the roadmap toward publisher operationalization.

### Core Scope

- Evaluate the real need for internal admin.
- Decide whether to create or defer the admin surface.
- Preserve the public/private boundary.
- Record why private administration is premature.
- Prevent conditional admin issues from being implemented when the creation condition is not satisfied.
- Redirect the roadmap toward publisher operational maturity.

### Out of Scope

- Creating a private admin UI after a `defer` decision.
- Creating public admin.
- Duplicating publisher logic in a web surface.
- Introducing broad CRUD.
- Creating release operations that bypass the publisher.
- Treating deferred conditional issues as failed or incomplete implementation work.
- Advancing to second-dataset expansion before publisher operation is mature.

### Expected Deliverables

- Recorded decision to defer internal admin.
- Documentation that explains why the admin branch was not executed.
- Explicit acknowledgement that conditional issues depending on `decision=create` are non-executable.
- Continuity direction toward publisher operational release flow.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: document the deferral in this milestone rather than creating a separate implementation map.
- Candidate documents: this document only, unless a future issue authorizes a dedicated operational decision record.
- Criterion to create: do not create private admin documentation because admin was not created.
- Criterion to update: update this milestone if the recorded decision or dependency interpretation changes.
- Criterion not to update: do not document deferred issues as if they were implemented.

### Dependencies

- M9 reviewed.
- Initial publisher and release candidate concepts exist.
- Evidence of operational gaps in publication is available.
- Human decision accepts deferral.

### Components or Areas Affected

- Future Internal Administration.
- Internal Publisher.
- Published Releases.
- Registry.
- Roadmap continuity.
- Security and operational boundaries.

### Expected Issues or Derivation Criteria

- Criterion: admin need evaluation must be recorded.
  - Possible issue type: decision.
  - Note: if the decision is `defer`, dependent admin implementation issues must not execute.
- Criterion: deferred downstream issues need interpretation.
  - Possible issue type: documentation.
  - Note: document that they were conditional and non-executable, not failed implementation.
- Criterion: next roadmap segment needs realignment.
  - Possible issue type: planning documentation.
  - Note: prioritize publisher operationalization before admin or second dataset expansion.

### Definition of Done

- The admin decision is explicit.
- The decision is recorded as `defer`.
- Conditional downstream issues are understood as non-executable.
- No private admin UI was created.
- No public admin route was introduced.
- The next roadmap segment is redirected toward publisher operational maturity.

### Minimum Evidence

- Decision evidence for M10-01.
- Confirmation that dependent M10 issues required `decision=create`.
- Confirmation that the milestone is blocked by deferred conditional issues rather than implementation failure.
- Confirmation that no admin surface was created.
- Confirmation that the target repository was not modified by artificial markers or forced advancement.

### Risks and Gaps

- Risk of interpreting deferral as failure instead of a valid planning decision.
- Risk of forcing admin implementation without mature publisher operations.
- Risk of advancing to second dataset while the publication operation remains incomplete.
- Gap: publisher needs an executable release flow.
- Gap: first real release still needs to be materialized and evidenced.

### Derivability Criteria

This milestone is already resolved as a decision milestone. Future issues should only be derived from M10 if they document the deferral, preserve the decision, or re-evaluate admin after later milestones create real operational need.

### Continuity Notes

M10 closes the initial administration branch as deferred. The next milestone should not be the previous second-dataset expansion. The project should first implement the publisher as a repeatable release operation.

## M11 — Publisher Operational Release Flow

### Objective

Turn the publisher from a set of schemas and publication concepts into an executable, repeatable release operation.

### Problem or Gap

Atlas currently has a contract-first and release-oriented direction, but the publication operation is not yet mature enough to serve as the foundation for admin, multi-dataset expansion, or repeated public releases.

A release must not depend on manual copying, inference, or loosely connected files. The system needs an internal operation that can validate a release candidate, generate a manifest, promote immutable artifacts, update the registry, and record evidence.

### Context

The M10 deferral showed that private administration is premature until the publisher is operational. The next step is to make publication executable and auditable through internal tooling, without exposing public administration and without creating a complex UI.

### Core Scope

- Define the operational release candidate input.
- Validate release candidate structure and required artifacts.
- Validate release candidate contracts against known schemas.
- Calculate hashes for published artifacts.
- Generate or validate `manifest.json`.
- Promote a release candidate into `releases/{release_id}/`.
- Update `registry/datasets.json` through a controlled operation.
- Reject incomplete or inconsistent candidates.
- Prevent silent overwrite of published releases.
- Record publication evidence.

### Out of Scope

- Private admin UI.
- Public admin.
- Public dataset upload.
- Multi-user operation.
- Complete data science pipeline automation.
- Second dataset publication.
- Predict views.
- Database-backed registry.
- Marketplace behavior.

### Expected Deliverables

- Executable publisher command or internal script.
- Release candidate validation rules.
- Manifest generation or strict manifest validation.
- Hash recording for promoted artifacts.
- Controlled promotion into immutable release directory.
- Registry update with active release control.
- Evidence artifact for publication.
- Tests for valid and invalid publication states.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: schemas, tests, and publisher evidence should be the primary technical sources.
- Candidate documents: optional short publisher usage note only if future issue authorizes it.
- Criterion to create: create operational notes only if command usage cannot be safely inferred from tests and CLI help.
- Criterion to update: update architecture if publisher responsibility changes.
- Criterion not to update: do not create a broad implementation map for a single operational flow.

### Dependencies

- M10 closed with deferral.
- Registry model exists.
- Contract and release artifact concepts exist.
- File-based first-cycle publication remains accepted.

### Components or Areas Affected

- Internal Publisher.
- Published Releases.
- Registry.
- Contract Layer.
- Security and Traceability.
- Tests and validations.

### Expected Issues or Derivation Criteria

- Criterion: release candidate format needs operational definition.
  - Possible issue type: publisher contract.
  - Note: must not infer required artifacts from filenames alone.
- Criterion: promotion needs controlled implementation.
  - Possible issue type: internal publisher operation.
  - Note: must prevent overwrite and partial publication.
- Criterion: registry update needs validation.
  - Possible issue type: registry operation.
  - Note: active release changes must be explicit and auditable.

### Definition of Done

- Publisher can validate a release candidate.
- Publisher can reject incomplete or inconsistent candidates.
- Publisher can promote a valid candidate into an immutable release directory.
- Publisher can update the registry in a controlled way.
- Manifest and hashes are present and verifiable.
- Evidence is produced for publication.
- No admin UI is introduced.

### Minimum Evidence

- Valid release candidate test.
- Invalid release candidate tests.
- Promotion test.
- Registry update test.
- Evidence artifact example.
- Confirmation that published release directories are not silently overwritten.

### Risks and Gaps

- Risk of making publisher too broad and turning it into the full pipeline.
- Risk of accepting incomplete release candidates.
- Risk of registry mutation without traceability.
- Gap: the first real dataset release still needs to be produced after the operation exists.

### Derivability Criteria

The milestone will be ready to derive issues when:

- required release candidate artifacts are identifiable;
- publisher inputs and outputs are clear;
- overwrite policy is explicit;
- registry update semantics are defined;
- tests can distinguish valid and invalid candidates.

### Continuity Notes

This milestone should create the operational foundation for publication. It should not attempt to solve data preparation, predict views, admin, or multi-dataset expansion.

## M12 — First Real Dataset Release

### Objective

Use the operational publisher to produce the first real, non-fixture dataset release.

### Problem or Gap

The project needs to move from structural examples and fixtures to a real published release with traceable artifacts. Without a real release, runtime and public experience validations remain incomplete demonstrations.

### Context

After M11, Atlas should have an executable publisher. M12 should use that publisher to materialize a real release and prove that the release-oriented architecture can support an actual public dataset publication.

### Core Scope

- Select or confirm the first real dataset for publication.
- Assemble release candidate artifacts.
- Include runtime contract and public contract.
- Include model or runtime prediction artifact, if applicable.
- Include metrics, model card, and safe public metadata.
- Promote the candidate through the publisher.
- Validate the resulting release through the registry and runtime.
- Review the public experience against the real release.

### Out of Scope

- Second dataset.
- Predict views.
- Private admin.
- Public upload.
- Generalized pipeline for every dataset.
- Complex model registry.
- Marketplace or user accounts.

### Expected Deliverables

- First real release under `releases/{release_id}/` or equivalent accepted release path.
- Updated registry pointing to the active release.
- Manifest and hashes for release artifacts.
- Runtime/public contracts linked to the release.
- Public metadata and model card.
- Evidence that the release was produced through the publisher.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: determine whether publisher usage is understandable from commands, tests, and evidence.
- Candidate documents: optional first-release note if authorized by issue.
- Criterion to create: create a short note only if the release process requires manual steps not captured elsewhere.
- Criterion to update: update architecture or milestones if the real release reveals a boundary change.
- Criterion not to update: do not turn this milestone into a general data science report.

### Dependencies

- M11 completed.
- First dataset choice confirmed.
- Required artifacts available or producible.
- Public runtime can resolve active release.

### Components or Areas Affected

- Published Releases.
- Registry.
- Contract Layer.
- Inference Runtime.
- Public Web Experience.
- Publisher Evidence.

### Expected Issues or Derivation Criteria

- Criterion: first real dataset needs confirmation.
  - Possible issue type: decision.
  - Note: dataset choice must not be inferred from fixture names.
- Criterion: release candidate artifacts need assembly.
  - Possible issue type: release preparation.
  - Note: must preserve contract-first boundaries.
- Criterion: release needs publication validation.
  - Possible issue type: publisher validation.
  - Note: must use M11 publisher operation.

### Definition of Done

- A real dataset release exists.
- The release is not a structural fixture.
- Registry resolves the dataset and active release.
- Runtime can load required release artifacts.
- Public experience uses the release data safely.
- Publication evidence exists.
- Traceability between dataset, contracts, model artifacts, metrics, and release is preserved.

### Minimum Evidence

- Publisher execution evidence.
- Manifest and hash verification.
- Registry validation.
- Runtime resolution validation.
- Public experience review.
- Confirmation that fixture-only publication is no longer the sole example.

### Risks and Gaps

- Risk of treating a fixture as a production release.
- Risk of manual artifact assembly bypassing publisher validation.
- Risk of hardcoding the first real dataset.
- Gap: generalized artifact build pipeline is still not complete.

### Derivability Criteria

The milestone will be ready to derive issues when:

- publisher flow is operational;
- first dataset is selected;
- required release artifacts are known;
- runtime validation target is clear;
- public exposure review criteria are defined.

### Continuity Notes

This milestone proves a real publication. The broader artifact build pipeline should come after this proof rather than before it.

## M13 — Contract Artifact Build Pipeline Foundation

### Objective

Create the minimum governed pipeline for transforming dataset/study inputs into contract artifacts suitable for publication.

### Problem or Gap

The legacy draft showed useful capabilities around pipeline, contracts, model artifacts, and reports, but the current Atlas must recover those capabilities through contract-first boundaries instead of ad hoc data processing.

Atlas needs a build stage that prepares candidate artifacts before publisher promotion, while keeping publisher and pipeline responsibilities separate.

### Context

M11 makes publication executable. M12 proves a real release. M13 should establish how future datasets produce compatible artifacts without manually assembling every release candidate.

### Core Scope

- Define the boundary between pipeline output and publisher input.
- Define a minimum source or human-facing contract input.
- Normalize or derive runtime contract artifacts.
- Derive safe public contract artifacts.
- Produce candidate artifacts for publisher validation.
- Record build evidence.
- Keep build artifacts separate from published immutable releases.

### Out of Scope

- Full notebook automation for every study type.
- Public upload.
- Online retraining.
- Private admin UI.
- Predict views.
- Multi-dataset expansion as the main goal.
- Publisher promotion logic.

### Expected Deliverables

- Minimum build pipeline entrypoint.
- Defined candidate artifact layout.
- Runtime/public contract derivation or validation.
- Build evidence artifact.
- Tests for successful and rejected builds.
- Clear separation between build and publish.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: check whether pipeline and publisher now evolve independently enough to justify future navigation documentation.
- Candidate documents: optional pipeline usage note if authorized.
- Criterion to create: consider a small operational note only if multiple commands or directories are introduced.
- Criterion to update: update architecture if pipeline responsibilities change.
- Criterion not to update: do not create a full implementation map unless parallel areas become hard to navigate.

### Dependencies

- M11 completed.
- M12 completed or sufficiently validated.
- Contract formats stable enough for derivation.
- Publisher input requirements known.

### Components or Areas Affected

- Data Pipeline.
- Contract Layer.
- Candidate Artifacts.
- Publisher Boundary.
- Evidence.
- Tests.

### Expected Issues or Derivation Criteria

- Criterion: candidate artifact layout needs definition.
  - Possible issue type: pipeline contract.
  - Note: must be compatible with publisher validation.
- Criterion: contract derivation needs implementation.
  - Possible issue type: contract pipeline.
  - Note: public projection must not expose internal details.
- Criterion: build evidence needs persistence.
  - Possible issue type: traceability.
  - Note: evidence should link inputs to candidate artifacts.

### Definition of Done

- Pipeline can produce candidate artifacts.
- Candidate artifacts can be consumed by publisher validation.
- Runtime and public contracts are validated or derived predictably.
- Build evidence is recorded.
- Publisher does not become responsible for data transformation.
- Tests cover valid and invalid build outputs.

### Minimum Evidence

- Build command or entrypoint validation.
- Candidate artifact example.
- Contract validation results.
- Build evidence example.
- Publisher compatibility validation.

### Risks and Gaps

- Risk of rebuilding the full legacy system too quickly.
- Risk of mixing pipeline and publisher responsibilities.
- Risk of accepting implicit contract generation without review.
- Gap: model training automation may remain limited after this milestone.

### Derivability Criteria

The milestone will be ready to derive issues when:

- publisher input requirements are stable;
- minimum pipeline inputs are defined;
- contract derivation rules are known;
- evidence requirements are clear;
- build/publish boundary is explicit.

### Continuity Notes

This milestone should recover useful legacy pipeline ideas while preserving the new contract-first architecture.

## M14 — Run Evidence and Traceability Layer

### Objective

Introduce a traceability layer that distinguishes runs, builds, release candidates, published releases, and active releases.

### Problem or Gap

As Atlas grows beyond a single manually assembled release, it needs a reliable way to understand how artifacts were produced and promoted. Without run-level evidence, debugging, audit, and future automation become fragile.

### Context

The legacy project included richer notions of runs and generated artifacts. The current architecture should recover that value in a simpler, release-oriented way.

### Core Scope

- Define run identity and minimum metadata.
- Link run outputs to candidate artifacts.
- Link candidates to release promotion evidence.
- Link published releases to registry activation.
- Provide a minimum run manifest or evidence record.
- Validate traceability across build and publish stages.

### Out of Scope

- Full experiment tracking platform.
- Database-backed run history.
- Multi-user collaboration.
- Public exposure of internal runs.
- Admin UI.
- Complex model comparison dashboard.

### Expected Deliverables

- Run or build evidence schema.
- Traceability records linking run, candidate, release, and registry activation.
- Validation of required traceability fields.
- Tests for missing or inconsistent traceability.
- Safe separation of internal evidence from public metadata.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: assess whether evidence formats and tests remain enough as source of truth.
- Candidate documents: optional evidence format note if authorized.
- Criterion to create: create documentation only if multiple evidence files become difficult to interpret.
- Criterion to update: update architecture if traceability changes publication semantics.
- Criterion not to update: do not expose internal run evidence as public documentation.

### Dependencies

- M13 completed or sufficiently advanced.
- Publisher evidence exists.
- Candidate artifacts can be linked to release artifacts.

### Components or Areas Affected

- Evidence Layer.
- Data Pipeline.
- Internal Publisher.
- Published Releases.
- Registry.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: run evidence schema needs definition.
  - Possible issue type: evidence contract.
  - Note: keep it small and auditable.
- Criterion: pipeline output needs linkage.
  - Possible issue type: traceability integration.
  - Note: run output must not be confused with published release.
- Criterion: registry activation needs evidence.
  - Possible issue type: publication traceability.
  - Note: active release changes must be explainable.

### Definition of Done

- Runs, candidates, releases, and active releases are distinguishable.
- Traceability records link the lifecycle stages.
- Invalid or missing traceability is rejected where required.
- Internal evidence is not exposed as public data by default.
- Tests demonstrate the lifecycle links.

### Minimum Evidence

- Run/build evidence example.
- Candidate-to-release traceability example.
- Registry activation evidence example.
- Validation of missing evidence cases.
- Public exposure review.

### Risks and Gaps

- Risk of creating a heavy experiment tracking system too early.
- Risk of exposing internal metadata publicly.
- Risk of treating a run as a release.
- Gap: long-term storage strategy remains file-based unless future evidence requires otherwise.

### Derivability Criteria

The milestone will be ready to derive issues when:

- build and publish stages exist;
- required evidence fields are known;
- internal/public metadata boundary is clear;
- traceability failure behavior is defined.

### Continuity Notes

This milestone makes future growth safer by preserving provenance without turning Atlas into a full MLOps platform.

## M15 — Controlled Expansion to a Second Dataset

### Objective

Validate that Atlas can publish more than one dataset without architectural redesign or hardcoding of the first case.

### Problem or Gap

A single real release proves the basic publication path, but it does not prove the architecture can support more than one dataset. A second dataset should validate generality while staying controlled.

### Context

This milestone replaces the previous M11 position. It is intentionally delayed until publisher operation, first release, artifact build, and traceability have stronger foundations.

### Core Scope

- Define selection criteria for a second dataset.
- Select a simple and suitable second dataset.
- Build candidate artifacts through the governed pipeline.
- Publish the second dataset through the publisher.
- Validate registry with multiple datasets.
- Validate runtime resolution by `dataset_slug` and `active_release`.
- Confirm that the first dataset is not hardcoded.

### Out of Scope

- Marketplace.
- Public upload.
- Multi-user operation.
- Excessive generalization for every possible dataset.
- Predict views as the main goal.
- Private admin implementation.
- Database migration.

### Expected Deliverables

- Second dataset release.
- Registry with multiple valid datasets.
- Active release per dataset.
- Runtime validation for both datasets.
- Public experience for each dataset.
- Evidence that pipeline and publisher were used without special-case exceptions.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: review whether multi-dataset operations now justify a small publishing guide.
- Candidate documents: optional publishing-new-dataset note, if authorized.
- Criterion to create: create only if publishing requires multiple coordinated manual steps.
- Criterion to update: update architecture if multi-dataset behavior changes registry or runtime assumptions.
- Criterion not to update: do not create marketplace or onboarding documentation.

### Dependencies

- M11 completed.
- M12 completed.
- M13 completed or sufficiently advanced.
- M14 completed or sufficiently advanced.
- Second dataset selected.

### Components or Areas Affected

- Published Dataset Registry.
- Published Releases.
- Data Pipeline.
- Contract Layer.
- Internal Publisher.
- Inference Runtime.
- Public Web Experience.

### Expected Issues or Derivation Criteria

- Criterion: second dataset needs selection.
  - Possible issue type: dataset decision.
  - Note: prioritize simplicity and demonstrative value.
- Criterion: second dataset needs artifact build.
  - Possible issue type: pipeline application.
  - Note: must not introduce dataset-specific runtime exceptions.
- Criterion: multi-dataset registry needs validation.
  - Possible issue type: registry/runtime validation.
  - Note: resolution must remain explicit and deterministic.

### Definition of Done

- Second dataset is published.
- Registry resolves both datasets.
- Each dataset has an active release.
- Runtime resolves by dataset slug without hardcoding.
- Public experience remains separated by dataset.
- Traceability is preserved for both datasets.
- No marketplace, public upload, or complex admin is introduced.

### Minimum Evidence

- Second dataset selection rationale.
- Build evidence.
- Publication evidence.
- Registry validation with multiple datasets.
- Runtime validation for both datasets.
- Public experience review.
- Hardcode review.

### Risks and Gaps

- Risk of choosing a dataset that forces premature generalization.
- Risk of adapting runtime through exceptions.
- Risk of expanding scope into marketplace behavior.
- Gap: multiple experiences per dataset still need a later predict view foundation.

### Derivability Criteria

The milestone will be ready to derive issues when:

- first real release exists;
- pipeline and publisher can be reused;
- traceability is sufficient;
- second dataset selection criteria are known;
- multi-dataset validation cases are defined.

### Continuity Notes

This milestone should validate controlled multi-dataset operation, not platform marketplace ambitions.

## M16 — Published Dataset Context Foundation

### Objective

Introduce a governed semantic context layer for published datasets, while keeping `dataset_slug` as the primary public identity.

### Problem or Gap

A public dataset experience needs more than contracts and prediction endpoints. It needs a safe, governed context that explains what the dataset represents, what the model does, and how users should understand the experience.

### Context

The legacy project contained richer published dataset context ideas. The current Atlas should recover that value in a way compatible with the release-oriented registry and active release model.

### Core Scope

- Define published dataset context fields.
- Link context to dataset and active release.
- Include title, description, domain, tags, and narrative metadata.
- Separate public context from internal run evidence.
- Validate context schema.
- Expose safe context through public runtime.

### Out of Scope

- Replacing `dataset_slug` as identity.
- Multiple predict views.
- Public editing of context.
- Private admin UI.
- Rich CMS.
- Multi-user content management.

### Expected Deliverables

- Published dataset context schema or contract.
- Context example for existing dataset releases.
- Runtime endpoint or payload including safe context.
- Validation of required and optional context fields.
- Public exposure review.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: verify whether context schemas are enough as source of truth.
- Candidate documents: not required initially.
- Criterion to create: create documentation only if context authoring becomes non-obvious.
- Criterion to update: update architecture if dataset identity changes.
- Criterion not to update: do not create CMS documentation.

### Dependencies

- M15 completed or at least one real dataset release available.
- Public runtime can resolve dataset and release.
- Public metadata exposure policy is understood.

### Components or Areas Affected

- Published Dataset Context.
- Registry.
- Public Runtime API.
- Public Web Experience.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: context schema needs definition.
  - Possible issue type: public context contract.
  - Note: must remain safe for public exposure.
- Criterion: runtime needs context delivery.
  - Possible issue type: public runtime projection.
  - Note: must not expose internal evidence.
- Criterion: UI needs context rendering.
  - Possible issue type: public web experience.
  - Note: rendering must be metadata-driven.

### Definition of Done

- Published dataset context is defined and validatable.
- Context is associated with dataset/release without replacing registry identity.
- Public runtime exposes only safe context.
- Public web can render context predictably.
- Internal evidence remains private.

### Minimum Evidence

- Context schema validation.
- Context payload example.
- Runtime response validation.
- Public UI review.
- Public exposure review.

### Risks and Gaps

- Risk of turning context into an uncontrolled CMS.
- Risk of exposing internal evidence or data preparation details.
- Risk of confusing `dataset_slug` with thematic grouping.
- Gap: predict views still need a separate foundation.

### Derivability Criteria

The milestone will be ready to derive issues when:

- at least one real release exists;
- public metadata needs are clear;
- safe exposure rules are known;
- context does not replace registry identity.

### Continuity Notes

This milestone makes the public dataset experience understandable before adding multiple prediction views.

## M17 — Published Shell and Dataset Home Experience

### Objective

Create a clearer published shell and dataset home experience around the governed dataset context and release artifacts.

### Problem or Gap

A single prediction screen is not enough to communicate a published dataset experience. Atlas needs a public shell that organizes context, metrics, visualizations, model information, and prediction in a predictable dataset-centered way.

### Context

The legacy project explored multiple screens and published experience structure. The current Atlas should reintroduce this as a public shell after publication, context, and dataset identity are stable.

### Core Scope

- Define public dataset home structure.
- Render dataset context.
- Render safe metrics and model information.
- Render safe visualizations when available.
- Link to prediction experience.
- Keep public shell separate from technical/internal shell.
- Preserve contract-driven prediction behavior.

### Out of Scope

- Private admin.
- Public editing.
- Multiple predict views as a required feature.
- User accounts.
- Marketplace navigation.
- Complex visualization builder.

### Expected Deliverables

- Public dataset home route or equivalent entrypoint.
- Published shell layout.
- Context, metrics, visualizations, and prediction navigation.
- Safe fallback behavior when optional artifacts are absent.
- Tests or reviews for public rendering.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: assess whether public routing and shell responsibilities are clear from code and tests.
- Candidate documents: optional public routes note if authorized.
- Criterion to create: create only if route structure becomes hard to infer.
- Criterion to update: update architecture if public shell changes runtime responsibilities.
- Criterion not to update: do not document visual design details as architecture.

### Dependencies

- M16 completed.
- Public context available.
- Runtime can expose safe public artifacts.
- Web experience can consume public contract and context.

### Components or Areas Affected

- Public Web Experience.
- Public Runtime API.
- Published Dataset Context.
- Published Releases.
- Visualizations and Metrics.

### Expected Issues or Derivation Criteria

- Criterion: dataset home route needs definition.
  - Possible issue type: public web routing.
  - Note: routes must remain dataset-centered.
- Criterion: public shell needs rendering.
  - Possible issue type: web experience.
  - Note: must not introduce business logic in UI.
- Criterion: optional artifacts need safe rendering behavior.
  - Possible issue type: runtime/web compatibility.
  - Note: absent optional artifacts should not break the dataset home.

### Definition of Done

- Dataset home is accessible.
- Public shell renders safe context and artifact summaries.
- Prediction remains contract-driven.
- Optional missing artifacts have predictable behavior.
- No private/admin capability is exposed.

### Minimum Evidence

- Route validation.
- Public rendering review.
- Runtime payload validation.
- Optional artifact fallback validation.
- Public exposure review.

### Risks and Gaps

- Risk of mixing public shell with future admin shell.
- Risk of duplicating runtime decisions in the frontend.
- Risk of overbuilding visual navigation before predict views.
- Gap: multiple prediction experiences remain future scope.

### Derivability Criteria

The milestone will be ready to derive issues when:

- dataset context exists;
- public route model is clear;
- safe artifact payloads are available;
- UI/runtime boundaries are preserved.

### Continuity Notes

This milestone turns published datasets into navigable experiences without yet adding multiple prediction views.

## M18 — Predict View Foundation

### Objective

Introduce the concept of governed predict views as multiple prediction experiences associated with a published dataset.

### Problem or Gap

A dataset may need more than one prediction experience, but those experiences must not duplicate or override the canonical runtime contract. Atlas needs a way to associate view-level presentation and intent with a dataset while preserving contract-first validation.

### Context

The legacy draft contained predict view concepts. The current Atlas should reintroduce them only after dataset context and published shell foundations exist.

### Core Scope

- Define predict view identity.
- Associate predict views with dataset and active release or compatible release context.
- Store view metadata.
- Resolve view runtime through dataset context and contract artifacts.
- List available views for a dataset.
- Block views that reference invalid datasets, releases, or contracts.

### Out of Scope

- View marketplace.
- Public view editor.
- Private admin UI.
- Arbitrary business logic per view.
- Contract duplication.
- Multiple model variants as a primary goal.

### Expected Deliverables

- Predict view contract or schema.
- View registry or metadata location.
- Runtime resolution for dataset/view.
- Public listing of views.
- Validation for invalid view bindings.
- Tests for canonical dataset/contract precedence.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: consider whether view binding rules require a small reference note.
- Candidate documents: optional predict view binding note if authorized.
- Criterion to create: create only if binding rules become non-trivial.
- Criterion to update: update architecture if predict views alter contract responsibilities.
- Criterion not to update: do not document view content as implementation map.

### Dependencies

- M16 completed.
- M17 completed.
- Runtime/public contract separation stable.
- Dataset/release resolution stable.

### Components or Areas Affected

- Predict Views.
- Public Runtime API.
- Public Web Experience.
- Contract Layer.
- Published Dataset Context.
- Registry.

### Expected Issues or Derivation Criteria

- Criterion: predict view schema needs definition.
  - Possible issue type: view contract.
  - Note: views must not redefine runtime validation.
- Criterion: view runtime needs resolution.
  - Possible issue type: runtime binding.
  - Note: dataset and contract precedence must be explicit.
- Criterion: public web needs view listing.
  - Possible issue type: web experience.
  - Note: view rendering must be metadata-driven.

### Definition of Done

- Predict views are defined and validatable.
- Views are associated with datasets without replacing dataset identity.
- Runtime can resolve dataset/view safely.
- Invalid bindings are rejected.
- Public web can list or open available views.
- Contracts remain the source of truth.

### Minimum Evidence

- Valid view example.
- Invalid binding tests.
- Runtime resolution tests.
- Public listing/rendering review.
- Contract precedence review.

### Risks and Gaps

- Risk of view metadata becoming a second contract system.
- Risk of coupling view identity to one release too rigidly or too loosely.
- Risk of reintroducing legacy complexity too quickly.
- Gap: customization rules need a later milestone.

### Derivability Criteria

The milestone will be ready to derive issues when:

- dataset shell exists;
- contract precedence is stable;
- view identity and binding rules are defined;
- invalid view behavior is known.

### Continuity Notes

This milestone introduces predict views as governed associations, not as arbitrary new applications.

## M19 — Predict Experience Customization

### Objective

Allow prediction experiences to be customized through governed metadata while preserving canonical runtime validation.

### Problem or Gap

After predict views exist, Atlas needs a safe way to vary presentation, field grouping, text, and user guidance without duplicating business rules in the frontend or weakening runtime contracts.

### Context

The legacy project explored richer prediction experiences. The current Atlas should recover customization gradually and only through contract-compatible metadata.

### Core Scope

- Define customization metadata allowed for predict views.
- Support field ordering and grouping when compatible with the public contract.
- Support explanatory copy and context per view.
- Support optional field visibility rules only when contract-safe.
- Validate customization against the public contract.
- Render customized prediction experiences in the public web.

### Out of Scope

- Runtime validation changes per view.
- Arbitrary frontend scripts.
- User-authored public customization.
- Admin UI for editing.
- Complex personalization.
- Multiple models per view unless already supported by release contracts.

### Expected Deliverables

- Customization schema or extension for predict views.
- Validation against public contract.
- Public rendering of customized view metadata.
- Rejection of customization that violates contract requirements.
- Tests for field ordering, copy, and invalid customization.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: assess whether customization rules need a reference note.
- Candidate documents: optional view customization note if authorized.
- Criterion to create: create only if metadata authoring becomes ambiguous.
- Criterion to update: update architecture if UI starts carrying business logic.
- Criterion not to update: do not document view styling as core architecture.

### Dependencies

- M18 completed.
- Public contract projection stable.
- Public web supports view rendering.

### Components or Areas Affected

- Predict Views.
- Public Web Experience.
- Public Contract.
- Public Runtime API.
- Published Dataset Context.

### Expected Issues or Derivation Criteria

- Criterion: customization metadata needs definition.
  - Possible issue type: view metadata contract.
  - Note: must be validated against public contract.
- Criterion: web rendering needs customization support.
  - Possible issue type: public web experience.
  - Note: must not encode business rules outside the contract.
- Criterion: invalid customization needs rejection.
  - Possible issue type: validation.
  - Note: hidden or reordered fields must not break required input semantics.

### Definition of Done

- Predict views can carry safe customization metadata.
- Customization is validated against the public contract.
- Public web renders customized experiences.
- Invalid customization is rejected.
- Runtime validation remains canonical.
- No arbitrary scripts or public editing are introduced.

### Minimum Evidence

- Valid customization example.
- Invalid customization tests.
- Public rendering review.
- Contract compatibility review.
- Confirmation that UI did not duplicate business rules.

### Risks and Gaps

- Risk of customization becoming hidden business logic.
- Risk of hiding required fields unsafely.
- Risk of growing into CMS/editor scope.
- Gap: private admin for managing these artifacts remains deferred until re-evaluation.

### Derivability Criteria

The milestone will be ready to derive issues when:

- predict views exist;
- public contract rules are stable;
- allowed customization scope is clear;
- invalid customization behavior is defined.

### Continuity Notes

This milestone makes Atlas more flexible for users while keeping contracts as the source of truth.

## M20 — Internal Admin Re-Evaluation

### Objective

Re-evaluate private internal administration after publisher, real releases, multi-dataset operation, context, shell, and predict views create real operational needs.

### Problem or Gap

M10 deferred admin because it was premature. After later milestones, private administration may become justified for inspecting candidates, releases, evidence, views, and publication status. This milestone revisits the decision based on actual operations rather than speculation.

### Context

By this stage, Atlas should have enough internal operations to evaluate whether a minimal private surface improves safety and usability. The admin must remain private and must not duplicate publisher or pipeline logic.

### Core Scope

- Re-evaluate the need for private admin.
- Identify concrete operational tasks that justify a private surface.
- Define private access mechanism.
- Allow read-only inspection of datasets, releases, candidates, evidence, and views if justified.
- Allow controlled triggering of existing operations only if safe.
- Preserve public/private boundary.

### Out of Scope

- Public admin.
- Broad CRUD.
- Multi-user administration.
- Public upload.
- Public retraining.
- Replacing publisher or pipeline logic with UI.
- Running long fragile operations inside public HTTP requests.

### Expected Deliverables

- Recorded decision to create, partially create, or defer admin again.
- If created, minimal private internal surface.
- Clear boundary between admin, publisher, and pipeline.
- Private access validation.
- Public exposure review.

### Implementation Documentation

- Applicable strategy: `milestones-only`, with possible review.
- Expected evaluation: admin may justify small operational documentation.
- Candidate documents: private access note or admin operation note, if implementation is authorized.
- Criterion to create: create only if admin exists and operational misuse is likely without guidance.
- Criterion to update: update architecture if private access model changes.
- Criterion not to update: do not create user-facing public admin documentation.

### Dependencies

- M11 completed.
- M12 completed.
- M15 completed or multi-dataset operation validated.
- M18 or M19 completed if views are part of admin needs.
- Real operational need demonstrated.

### Components or Areas Affected

- Future Internal Administration.
- Internal Publisher.
- Data Pipeline.
- Evidence Layer.
- Predict Views.
- Security and Operations.

### Expected Issues or Derivation Criteria

- Criterion: operational need is demonstrated.
  - Possible issue type: decision.
  - Note: admin must not be created merely because it was previously planned.
- Criterion: private access needs definition.
  - Possible issue type: security boundary.
  - Note: public exposure must be impossible by design and deployment.
- Criterion: safe operations need integration.
  - Possible issue type: internal integration.
  - Note: admin must call existing operations, not duplicate rules.

### Definition of Done

- Admin decision is explicit.
- If created, admin is private.
- Admin does not duplicate publisher or pipeline logic.
- Public routes do not expose admin.
- Operational tasks are concrete and justified.
- Security review is recorded.

### Minimum Evidence

- Decision evidence.
- Private access validation, if created.
- Public exposure review.
- Integration tests or manual validation for allowed operations, if created.
- Confirmation that long operations are not run through unsafe public requests.

### Risks and Gaps

- Risk of admin growing beyond operational need.
- Risk of private surface leaking publicly.
- Risk of duplicating publisher rules.
- Risk of turning admin into a general platform before product boundaries are mature.

### Derivability Criteria

The milestone will be ready to derive issues when:

- real operational tasks are known;
- publisher and pipeline operations are mature;
- private access mechanism can be validated;
- out-of-scope admin expansion is explicit.

### Continuity Notes

This milestone intentionally revisits M10 after the system has enough real operations to justify or reject admin with better evidence.

## M21 — Publication Stabilization and Operational Hardening

### Objective

Harden the publication layer and public dataset experience for continued operation after the second growth cycle.

### Problem or Gap

After publisher, real releases, pipeline, traceability, multi-dataset support, contexts, shell, and predict views, Atlas needs a stabilization milestone to reduce operational risk and prepare for sustained use.

### Context

This milestone closes the new roadmap segment. It should not introduce a major new product area. It should strengthen what already exists.

### Core Scope

- Review release immutability and backup assumptions.
- Review minimum logging and error policy.
- Harden public runtime errors.
- Validate registry and release consistency across multiple datasets.
- Validate public shell and predict views end to end.
- Review security boundaries.
- Review operational documentation needs.
- Record remaining gaps for a future roadmap.

### Out of Scope

- Marketplace.
- Public upload.
- Complex user accounts.
- Database migration unless a concrete blocker exists.
- Major architecture rewrite.
- New modeling capabilities as primary scope.
- Public retraining.

### Expected Deliverables

- Stabilization review.
- Hardened error behavior.
- Multi-dataset publication validation.
- Public experience regression validation.
- Security and operations review.
- Documentation strategy review.
- Recorded next-roadmap gaps.

### Implementation Documentation

- Applicable strategy: review `milestones-only`.
- Expected evaluation: determine whether Atlas now needs a small implementation map or operational guide.
- Candidate documents: implementation navigation note, operational release guide, or public runtime guide, only if authorized.
- Criterion to create: create documentation only if the project has enough parallel areas that milestones alone are no longer sufficient.
- Criterion to update: update architecture and roadmap if stabilization reveals changed assumptions.
- Criterion not to update: do not create documentation as a substitute for tests and evidence.

### Dependencies

- M11 through M19 completed or explicitly scoped as not applicable.
- Public runtime and web experience operational.
- Multiple datasets or multiple views available for regression validation.

### Components or Areas Affected

- Published Releases.
- Registry.
- Public Runtime API.
- Public Web Experience.
- Predict Views.
- Evidence Layer.
- Deployment and Operations.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: release consistency needs validation.
  - Possible issue type: stabilization.
  - Note: validate across datasets and active releases.
- Criterion: public errors need hardening.
  - Possible issue type: runtime hardening.
  - Note: errors must be safe and actionable.
- Criterion: documentation strategy needs review.
  - Possible issue type: documentation decision.
  - Note: decide whether milestones-only remains enough.

### Definition of Done

- Publication invariants are reviewed.
- Public runtime errors are safe and predictable.
- Multi-dataset and/or multi-view scenarios are regression-tested.
- Security boundary is reviewed.
- Operational documentation strategy is evaluated.
- Remaining gaps are recorded without becoming automatic scope.

### Minimum Evidence

- Stabilization test results.
- Error behavior review.
- Registry/release validation.
- Public experience review.
- Security review.
- Documentation strategy decision.

### Risks and Gaps

- Risk of turning stabilization into a new feature milestone.
- Risk of leaving operational risks undocumented.
- Risk of delaying necessary architecture corrections.
- Gap: future roadmap may require database, authentication, richer admin, or broader platform decisions.

### Derivability Criteria

The milestone will be ready to derive issues when:

- core publication flows exist;
- multi-dataset or multi-view behavior is testable;
- security and operations risks are identifiable;
- stabilization can be separated from new feature development.

### Continuity Notes

This milestone should close the second roadmap block and prepare a future planning cycle based on evidence from real operation.

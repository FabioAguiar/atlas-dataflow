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
| M9 | First public cycle closure | First demonstrable cycle stabilized and documented | Yes |
| M10 | Initial private internal administration | Evaluation and possible introduction of a private control plane | With reservations |
| M11 | Controlled expansion to a second dataset | Architecture validated beyond the first dataset | With reservations |

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

Evaluate and, if justified, introduce a minimal internal administrative surface to operate publication and releases without exposing public administration.

### Problem or Gap

Publication operations may become inconvenient if they depend only on manual tooling. An internal surface can improve operation, as long as it does not duplicate publisher logic and does not become part of the public surface.

### Context

The architecture defines that the internal publisher must exist before any web administration. Internal administration is optional, future-facing, and accessible only through a private surface, such as an SSH tunnel, private network, or equivalent mechanism.

### Core Scope

- Evaluation of the real need for internal admin.
- Definition of private access surface.
- Querying releases and candidates, if applicable.
- Controlled triggering of existing publisher operations.
- Querying results or operational evidence.
- Verification that admin is not publicly exposed.

### Out of Scope

- Public admin.
- Complex multi-user login.
- Broad relational CRUD.
- Complete administrative framework as a mandatory requirement.
- Public upload.
- Public retraining.
- Long and fragile pipeline execution in an HTTP request.
- Duplication of publisher logic.
- Replacing publisher with UI.

### Expected Deliverables

- Documented decision to create or defer internal admin.
- If created, minimal and private internal surface.
- Integration with existing publisher operations.
- Guarantee of no public exposure.
- Criteria for safe operation.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: review whether internal admin increases the need for operational documentation.
- Candidate documents: short operational private access documentation, if authorized.
- Criterion to create: create documentation only if there is operational risk without minimum instruction.
- Criterion to update: update when the private access mechanism changes.
- Criterion not to update: do not create an Implementation Map because of minimal admin existence.

### Dependencies

- M5 completed.
- M9 completed or first public cycle stabilized.
- Real operational need identified.
- Private access mechanism decided.

### Components or Areas Affected

- Future Internal Administration.
- Internal Publisher.
- Security.
- Deployment and Operations.
- Registry and Published Releases.

### Expected Issues or Derivation Criteria

- Criterion: publisher is already solid and manual operation has become a bottleneck.
  - Possible issue type: private internal admin.
  - Note: the issue must prove need before creating UI.
- Criterion: private access needs to be validated.
  - Possible issue type: security boundary.
  - Note: admin cannot appear on the public internet.
- Criterion: administrative operation needs to call publisher.
  - Possible issue type: internal integration.
  - Note: do not duplicate publication rules.

### Definition of Done

- Decision to create or defer internal admin is explicit.
- If created, admin is accessible only through a private surface.
- Admin calls publisher operations.
- No public administrative route exists.
- Long operations are not executed in a fragile way through public request.
- Security of the internal surface was reviewed.

### Minimum Evidence

- Decision recorded.
- Public surface review.
- Private access validation, if created.
- Publisher operation validation through admin, if created.
- Confirmation that admin does not replace publisher.

### Risks and Gaps

- Risk of admin growing into a complex panel too early.
- Risk of exposing admin through deployment configuration.
- Risk of duplicating publisher logic.
- Risk of an HTTP request becoming an executor of a heavy pipeline.
- Gap: real need for admin may not exist after M9.
- Gap: exact private access mechanism depends on infrastructure.

### Derivability Criteria

The milestone will be ready to derive issues when:

- publisher is completed and validated;
- operational need is demonstrated;
- public/internal boundary is clear;
- private access mechanism is decided;
- out of scope prevents complex admin.

### Continuity Notes

This milestone is derivable with reservations. It should be deferred if the publisher CLI or internal tooling is sufficient to operate Atlas at the current stage.

## M11 — Controlled Expansion to a Second Dataset

### Objective

Validate that Atlas can publish more than one dataset without architectural redesign or hardcoding of the first case.

### Problem or Gap

The first dataset may prove the public experience, but it does not by itself prove that the architecture supports multiple datasets. A second dataset helps validate the generality of the registry, contracts, publisher, and runtime.

### Context

The vision provides for evolution toward multiple datasets. The architecture requires that the first dataset not be treated as a special case and that resolution occur by `dataset_slug` and `active_release`.

### Core Scope

- Selection of a suitable second dataset.
- Generation of candidate artifacts.
- Contracts compatible with the architectural model.
- Release candidate validated.
- Publication via publisher.
- Registry with multiple datasets.
- Additional public experience.
- Verification that runtime has no hardcode for the first dataset.

### Out of Scope

- Public upload.
- Marketplace.
- Multi-user operation.
- Multiple experiences per dataset.
- Predict views.
- Complex admin.
- Architecture rewrite.
- Excessive generalization for any possible dataset.

### Expected Deliverables

- Second dataset published.
- Registry resolving multiple datasets.
- Second release published and traceable.
- Separate public experience.
- Functional inference for both datasets, when applicable.
- Review of couplings to the first dataset.

### Implementation Documentation

- Applicable strategy: `milestones-only`.
- Expected evaluation: review whether multiple implemented areas begin to justify `implementation-map-single`.
- Candidate documents: possible documentation for publishing a new dataset, if authorized.
- Criterion to create: consider cumulative documentation if publishing the second dataset requires navigation through many areas.
- Criterion to update: update architecture or milestones if new boundaries appear.
- Criterion not to update: do not create a map if the process remains simple and covered by publisher, contracts, and milestones.

### Dependencies

- M9 completed.
- M5 functional.
- M6 functional.
- M7 functional.
- Second dataset chosen.
- First-cycle publication strategy validated.

### Components or Areas Affected

- Published Dataset Registry.
- Published Releases.
- Contract Layer.
- Internal Publisher.
- Inference Runtime.
- Public Web Experience.
- Security and Traceability.

### Expected Issues or Derivation Criteria

- Criterion: second dataset needs to be chosen.
  - Possible issue type: dataset selection.
  - Note: should evaluate demonstrative capability and simplicity.
- Criterion: pipeline needs to generate compatible artifacts.
  - Possible issue type: dataset publication.
  - Note: must not create exceptions in the runtime.
- Criterion: runtime needs to serve multiple datasets.
  - Possible issue type: multi-dataset validation.
  - Note: resolve through registry, not through hardcode.

### Definition of Done

- Second dataset is published.
- Registry contains more than one valid dataset.
- Each dataset has an active release.
- Each public experience is separately accessible.
- Runtime resolves datasets by slug.
- The first dataset is not a special case.
- Traceability is preserved in both datasets.
- Documentation strategy has been reevaluated.

### Minimum Evidence

- Registry validated with multiple datasets.
- Publication of the second dataset validated.
- Public experience of the second dataset reviewed.
- Applicable prediction or interaction validated.
- Absence of hardcode reviewed.
- Documentation strategy evaluation recorded.

### Risks and Gaps

- Risk of excessive generalization after only two datasets.
- Risk of choosing a dataset unsuitable for demonstrating value.
- Risk of adapting runtime to the second dataset through exceptions.
- Gap: selection criteria for the second dataset need to be defined.
- Gap: documentation strategy may need review after multiple areas evolve.

### Derivability Criteria

The milestone will be ready to derive issues when:

- first public cycle is closed;
- publication process for the first dataset is clear;
- second dataset has selection criteria;
- boundaries between pipeline, publisher, and runtime are preserved;
- need for additional documentation has been reevaluated.

### Continuity Notes

This milestone should validate multi-dataset capability in a controlled way. It must not automatically open the path to marketplace, public upload, or complex administration.

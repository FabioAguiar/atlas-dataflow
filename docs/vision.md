# Vision

## Purpose

This document records the high-level direction of Atlas DataFlow.

It serves as a foundational reference for future decisions about architecture, milestones, documentation, and incremental evolution of the project.

This document is not a detailed architecture, roadmap, backlog, issue list, execution plan, or final technical specification. It defines the project's purpose, boundaries, priorities, and high-level success criteria.

At the current stage, this vision also authorizes the transition from a contract-driven runtime foundation into a design-backed product surface composed of public dataset experiences and a private administrative curation layer.

## Project Overview

Atlas DataFlow is a platform for transforming data studies into web-based predictive experiences that can be published per dataset.

The project organizes the transition between exploratory analysis, data contracts, predictive artifacts, metrics, visualizations, and interactive experience. Its purpose is to allow a studied dataset to move beyond a notebook, script, or static report and become a searchable, traceable, and interactive web experience.

Each published dataset should be able to have its own environment inside Atlas, including problem context, relevant information about the data, model metrics, visualizations, and predictive interaction. The central value of the project is connecting technical artifacts to an understandable and demonstrable experience.

Atlas is not merely a collection of notebooks, an inference API, or an interface for models. It acts as a publication layer between data studies and predictive experiences accessible through the web.

The next product stage adds a private administrative surface that allows operators to discover generated runs, prepare public dataset details, curate presentation metadata, preview changes, and publish deterministic public snapshots. This administrative layer exists to support publication and curation. It must not replace contracts, runtime validation, publisher rules, or released artifacts as sources of truth.

## Problem or Opportunity

Data studies often end in notebooks, local scripts, isolated reports, or models that are difficult to demonstrate. Even when a trained model exists, the final delivery is often disconnected from a public, reproducible, and validatable experience.

This scenario creates recurring limitations:

- analyses remain difficult to access outside the original technical environment;
- predictive models are difficult for external users to test;
- forms and interfaces tend to duplicate validation rules;
- contracts, metrics, and artifacts remain poorly traceable;
- each new dataset requires repetitive effort to become a web experience;
- the relationship between data, model, inference, and presentation is not always explicit;
- runs generated from notebooks can remain available in the filesystem without a clear promotion path into a curated public dataset experience;
- hardcoded example datasets can help bootstrap the runtime, but they should not remain the product model for future datasets.

The opportunity for Atlas is to create a standardized and auditable way to publish predictive experiences from datasets, preserving the link between contract, artifacts, metrics, presentation, and inference.

Hypothesis to validate: a small but coherent flow from generated run to curated public dataset experience is enough to demonstrate the central value of Atlas, provided the public surface remains clear and the administrative surface remains private, proportional, and deterministic.

## Target Audience or Users

The target audience includes:

- visitors who access published predictive experiences;
- people interested in exploring a dataset through context, visualizations, and inference;
- technical professionals who want to transform data studies into structured web demonstrations;
- operators responsible for preparing, publishing, and maintaining datasets inside the platform;
- technical evaluators who need to understand the relationship between data, contract, model, metrics, publication, and experience.

External visitors should consume already published experiences through the public surface. They should not see internal runs, operational tools, draft states, release preparation workflows, or administration routes.

Internal operators may use a private administrative surface to inspect runs, promote a run into a dataset detail draft, curate public presentation fields, preview a draft, publish a versioned snapshot, and control whether an already published snapshot is publicly visible.

At this stage, there is no mandatory definition of public dataset creation by third parties, complex permissions, multiple organizations, or marketplace-style publishing. Any administrative capability must remain proportional to the product goal and must not turn Atlas into a broad MLOps platform.

## Main Objective

Establish Atlas DataFlow as a platform capable of publishing web-based predictive experiences per dataset, connecting context, contract, model, metrics, visualizations, and inference interaction in a traceable and secure way.

This objective will be met at a high level when a person can access a published experience, understand the dataset, interact with a contract-driven predictive form, and receive a stable response from the model.

The next implementation objective is to make this publication flow visible and operable through design-backed screens, while preserving the deterministic relationship between generated runs, contracts, artifacts, drafts, previews, published snapshots, public visibility, and runtime inference.

## Secondary Objectives

- Allow multiple datasets to be published inside Atlas.
- Preserve contracts as the source of truth for consistency, validation, forms, and inference.
- Prevent the interface from concentrating business logic.
- Maintain traceability between dataset, run, contract, model, metrics, visualizations, public profile, and published artifacts.
- Support incremental, safe, and testable evolution.
- Consider public deployment in a containerized environment that can run on a VPS.
- Reduce dependence on notebooks as the final delivery format for data studies.
- Allow new dataset experiences to be added without restarting the system from scratch.
- Maintain a clear separation between public surface and internal processes.
- Provide a private Dashboard for run discovery and dataset publication preparation.
- Provide a private Dataset Admin screen for public content curation, theme/home-card presentation, inference form presentation, preview, and publishing controls.
- Provide minimal Settings and Help screens as part of the administrative shell, with Settings initially limited to changing the displayed user name.
- Replace permanent hardcoded dataset assumptions with registry-driven and artifact-driven dataset discovery, while allowing Telco and Bank to remain as seeded examples.
- Keep the design documentation under `design/` as a deterministic UX reference for the next implementation milestones.

## Project Core

The core of Atlas includes:

- publication of predictive experiences per dataset;
- a distinct identity for each published dataset;
- the contract as the structural source of truth;
- a public web experience for context, visualization, and interaction;
- an inference runtime based on published artifacts;
- a traceable link between run, contract, model, metrics, visualizations, profile, and publication;
- separation between exploration, artifact generation, publication, curation, and public consumption;
- secure public operation, without exposing internal services;
- a private and proportional administrative layer for preparing and publishing dataset experiences.

Atlas only makes sense if it can transform a data study into an accessible and verifiable predictive web experience.

The administrative layer only makes sense if it helps this transformation happen safely. It must orchestrate and present publication state; it must not become an independent source of contract truth, model truth, validation truth, or runtime behavior.

## Desired Features or Capabilities

At the vision level, Atlas should aim for the following capabilities:

- register publishable datasets with their own identity;
- discover generated runs that can be promoted into public dataset preparations;
- expose a public Home experience listing published datasets;
- expose a public Dataset Detail experience per dataset;
- present the context of the problem and the dataset;
- present metrics and essential information about the model;
- present relevant visualizations for understanding the dataset when public-safe visualization artifacts exist;
- render inference forms from a contract;
- render categorical/select inputs from public-safe contract options instead of frontend-invented values;
- validate inference inputs consistently through contract-driven runtime validation;
- execute predictions using published artifacts;
- preserve the relationship between contract, model, metrics, public profile, and publication;
- allow operators to prepare dataset detail drafts from generated runs;
- allow operators to curate public-facing metadata without mutating technical contract fields;
- allow operators to organize inference form presentation while preserving runtime contract authority;
- allow operators to preview draft changes before publication;
- allow operators to publish a deterministic, versioned public snapshot;
- allow operators to control public visibility of a published snapshot separately from draft editing;
- provide clear visual feedback for drag-and-drop operations, including a visible dragged object attached to the pointer when appropriate;
- provide minimal Settings and Help routes in the private admin shell;
- allow evolution toward multiple datasets without relying on Telco and Bank as hardcoded product assumptions;
- keep internal services outside the public surface.

These capabilities describe product direction, not a detailed backlog.

## Out of Scope

The following are outside the current vision and the next product stage:

- public upload of datasets;
- marketplace for models or datasets;
- public dataset creation by third parties;
- public editing of contracts;
- public execution of notebooks;
- public creation of pipelines by third parties;
- model retraining through the public interface;
- turning the administrative shell into a complex multi-user backoffice;
- multiple organizations;
- complex authentication and authorization beyond what is necessary to keep the administrative surface private;
- public exposure of databases, orchestrators, deployment tools, generated runs, draft states, or internal services;
- attempting to cover the entire MLOps lifecycle;
- making visual design prototypes override runtime contracts, publisher rules, or artifact schemas;
- an architecture that is too large for the first complete public/admin delivery.

These items may be reevaluated in the future, but they should not guide the current implementation cycle.

## Known Constraints

- Atlas must be suitable for real web publication.
- Deployment must consider a containerized environment and execution on a VPS.
- The public surface must expose only experiences, public contracts, public presentation data, and the endpoints required for application consumption.
- The private administrative surface must not expose internal services as public product capabilities.
- The frontend must not concentrate business logic.
- Contracts must act as the source of truth for forms, inference, validation, and consistency.
- Public presentation metadata may customize labels, descriptions, ordering, theme, home-card content, visibility, and preview behavior, but it must not silently alter technical contract meaning.
- The system must preserve determinism, auditability, traceability, and predictability.
- Draft configuration, preview state, published snapshot, and public visibility must have explicit and deterministic semantics.
- Internal services, databases, orchestrators, generated runs, and operational tools must not appear as part of the product's public surface.
- Technical decisions must be proportional to the goal of publishing a functional experience early.
- Hardcoded example datasets must not remain the long-term mechanism for dataset availability.
- Existing Telco and Bank examples may continue as seeded examples or fixtures, but the product flow must evolve toward registry/artifact/profile-driven dataset handling.
- The design documentation under `design/` should be treated as the closest available deterministic UX reference, while inconsistencies between design documents and executable prototypes should be corrected through explicit implementation documentation.

## User Preferences

In this vision, user preferences refer to the expected experience for those who access, publish, or operate Atlas.

- Visiting users should be able to understand the published experience without depending on internal project knowledge.
- Visiting users should interact with models through clear, contract-driven forms.
- Visiting users should see public dataset pages that are readable, visually coherent, and stable across desktop, tablet, and mobile contexts where applicable.
- Technical users should be able to trace the relationship between dataset, run, contract, model, metrics, public profile, snapshot, and publication.
- Users responsible for publication should have a predictable, controlled, and validatable flow.
- Operators should be able to distinguish draft configuration from public snapshot state.
- Operators should be able to preview draft changes before publishing them.
- Operators should understand that public visibility applies to the published snapshot, not to unsaved or unpublished draft changes.
- Drag-and-drop interactions should provide intuitive visual feedback while an item is being moved.
- The public experience should prioritize clarity, stability, and consistency.
- Product evolution should favor initial simplicity, modularity, and low coupling.
- Documentation should be searchable by humans and by technical support tools.

## Success Criteria

The current vision will be considered well served when:

- a public version of Atlas is accessible through a URL;
- at least one dataset is published as its own web experience;
- the public Home lists datasets from registry/artifact/profile state instead of frontend hardcoding;
- the Dataset Detail experience allows the dataset context to be understood;
- the experience presents relevant information about data, model, metrics, and visualizations when available;
- the experience allows functional predictive interaction;
- inference uses published artifacts and not improvised logic in the interface;
- select/categorical fields are rendered from public-safe contract data rather than frontend-invented options;
- contract, model, metrics, profile, snapshot, and public experience are connected in a traceable way;
- the public surface does not expose internal services, generated runs, draft states, or administrative controls;
- the private Dashboard can discover generated runs and start preparation of public dataset details;
- the private Dataset Admin can curate public presentation state, preview drafts, publish deterministic snapshots, and control public visibility;
- Settings and Help exist as minimal private admin routes;
- the created foundation allows evolution toward new datasets without starting over or requiring hardcoded dataset additions.

## Risks and Uncertainties

- Risk of disorganized growth if the vision does not maintain clear boundaries.
- Risk of overengineering if administrative features, multi-user operation, or marketplace capabilities are anticipated too early.
- Risk of coupling if pipeline, runtime, contract, model, public profile, and interface do not have clear boundaries.
- Risk of improperly exposing internal services if minimum security and public/private boundaries are not considered from the beginning.
- Risk that the public experience becomes too technical and not very understandable for external visitors.
- Risk that the administrative experience becomes a source of truth for technical behavior instead of a curation and publication layer.
- Risk that design prototypes are copied mechanically without reconciling them with contracts, artifacts, schemas, tests, and API boundaries.
- Risk that hardcoded Telco and Bank examples remain embedded as product assumptions instead of becoming seeded examples.
- Risk that draft, preview, publish, and visibility semantics become ambiguous if not modeled explicitly.
- Risk that the first published dataset does not demonstrate the value of Atlas well.
- Uncertainty about the best persistence strategy for dataset public profiles and published public snapshots.
- Uncertainty about how much admin functionality is necessary before Atlas feels complete enough as a demonstrable product.
- Uncertainty about how to balance initial simplicity and future multi-dataset capability.

## Pending Decisions

- Define the minimum level of operational documentation required for deployment and maintenance.
- Define the persistence model for dataset public profiles, drafts, published snapshots, and visibility state.
- Define how generated notebook runs should be indexed, validated, promoted, and eventually removed.
- Define which visualization artifacts are required for a complete public dataset experience and which remain optional.
- Define how public-safe categorical options are projected from runtime contracts.
- Define the minimum privacy/security mechanism required before the administrative surface can be considered private.
- Define which conceptual capabilities should appear first when the admin shell starts replacing design prototypes.

## Anchors for Architecture

The future architecture should consider the following anchors:

- separate exploratory study, generated run, build pipeline, published artifacts, public profile, web runtime, and public consumption;
- treat contract, model, public profile, and interface as distinct responsibilities;
- keep contracts as the source of truth for validation and guided rendering;
- allow publication per dataset without relying on hardcoding for a single case;
- support generated run discovery without exposing runs through the public surface;
- support a private administrative surface that orchestrates curation and publication without becoming the runtime authority;
- model draft, preview, published snapshot, and visibility as distinct states;
- consider containers, HTTPS, environment variables, and VPS operation from the beginning;
- prevent internal services from becoming part of the public surface;
- avoid making a database, complex authentication, or complex orchestration mandatory dependencies of the first complete public/admin cycle unless they become necessary for correctness;
- favor an architecture simple enough to publish early;
- preserve traceability between published artifacts;
- avoid coupling between exploration, artifact generation, profile curation, and public experience;
- allow future evolution without requiring a complete redesign for each new dataset.

These anchors do not define the final architecture. They guide updates to `docs/architecture.md`.

## Anchors for Milestones

Future milestones should follow these guidelines:

- start with a documented foundation and controlled scope;
- update vision and architecture before implementing screens that were previously deferred;
- treat `design/` as the closest available deterministic UX reference for public and admin surfaces;
- reconcile inconsistencies between design markdown and executable HTML/CSS/JS before using them as implementation instructions;
- move toward a minimal technical bootstrap before advanced capabilities;
- prioritize an initial public dataset experience and a private publication workflow early;
- validate contract, inference, public profile, preview, publish, and public experience in small increments;
- include public deployment as part of the path, not as a distant step;
- include minimum security before public exposure of admin routes;
- leave marketplace capabilities, public upload, multi-organization operation, and complex permissions for a later stage;
- avoid milestones that are too large or difficult to validate;
- preserve compatibility with small, testable microphases that avoid regressions;
- keep each step connected to the goal of publishing a demonstrable experience.

These anchors are not milestones. They guide updates to `docs/milestones.md` and issue planning.

## Anchors for Implementation Documentation

The project is likely to benefit from cumulative documentation because it now spans contracts, runtime, publication, frontend, artifacts, design references, admin curation, deployment, and security.

The implementation documentation strategy should remain proportional. The project should avoid creating a large documentation framework before implementation proves which seams are stable. However, the following documentation anchors are useful for the next stage:

- design documents under `design/` should remain aligned with the implemented screen behavior;
- inconsistencies between design markdown and HTML/CSS/JS prototypes should be documented before implementation issues depend on them;
- public/admin boundary decisions should be recorded in architecture or decision records;
- dataset public profile semantics should be documented before they become persistent runtime behavior;
- run promotion and publishing semantics should be documented before they become operator-facing behavior;
- validation and release evidence should continue to support milestone and issue closure.

The final implementation documentation strategy should be reevaluated as the admin and public UI layers become real. Possible options still include:

- `milestones-only`;
- `implementation-map-single`;
- `implementation-map-hierarchical`;
- `implementation-index-assisted`;
- `not-applicable`.

Current signals suggest that `milestones-only` may remain sufficient for very small implementation slices, but it may become limited as the project now includes multiple product surfaces and state transitions. The decision should be made later, based on the real architecture and implementation size.

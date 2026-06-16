# Vision

## Purpose

This document records the high-level direction of Atlas DataFlow.

It serves as a foundational reference for future decisions about architecture, milestones, documentation, and incremental evolution of the project.

This document is not a detailed architecture, roadmap, backlog, issue list, execution plan, or final technical specification. It defines the project's purpose, boundaries, priorities, and high-level success criteria.

## Project Overview

Atlas DataFlow is a platform for transforming data studies into web-based predictive experiences that can be published per dataset.

The project organizes the transition between exploratory analysis, data contracts, predictive artifacts, metrics, and interactive experience. Its purpose is to allow a studied dataset to move beyond a notebook, script, or static report and become a searchable, traceable, and interactive web experience.

Each published dataset should be able to have its own environment inside Atlas, including problem context, relevant information about the data, model metrics, visualizations, and predictive interaction. The central value of the project is connecting technical artifacts to an understandable and demonstrable experience.

Atlas is not merely a collection of notebooks, an inference API, or an interface for models. It acts as a publication layer between data studies and predictive experiences accessible through the web.

## Problem or Opportunity

Data studies often end in notebooks, local scripts, isolated reports, or models that are difficult to demonstrate. Even when a trained model exists, the final delivery is often disconnected from a public, reproducible, and validatable experience.

This scenario creates recurring limitations:

- analyses remain difficult to access outside the original technical environment;
- predictive models are difficult for external users to test;
- forms and interfaces tend to duplicate validation rules;
- contracts, metrics, and artifacts remain poorly traceable;
- each new dataset requires repetitive effort to become a web experience;
- the relationship between data, model, inference, and presentation is not always explicit.

The opportunity for Atlas is to create a standardized and auditable way to publish predictive experiences from datasets, preserving the link between contract, artifacts, metrics, and interface.

Hypothesis to validate: a first small and functional published experience is enough to demonstrate the central value of Atlas before adding more advanced administrative or operational features.

## Target Audience or Users

The initial target audience includes:

- visitors who access published predictive experiences;
- people interested in exploring a dataset through context, visualizations, and inference;
- technical professionals who want to transform data studies into structured web demonstrations;
- operators responsible for publishing and maintaining datasets inside the platform;
- technical evaluators who need to understand the relationship between data, contract, model, metrics, and experience.

At this stage, the external audience should consume already published experiences. Internal processes for preparation, publication, infrastructure, administration, and maintenance are not part of the product's public surface.

At this stage, there is no mandatory definition of multi-user operation, public dataset creation by third parties, complex permissions, or multi-organization operation.

## Main Objective

Establish Atlas DataFlow as a platform capable of publishing web-based predictive experiences per dataset, connecting context, contract, model, metrics, visualizations, and inference interaction in a traceable and secure way.

This objective will be met at a high level when a person can access a published experience, understand the dataset, interact with a contract-driven predictive form, and receive a stable response from the model.

## Secondary Objectives

- Allow multiple datasets to be published inside Atlas.
- Preserve contracts as the source of truth for consistency, validation, forms, and inference.
- Prevent the interface from concentrating business logic.
- Maintain traceability between dataset, contract, model, metrics, and published artifacts.
- Support incremental, safe, and testable evolution.
- Consider public deployment in a containerized environment that can run on a VPS.
- Reduce dependence on notebooks as the final delivery format for data studies.
- Allow new dataset experiences to be added without restarting the system from scratch.
- Maintain a clear separation between public surface and internal processes.

## Project Core

The core of Atlas includes:

- publication of predictive experiences per dataset;
- a distinct identity for each published dataset;
- the contract as the structural source of truth;
- a public web experience for context, visualization, and interaction;
- an inference runtime based on published artifacts;
- a traceable link between contract, model, metrics, and publication;
- separation between exploration, artifact generation, publication, and public consumption;
- secure public operation, without exposing internal services.

Atlas only makes sense if it can transform a data study into an accessible and verifiable predictive web experience.

## Desired Features or Capabilities

At the vision level, Atlas should aim for the following capabilities:

- register publishable datasets with their own identity;
- expose a public experience per dataset;
- present the context of the problem and the dataset;
- present metrics and essential information about the model;
- present relevant visualizations for understanding the dataset;
- render inference forms from a contract;
- validate inference inputs consistently;
- execute predictions using published artifacts;
- preserve the relationship between contract, model, metrics, and publication;
- allow evolution toward multiple datasets;
- keep internal services outside the public surface;
- allow future administrative layers to be added without making them a requirement of the initial cycle.

These capabilities describe product direction, not a detailed backlog.

## Out of Scope

The following are outside the initial vision and the first public cycle:

- public upload of datasets;
- marketplace for models or datasets;
- advanced customization of experiences;
- complex administrative panel;
- model retraining through the public interface;
- public editing of contracts;
- public execution of notebooks;
- public creation of pipelines by third parties;
- multiple organizations;
- complex authentication and authorization;
- public exposure of databases, orchestrators, deployment tools, or internal services;
- attempting to cover the entire MLOps lifecycle;
- an architecture that is too large for the first public delivery.

These items may be reevaluated in the future, but they should not guide the initial core.

## Known Constraints

- Atlas must be suitable for real web publication.
- Deployment must consider a containerized environment and execution on a VPS.
- The public surface must expose only experiences, public contracts, and the endpoints required for application consumption.
- The frontend must not concentrate business logic.
- Contracts must act as the source of truth for forms, inference, and consistency.
- The system must preserve determinism, auditability, traceability, and predictability.
- Internal services, databases, orchestrators, and operational tools must not appear as part of the product's public surface.
- The initial publication must avoid complex administration, multi-user operation, marketplace, public upload, and advanced customization.
- Technical decisions must be proportional to the goal of publishing a functional experience early.

## User Preferences

In this vision, user preferences refer to the expected experience for those who access, publish, or operate Atlas.

- Visiting users should be able to understand the published experience without depending on internal project knowledge.
- Visiting users should interact with models through clear, contract-driven forms.
- Technical users should be able to trace the relationship between dataset, contract, model, metrics, and publication.
- Users responsible for publication should have a predictable, controlled, and validatable flow.
- The public experience should prioritize clarity, stability, and consistency.
- Product evolution should favor initial simplicity, modularity, and low coupling.
- Documentation should be searchable by humans and by technical support tools.

## Success Criteria

The initial vision will be considered well served when:

- a public version of Atlas is accessible through a URL;
- at least one dataset is published as its own web experience;
- the experience allows the dataset context to be understood;
- the experience presents relevant information about data, model, and metrics;
- the experience allows functional predictive interaction;
- inference uses published artifacts and not improvised logic in the interface;
- contract, model, metrics, and public experience are connected in a traceable way;
- the public surface does not expose internal services;
- the created foundation allows evolution toward new datasets without starting over.

## Risks and Uncertainties

- Risk of disorganized growth if the vision does not maintain clear boundaries.
- Risk of overengineering if administrative features, multi-user operation, or marketplace capabilities are anticipated too early.
- Risk of coupling if pipeline, runtime, contract, model, and interface do not have clear boundaries.
- Risk of improperly exposing internal services if minimum security is not considered from the beginning.
- Risk that the public experience becomes too technical and not very understandable for external visitors.
- Risk that the first published dataset does not demonstrate the value of Atlas well.
- Uncertainty about the best way to store and version dataset publications.
- Uncertainty about the final stack of the project.
- Uncertainty about the ideal level of cumulative documentation to support continuity without generating documentation excess.
- Uncertainty about how to balance initial simplicity and future multi-dataset capability.

## Pending Decisions

- Confirm which dataset will be published first.
- Define the final technical stack.
- Define the initial persistence or storage approach for published artifacts.
- Define the versioning strategy for dataset publications.
- Define the initial model for public domain, routes, and URLs.
- Define whether the first publication will have only one experience per dataset or whether it will already leave conceptual room for multiple future experiences.
- Define the minimum level of operational documentation required for deployment and maintenance.
- Define the future implementation documentation strategy if the project grows into multiple areas.
- Define which conceptual capabilities should appear first.

## Anchors for Architecture

The future architecture should consider the following anchors:

- separate exploratory study, build pipeline, published artifacts, and web runtime;
- treat contract, model, and interface as distinct responsibilities;
- keep contracts as the source of truth for validation and guided rendering;
- allow publication per dataset without relying on hardcoding for a single case;
- consider containers, HTTPS, environment variables, and VPS operation from the beginning;
- prevent internal services from becoming part of the public surface;
- avoid making a database, advanced administration, or complex orchestration mandatory dependencies of the first public cycle;
- favor an architecture simple enough to publish early;
- preserve traceability between published artifacts;
- avoid coupling between exploration, artifact generation, and public experience;
- allow future evolution without requiring a complete redesign for each new dataset.

These anchors do not define the final architecture. They should guide the future creation of `docs/architecture.md`.

## Anchors for Milestones

Future milestones should follow these guidelines:

- start with a documented foundation and controlled scope;
- move toward a minimal technical bootstrap before advanced capabilities;
- prioritize an initial public dataset experience early;
- validate contract, inference, and public experience in small increments;
- include public deployment as part of the initial path, not as a distant step;
- include minimum security before public exposure;
- leave advanced administration, multi-user operation, and marketplace capabilities for after the first public cycle;
- avoid milestones that are too large or difficult to validate;
- preserve compatibility with small, testable microphases that avoid regressions;
- keep each step connected to the goal of publishing a demonstrable experience.

These anchors are not milestones. They should guide the future creation of `docs/milestones.md`.

## Anchors for Implementation Documentation

The project is likely to benefit from cumulative documentation in the future because it involves multiple potential areas: contracts, runtime, publication, frontend, artifacts, deployment, and security.

The final implementation documentation strategy should not yet be decided at this stage. The future architecture should proportionally evaluate options such as:

- `milestones-only`;
- `implementation-map-single`;
- `implementation-map-hierarchical`;
- `implementation-index-assisted`;
- `not-applicable`.

Current signals suggest that `milestones-only` may be sufficient at the beginning, but it may become limited if the project grows into multiple areas. The decision should be made later, based on the real architecture and the size of the implementation.

No implementation map should be created at this stage.

## Notes for Next Steps

Likely next documentation steps:

- review and approve this `docs/vision.md`;
- confirm essential gaps, especially the first dataset and initial stack;
- generate `docs/architecture.md` from this vision;
- generate `docs/milestones.md` only after the initial architecture is clear;
- keep the scope of the first public cycle small, safe, and demonstrable;
- avoid implementation before consolidating the main boundaries.

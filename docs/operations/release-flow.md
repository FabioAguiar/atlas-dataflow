# Release Operation Validation Checklist

This checklist is an operator aid for validating Atlas DataFlow releases from dataset preparation through public browser verification. It does not replace executable tests, schemas, release manifests, validation evidence, runtime behavior, architecture, or ASF operational State.

Use the repository's implemented validation entry points and reduced evidence artifacts as the authoritative source for each checkpoint. Do not copy secrets, private URLs, raw logs, raw payloads, runtime dumps, credentials, production-only paths, or environment-specific values into this document or release evidence.

## Validation Boundaries

- Treat datasets and releases as the main operational units.
- Treat contracts as the source of truth for validation, inference input shape, and guided rendering.
- Treat release candidates as publishable packages only after validation passes.
- Treat published releases as immutable; do not silently overwrite published artifacts.
- Keep pipeline, publisher, registry, public runtime API, and public web experience responsibilities separate.
- Keep internal publisher, pipeline, logs, databases, volumes, credentials, and operational tooling outside the public surface.
- Do not add tests, change validation commands, or document unimplemented checks as current behavior from this checklist.

## Local Verification

Run local checks against the repository's implemented commands, scripts, schemas, tests, and reduced evidence sources. Record only reduced, sanitized outcomes.

### Dataset Preparation

- Confirm the dataset input is the intended source for the release candidate.
- Confirm preparation outputs are reproducible from governed dataflow artifacts, not notebook memory or ad hoc local state.
- Confirm prepared dataset metadata and hashes are available for downstream traceability.
- Confirm raw source data, private paths, and local-only runtime values are not projected into public artifacts.

### Contract Promotion

- Confirm human-facing, execution, runtime, and public contract artifacts are the expected versions for the dataset.
- Confirm contract validation succeeds before release candidate assembly.
- Confirm public contract projection contains only fields and hints safe for browser consumption.
- Confirm runtime validation remains contract-driven and is not duplicated as frontend-only business logic.

### Model and Bundle Compatibility

- Confirm training outputs are linked to the prepared dataset, contract versions, metrics, and model evidence.
- Confirm the inference bundle declares input schema, feature order, preprocessing behavior, output shape, model reference, and compatibility constraints.
- Confirm bundle validation rejects missing model files, stale contract references, inconsistent feature names, and unsupported loader types.
- Confirm a valid local inference smoke check uses the bundle and contract rather than training internals.

### Release Candidate Completeness

- Confirm the release candidate includes required public and runtime artifacts: manifest, contracts, inference bundle, metrics, model card, public context, and any publishable visualizations or descriptions.
- Confirm manifest and hash validation link artifacts back to governed dataflow inputs.
- Confirm placeholder-only or fixture-only artifacts are rejected where real dataflow outputs are required.
- Confirm candidate validation checks cross-artifact consistency before promotion.

### Publisher and Registry

- Confirm publisher validation passes before promotion.
- Confirm promotion is explicit and does not mutate an existing published release in place.
- Confirm registry activation identifies the intended `dataset_slug` and `active_release`.
- Confirm previous releases remain preserved according to the current release model.
- Confirm publication evidence links the release candidate, manifest, hashes, registry activation, and selected release.

## Staging Verification

Use staging to verify the promoted or staged release through deployed service boundaries before relying on public behavior.

### Runtime API

- Confirm the public API healthcheck is available.
- Confirm dataset listing returns the expected public dataset identity and does not expose internal registry or file system details.
- Confirm public dataset metadata, public contract, metrics, model card, and context responses match the active release.
- Confirm a known valid payload returns a successful prediction through the public runtime.
- Confirm invalid payloads fail predictably and safely without internal paths, stack traces, raw contract internals, or sensitive values.
- Confirm runtime resolves the dataset and active release from the registry rather than temporary pipeline state.

### Public Web Experience

- Confirm dataset listing renders from the API response shape.
- Confirm the dataset home or dataset view renders public context, metrics, model card information, and release metadata safely.
- Confirm the prediction form renders from the public contract.
- Confirm a valid prediction flow submits the expected payload shape and presents a structured result.
- Confirm invalid input feedback is understandable and does not expose sensitive implementation details.
- Confirm frontend behavior does not redefine validation semantics that belong to the runtime contract.

### Exposure Review

- Confirm no public route exposes training, upload, publication, registry mutation, internal administration, private publisher operations, local databases, volumes, logs, or credentials.
- Confirm public errors are non-sensitive.
- Confirm CORS, HTTPS, payload-size, and deployment boundary checks are reviewed through the project's implemented deployment validation process.
- Confirm evidence and logs used for review are reduced and sanitized before persistence.

## Public Verification

Use public verification only after local and staging checks pass, and only against the intended published release.

- Confirm the public domain reaches the expected web experience over the configured secure surface.
- Confirm public dataset listing and dataset detail pages load the intended active release.
- Confirm public contract-driven form rendering matches the staging behavior.
- Confirm a representative valid prediction succeeds through the public API and browser path.
- Confirm a representative invalid payload fails safely and consistently.
- Confirm public responses do not expose internal services, local file paths, private URLs, credentials, raw logs, raw payloads, or production-only details.
- Confirm public artifacts remain immutable during runtime use.

## Evidence Checklist

For each release operation, keep reduced evidence that identifies the checkpoint and outcome without copying raw runtime data.

- Dataset preparation metadata and hash outcome.
- Contract validation outcome.
- Bundle compatibility validation outcome.
- Release candidate manifest and hash validation outcome.
- Publisher validation and promotion outcome.
- Registry activation outcome.
- Public API validation outcome for dataset listing, metadata, valid prediction, and invalid payload.
- Browser validation outcome for listing, dataset view, form rendering, valid prediction, and invalid input handling.
- Exposure review outcome confirming no private operational data was documented or exposed.

## Rejection Conditions

Reject the release operation until corrected if any of these conditions are observed:

- A checklist item relies on unimplemented behavior, an undocumented manual shortcut, or an unstable assumption.
- A candidate cannot be traced back to governed dataflow artifacts.
- Contracts, bundle, model, metrics, manifest, or registry references are stale or inconsistent.
- The publisher would overwrite a published release silently.
- The runtime depends on notebook state, training files, temporary pipeline outputs, or implicit local paths.
- The browser or API accepts payloads that the runtime contract should reject.
- Public output exposes internal paths, private URLs, raw logs, raw payloads, secrets, credentials, local databases, volumes, or production-only values.
- Validation evidence is missing, raw, unsanitized, or treated as replaceable by this checklist.

## Update Criteria

Update this checklist when implemented validation entry points, release artifacts, public routes, contract responsibilities, publisher behavior, registry activation rules, or public exposure boundaries change. Do not update it as a changelog, backlog, operational State, or substitute for tests and evidence.

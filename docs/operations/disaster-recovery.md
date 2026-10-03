# Disaster Recovery Runbook

## Purpose and boundary

This document is the repository-owned disaster-recovery contract for Atlas DataFlow. It defines which assets must be recoverable after the loss of a host or of persistent state, the order in which they are restored, and the evidence a recovery exercise must produce.

This runbook is not evidence that a backup exists or that a restore has succeeded. Its presence in the repository proves nothing about the actual deployment. Whether PostgreSQL, Storage, canonical Atlas state, secrets, or TLS material are currently backed up and restorable can only be answered by separate operational evidence collected against the real backup sources and restore targets.

Production readiness for backup and recovery remains `blocked` while any required recovery source is missing or any readiness-critical domain lacks a tested restore. A missing source or an untested restore is a blocker, never implicit success.

Never commit to this document, to the repository, or to recovery evidence: secret values, tokens, passwords, API keys, private keys, database dumps, storage archives, registry snapshots, raw backup contents, or raw recovery logs. Use placeholders such as `<approved-secret-source>` for anything environment-specific.

This runbook does not choose a backup provider and does not define a backup command, schedule, retention period, encryption scheme, off-site topology, RPO, or RTO. The repository does not currently establish any of these; they must be decided and evidenced operationally before they are referenced as facts.

## Recovery concepts

These four concepts are distinct. Having one never implies having another.

| Concept | What it is | What it is not |
| --- | --- | --- |
| Git/source reconstruction | Re-cloning the repository at a known revision to recover application code, Compose files, and versioned contracts. | Not a recovery of any runtime or persistent state; Git does not hold database contents, secrets, or the deployment's live registry/release/run state. |
| Local transactional rollback (`*.previous`) | The sibling `*.json.previous` files written by `registry/file_backup.py` before a registry mutation, used to roll back a single failed file-update transaction. | Not disaster recovery. They live in the same directory, on the same host and disk, as the files they protect; they cover only specific registry files and only the immediately previous version. Loss of the host or volume loses them too. |
| Durable backup / recovery source | A copy of a persistence domain held independently of the failed host, from which that domain can be rebuilt. | Not proven by the existence of a path, volume, or bind mount. A backup is only a recovery source once its location, integrity, and coverage are evidenced. |
| Restore validation / recovery exercise | Actually restoring from a recovery source into a target and validating the result. | Not satisfied by this runbook, by a backup job reporting success, or by a backup file existing. Only a performed and recorded restore counts. |

## Recovery asset classes

Each class below must have an identified recovery source before recovery readiness can be claimed. Entries describe what must be recovered, never its values.

1. **Application source and deployment revision** — the exact repository revision deployed (commit SHA or equivalent immutable snapshot). Recoverable from Git, provided the deployed revision is recorded.
2. **Infrastructure and deployment definitions** — `docker-compose.yml` (private), `docker-compose.prod.yml` (public), image build definitions, and any host-level proxy/ingress configuration needed to recreate the runtime. Versioned parts come from Git; host-only parts need their own recovery source.
3. **Non-versioned configuration and secrets** — values intentionally kept out of the repository, such as the backend-only Supabase JWT verification settings, the operator user identifier, the inference gateway credential, publishable build-time values, and any provisioning-only Supabase credentials (see `docs/operations/admin-operator-provisioning.md`). Must be restored from an approved secret source, never from the repository.
4. **Supabase/PostgreSQL database state** — the Atlas-specific Supabase project/stack database, including Auth identities, the operator account and its server-side role metadata, authorization and quota state, and other database-owned operational data.
5. **Supabase Storage state** — storage buckets and objects, when the deployment relies on Supabase Storage. If the deployment does not use it, record that as `not_applicable` with a reason rather than omitting it.
6. **Atlas canonical state** — the filesystem state the API reads and writes: the registry (dataset registry, public profiles, profile snapshots, profile publications, predict views and customizations, registry evidence), releases, publisher runs, and Admin-managed media such as home cards, as applicable to the deployment. In the private deployment these are bind-mounted into the API container; in the public deployment only the subset it mounts or bakes in applies.
7. **Private Admin TLS server material** — the private Admin endpoint's TLS leaf certificate and private key when the same server identity is reused after recovery. The client CA / private trust chain that authorizes clients is managed separately; its CA private key must stay with its owner and is never placed in the repository or on the application host to satisfy this runbook.
8. **Network, ingress, DNS, and firewall prerequisites** — domain records, reverse proxy/ingress, firewall rules, private network attachments (for example the trusted Atlas/Supabase Docker network), and any tunnel or forwarding needed to reconnect the recovered deployment.
9. **Operator authorization state** — what is required to regain private Admin access: the operator account in Supabase Auth, its server-side `atlas_role`, the matching configured operator user identifier, and the operator's ability to authenticate (including administrative password recovery from the Supabase project).

## Loss scenarios

Losing different persistence domains has different effects. Assess each domain independently.

- **Canonical Atlas state lost, database state survives** — Auth, operator, and quota state are intact, but datasets, releases, runs, profiles, publications, and Admin media are gone. Public dataset pages and predictions fail or show nothing until canonical state is restored. Re-running pipelines from source can regenerate some artifacts but does not reproduce the exact published releases, registry state, or publication history; that requires a canonical-state recovery source.
- **Database/auth state lost, canonical Atlas state survives** — datasets and releases are present on disk, but the operator account, its role, visitor sessions, and quota/authorization state are gone. Private Admin access fails closed until the operator is re-provisioned and the configured operator user identifier matches the new account. Public gateway authorization and quota behaviour depend on the restored database state.
- **Non-versioned secrets/configuration lost** — the services may build but the backend fails closed: Admin rejects every request, and the public inference route rejects every request when its gateway credential is empty. Values must be restored from the approved secret source or rotated and re-issued; they cannot be recovered from Git.
- **TLS server material lost** — the private Admin endpoint cannot present its previous server identity. Reissue a new leaf certificate through the owner of the trust chain, and update clients that pinned the old identity. Do not generate or import a CA private key on the application host as a shortcut.
- **Source code available, persistent state unavailable** — Git reconstruction recovers code and deployment definitions only. The result is an empty or fail-closed deployment, not a recovered one. It must not be reported as recovery of database, storage, canonical state, secrets, or TLS material.

## Restore order

Follow this sequence; each step depends on the ones before it. Environment-specific commands are placeholders and must come from the deployment's own operational procedure.

1. **Host and runtime prerequisites** — provision or restore the host, container runtime, and the non-root runtime account/ownership model the deployment uses.
2. **Source and deployment definitions** — check out the repository at the recorded known revision (`<deployed-revision>`); restore host-only deployment definitions from their recovery source.
3. **Non-versioned configuration and secrets** — inject values from `<approved-secret-source>`. Do not copy them into the repository, into recovery evidence, or into logs.
4. **Database and storage state** — restore Supabase/PostgreSQL and, when used, Supabase Storage from `<database-recovery-source>` and `<storage-recovery-source>`. Dependent Atlas services are not considered recovered until this step is validated.
5. **Atlas canonical state** — restore registry, releases, runs, profile/publication state, and Admin media from `<canonical-state-recovery-source>`, with filesystem ownership and permissions that let the non-root API account read and, where required, write them. Do not treat `*.previous` files as the recovery source.
6. **Private Admin TLS server material** — restore the leaf certificate and key from their recovery source, or reissue them through the trust-chain owner. The client CA private key stays outside the repository and outside the application host.
7. **Start services in dependency order** — recreate the API and wait for its health check before starting the web service, matching the dependency order in the Compose files.
8. **Validate before re-exposing traffic** — confirm service health; public/private access boundaries (public `/admin` and `/api/admin` return 404, private Admin admits only the provisioned operator); persistence consistency between registry, releases, and publications; and the image/deployment invariants enforced by the repository's Compose gate tests. Only then reconnect ingress, DNS, and firewall paths.
9. **Record a reduced recovery result** — write the evidence described below. Never persist raw logs, dumps, or secrets.

## Recovery evidence and readiness

A recovery exercise produces one reduced, secret-free evidence record, following the evidence discipline of `docs/operations/first-version-readiness.md`. Minimum content:

- `source_revision` — the evaluated repository revision;
- `recovery_target` — an identifier for the recovery environment/target, without secret material;
- `recovery_sources` — identifiers or digests of each backup/recovery source used, where safe to record;
- `asset_classes_attempted` — which of the nine asset classes were in scope, each with a per-class outcome, or `not_applicable` with a reason;
- `restore_steps_attempted` — which restore-order steps were performed;
- `validation_checks` — each check and its reduced outcome (status codes, counts, digests; no raw payloads);
- `reservations` and `blockers` — explicit, owned entries;
- `started_at` and `recorded_at` — ISO 8601 timestamps;
- `outcome` — exactly one aggregate value: `ready`, `ready_with_documented_reservations`, or `blocked`;
- `raw_logs_persisted: false` and `secrets_persisted: false`.

Rules for the aggregate outcome:

- `blocked` whenever a readiness-critical asset class has no identified recovery source, or has no performed and validated restore.
- `ready_with_documented_reservations` only when every readiness-critical class was restored and validated, and every remaining reservation is bounded, owned, and non-safety-critical.
- `ready` only when every in-scope class was restored and validated with no reservations.
- This runbook, a backup job's success report, or the existence of a path or volume is never evidence for `ready`.

"""
Project Spec S0155: External Analysis Handoff Schema, Trust, and Read-Only
Import Boundary Contract.

Side-effect-free, read-only validator for a producer-owned external analysis
handoff package. This module never writes to the package root, the Atlas
repository, or the support root; never imports or executes producer code;
and never deserializes an opaque artifact (no joblib, no pickle -- neither
library is imported anywhere in this module).

Trust model: a handoff document's own `trusted_source_declaration` is a
producer assertion only. It is never sufficient by itself to make any
artifact load-eligible. The caller of `validate_external_analysis_handoff`
must separately pass `trusted_source_confirmed=True`; a missing or false
confirmation is recorded as a failure and `load_eligible` is always False
in that case, regardless of what the handoff document itself claims.

The package root is execution context supplied explicitly by the caller.
A path or identifier named inside the handoff JSON (e.g. `source_dataset_ref`,
`producer_repository_reference`) is never used as a filesystem location --
only `artifact_inventory[].path` entries are resolved, and only beneath the
caller-supplied `package_root`.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

_SCHEMA_PATH = Path(__file__).parent / "external-analysis-handoff.schema.json"

_JSON_CONTENT_KINDS = frozenset({"json_evidence", "json_manifest"})
_KNOWN_CONTENT_KINDS = frozenset(
    {"json_evidence", "json_manifest", "opaque_model_artifact", "static_visual_evidence", "documentation"}
)

# Locally supported semantic fingerprint profiles. A profile name not present
# here fails closed (Acceptance Criterion 20) rather than being silently
# accepted. "json-canonical-sha256.v1" is independently recomputed from the
# artifact's own parsed JSON bytes; it is only applicable to JSON-parseable
# content kinds. "cross-artifact-reference.v1" never deserializes anything --
# it only requires that every artifact_inventory entry sharing this profile
# name declare the same fingerprint value, which is how a producer-declared
# opaque model-state fingerprint may be cross-checked without ever loading
# the model (Acceptance Criterion 21).
_PROFILE_JSON_CANONICAL_SHA256 = "json-canonical-sha256.v1"
_PROFILE_CROSS_ARTIFACT_REFERENCE = "cross-artifact-reference.v1"
_SUPPORTED_SEMANTIC_FINGERPRINT_PROFILES = frozenset(
    {_PROFILE_JSON_CANONICAL_SHA256, _PROFILE_CROSS_ARTIFACT_REFERENCE}
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ValidationFailure:
    """A single, typed validation failure identifying the exact field,
    artifact role, or path that failed."""

    code: str
    message: str
    role: str | None = None
    path: str | None = None
    field_path: str | None = None


@dataclass(frozen=True)
class ArtifactValidationResult:
    """Deterministic, typed result for a single artifact_inventory entry."""

    role: str
    declared_path: str
    required: bool
    content_kind: str
    present: bool
    declared_sha256: str
    observed_sha256: str | None
    sha256_matches: bool | None
    json_parsed: bool
    semantic_fingerprint_status: str | None


@dataclass(frozen=True)
class ValidationResult:
    """Immutable validation report. Constructed once and never mutated."""

    valid: bool
    schema_valid: bool
    trusted_source_confirmed: bool
    load_eligible: bool
    handoff_id: str | None
    validated_identities: Mapping[str, Any]
    artifact_results: tuple[ArtifactValidationResult, ...]
    failures: tuple[ValidationFailure, ...]
    warnings: tuple[str, ...]
    generated_at: str


def _load_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


def _schema_failures(instance: dict) -> list[ValidationFailure]:
    import jsonschema

    schema = _load_schema()
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    return [
        ValidationFailure(
            code="schema_validation_failed",
            message=e.message,
            field_path=".".join(str(p) for p in e.path) or None,
        )
        for e in errors
    ]


def _is_safe_relative_path(candidate: str) -> bool:
    """Independent, defense-in-depth safety check, re-checked in Python even
    though the schema's own pattern already constrains artifact paths --
    never rely solely on schema regex before touching the filesystem."""
    if not candidate or candidate.strip() == "":
        return False
    if candidate.startswith("/"):
        return False
    if "\\" in candidate:
        return False
    if len(candidate) >= 2 and candidate[1] == ":" and candidate[0].isalpha():
        return False
    if candidate.startswith("//"):
        return False
    parts = candidate.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return False
    return True


def _normalize_path(candidate: str) -> str:
    return posixpath.normpath(candidate)


def _resolve_within_root(package_root: Path, relative_path: str) -> Path | None:
    """Resolve `relative_path` beneath `package_root`, following symlinks,
    and return None if the resolved location escapes the package root
    (path or symlink-based escape) -- checked before any content is read."""
    candidate = (package_root / relative_path).resolve()
    try:
        candidate.relative_to(package_root)
    except ValueError:
        return None
    return candidate


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_sha256(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_external_analysis_handoff(
    handoff: dict | str | Path,
    package_root: str | Path,
    trusted_source_confirmed: bool,
    *,
    expected_dataset_slug: str | None = None,
    expected_consumer_component: str | None = None,
    expected_producer_project_id: str | None = None,
    generated_at: str | None = None,
) -> ValidationResult:
    """Validate an external analysis handoff package.

    `handoff` is either an already-parsed handoff payload (dict) or a path
    to one. `package_root` is the caller's own, explicitly supplied
    filesystem root for the package -- never inferred from any path named
    inside the handoff document. `trusted_source_confirmed` is the caller's
    own explicit trust decision; a handoff's internal
    `trusted_source_declaration` is never sufficient by itself.

    Performs no writes anywhere. Never imports or executes producer code.
    Never deserializes an opaque artifact (no joblib, no pickle).
    """
    failures: list[ValidationFailure] = []
    warnings: list[str] = []

    if isinstance(handoff, dict):
        instance = handoff
    else:
        handoff_path = Path(handoff)
        try:
            instance = json.loads(handoff_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            failures.append(
                ValidationFailure(code="handoff_not_found", message=f"handoff file not found: {handoff_path}")
            )
            return ValidationResult(
                valid=False,
                schema_valid=False,
                trusted_source_confirmed=bool(trusted_source_confirmed),
                load_eligible=False,
                handoff_id=None,
                validated_identities=MappingProxyType({}),
                artifact_results=(),
                failures=tuple(failures),
                warnings=tuple(warnings),
                generated_at=generated_at or _utc_now_iso(),
            )
        except json.JSONDecodeError as exc:
            failures.append(
                ValidationFailure(code="handoff_not_valid_json", message=f"handoff is not valid JSON: {exc}")
            )
            return ValidationResult(
                valid=False,
                schema_valid=False,
                trusted_source_confirmed=bool(trusted_source_confirmed),
                load_eligible=False,
                handoff_id=None,
                validated_identities=MappingProxyType({}),
                artifact_results=(),
                failures=tuple(failures),
                warnings=tuple(warnings),
                generated_at=generated_at or _utc_now_iso(),
            )

    if not isinstance(instance, dict):
        failures.append(
            ValidationFailure(code="handoff_not_an_object", message="parsed handoff payload is not a JSON object")
        )
        return ValidationResult(
            valid=False,
            schema_valid=False,
            trusted_source_confirmed=bool(trusted_source_confirmed),
            load_eligible=False,
            handoff_id=None,
            validated_identities=MappingProxyType({}),
            artifact_results=(),
            failures=tuple(failures),
            warnings=tuple(warnings),
            generated_at=generated_at or _utc_now_iso(),
        )

    schema_failures = _schema_failures(instance)
    failures.extend(schema_failures)
    schema_valid = not schema_failures

    if not schema_valid:
        # Stop before any downstream identity/path/hash inspection: the
        # document's own shape is not trustworthy enough to walk further.
        return ValidationResult(
            valid=False,
            schema_valid=False,
            trusted_source_confirmed=bool(trusted_source_confirmed),
            load_eligible=False,
            handoff_id=instance.get("handoff_id") if isinstance(instance.get("handoff_id"), str) else None,
            validated_identities=MappingProxyType({}),
            artifact_results=(),
            failures=tuple(failures),
            warnings=tuple(warnings),
            generated_at=generated_at or _utc_now_iso(),
        )

    handoff_id = instance["handoff_id"]
    producer = instance["producer"]
    consumer = instance["consumer"]
    dataset_identity = instance["dataset_identity"]

    validated_identities = {
        "handoff_id": handoff_id,
        "producer_project_id": producer["producer_project_id"],
        "consumer_component": consumer["consumer_component"],
        "dataset_slug": dataset_identity["dataset_slug"],
    }

    # --- Identity validation (expected-value cross-checks) -----------------
    if expected_dataset_slug is not None and dataset_identity["dataset_slug"] != expected_dataset_slug:
        failures.append(
            ValidationFailure(
                code="dataset_slug_mismatch",
                message=(
                    f"dataset_identity.dataset_slug {dataset_identity['dataset_slug']!r} does not match "
                    f"expected {expected_dataset_slug!r}"
                ),
                field_path="dataset_identity.dataset_slug",
            )
        )
    if expected_consumer_component is not None and consumer["consumer_component"] != expected_consumer_component:
        failures.append(
            ValidationFailure(
                code="consumer_component_mismatch",
                message=(
                    f"consumer.consumer_component {consumer['consumer_component']!r} does not match "
                    f"expected {expected_consumer_component!r}"
                ),
                field_path="consumer.consumer_component",
            )
        )
    if (
        expected_producer_project_id is not None
        and producer["producer_project_id"] != expected_producer_project_id
    ):
        failures.append(
            ValidationFailure(
                code="producer_project_id_mismatch",
                message=(
                    f"producer.producer_project_id {producer['producer_project_id']!r} does not match "
                    f"expected {expected_producer_project_id!r}"
                ),
                field_path="producer.producer_project_id",
            )
        )

    # --- Artifact inventory: paths, presence, hashes, content, fingerprints
    package_root_path = Path(package_root)
    package_root_valid = package_root_path.is_dir()
    if not package_root_valid:
        failures.append(
            ValidationFailure(
                code="package_root_not_a_directory",
                message=f"package_root is not a directory: {package_root_path}",
            )
        )
    else:
        package_root_path = package_root_path.resolve()

    inventory: list[dict] = instance["artifact_inventory"]

    seen_roles: dict[str, str] = {}
    seen_normalized_paths: dict[str, str] = {}
    fingerprints_by_profile: dict[str, list[tuple[str, str]]] = {}

    artifact_results: list[ArtifactValidationResult] = []

    for entry in inventory:
        role = entry["role"]
        declared_path = entry["path"]
        required = entry["required"]
        content_kind = entry["content_kind"]
        declared_sha256 = entry["sha256"]
        semantic_fingerprint = entry.get("semantic_fingerprint")

        if role in seen_roles and seen_roles[role] != declared_path:
            failures.append(
                ValidationFailure(
                    code="duplicate_role_declaration",
                    message=f"role {role!r} is declared more than once with conflicting paths",
                    role=role,
                )
            )
        seen_roles.setdefault(role, declared_path)

        normalized = _normalize_path(declared_path)
        if normalized in seen_normalized_paths and seen_normalized_paths[normalized] != role:
            failures.append(
                ValidationFailure(
                    code="duplicate_artifact_path",
                    message=f"normalized path {normalized!r} is declared by more than one role",
                    role=role,
                    path=declared_path,
                )
            )
        seen_normalized_paths.setdefault(normalized, role)

        if not _is_safe_relative_path(declared_path):
            failures.append(
                ValidationFailure(
                    code="unsafe_artifact_path",
                    message=f"artifact path is not a safe relative reference: {declared_path!r}",
                    role=role,
                    path=declared_path,
                )
            )
            artifact_results.append(
                ArtifactValidationResult(
                    role=role,
                    declared_path=declared_path,
                    required=required,
                    content_kind=content_kind,
                    present=False,
                    declared_sha256=declared_sha256,
                    observed_sha256=None,
                    sha256_matches=None,
                    json_parsed=False,
                    semantic_fingerprint_status="not_evaluated",
                )
            )
            continue

        resolved: Path | None = None
        if package_root_valid:
            resolved = _resolve_within_root(package_root_path, declared_path)
            if resolved is None:
                failures.append(
                    ValidationFailure(
                        code="artifact_path_escapes_package_root",
                        message=f"artifact path resolves outside package_root: {declared_path!r}",
                        role=role,
                        path=declared_path,
                    )
                )

        present = bool(resolved is not None and resolved.is_file())

        if not present:
            if required:
                failures.append(
                    ValidationFailure(
                        code="required_artifact_missing",
                        message=f"required artifact is absent: role={role!r} path={declared_path!r}",
                        role=role,
                        path=declared_path,
                    )
                )
            artifact_results.append(
                ArtifactValidationResult(
                    role=role,
                    declared_path=declared_path,
                    required=required,
                    content_kind=content_kind,
                    present=False,
                    declared_sha256=declared_sha256,
                    observed_sha256=None,
                    sha256_matches=None,
                    json_parsed=False,
                    semantic_fingerprint_status="not_evaluated",
                )
            )
            continue

        observed_sha256 = _sha256_of_file(resolved)
        sha256_matches = observed_sha256 == declared_sha256
        if not sha256_matches:
            failures.append(
                ValidationFailure(
                    code="artifact_hash_mismatch",
                    message=(
                        f"byte SHA-256 mismatch for role={role!r} path={declared_path!r}: "
                        f"declared={declared_sha256} observed={observed_sha256}"
                    ),
                    role=role,
                    path=declared_path,
                )
            )

        json_parsed = False
        parsed_payload: Any = None
        if content_kind in _JSON_CONTENT_KINDS:
            try:
                parsed_payload = json.loads(resolved.read_text(encoding="utf-8"))
                json_parsed = True
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                failures.append(
                    ValidationFailure(
                        code="artifact_json_parse_failed",
                        message=f"artifact declared as {content_kind} is not valid JSON: {exc}",
                        role=role,
                        path=declared_path,
                    )
                )

        semantic_fingerprint_status = None
        if semantic_fingerprint is not None:
            profile = semantic_fingerprint["profile"]
            value = semantic_fingerprint["value"]
            if profile not in _SUPPORTED_SEMANTIC_FINGERPRINT_PROFILES:
                failures.append(
                    ValidationFailure(
                        code="semantic_fingerprint_profile_unsupported",
                        message=f"semantic fingerprint profile is not locally supported: {profile!r}",
                        role=role,
                        path=declared_path,
                    )
                )
                semantic_fingerprint_status = "unsupported_profile"
            elif profile == _PROFILE_JSON_CANONICAL_SHA256:
                if content_kind not in _JSON_CONTENT_KINDS:
                    failures.append(
                        ValidationFailure(
                            code="semantic_fingerprint_profile_not_applicable",
                            message=(
                                f"{_PROFILE_JSON_CANONICAL_SHA256} is only applicable to JSON-parseable "
                                f"content kinds, not {content_kind!r}"
                            ),
                            role=role,
                            path=declared_path,
                        )
                    )
                    semantic_fingerprint_status = "not_applicable"
                elif json_parsed:
                    computed = _canonical_json_sha256(parsed_payload)
                    if computed == value:
                        semantic_fingerprint_status = "verified"
                    else:
                        failures.append(
                            ValidationFailure(
                                code="semantic_fingerprint_mismatch",
                                message=(
                                    f"semantic fingerprint mismatch for role={role!r}: "
                                    f"declared={value} computed={computed}"
                                ),
                                role=role,
                                path=declared_path,
                            )
                        )
                        semantic_fingerprint_status = "mismatch"
                else:
                    semantic_fingerprint_status = "not_evaluated"
            else:
                # cross-artifact-reference.v1: never recomputed from opaque
                # bytes -- only cross-checked for equality across every
                # other inventory entry declaring the same profile name.
                fingerprints_by_profile.setdefault(profile, []).append((role, value))
                semantic_fingerprint_status = "pending_cross_check"

        artifact_results.append(
            ArtifactValidationResult(
                role=role,
                declared_path=declared_path,
                required=required,
                content_kind=content_kind,
                present=True,
                declared_sha256=declared_sha256,
                observed_sha256=observed_sha256,
                sha256_matches=sha256_matches,
                json_parsed=json_parsed,
                semantic_fingerprint_status=semantic_fingerprint_status,
            )
        )

    # --- Cross-artifact-reference.v1 equality cross-check ------------------
    for profile, declarations in fingerprints_by_profile.items():
        distinct_values = {value for _role, value in declarations}
        if len(distinct_values) > 1:
            roles = ", ".join(sorted(role for role, _value in declarations))
            failures.append(
                ValidationFailure(
                    code="semantic_fingerprint_cross_reference_mismatch",
                    message=(
                        f"{profile} is declared with conflicting values across roles: {roles}"
                    ),
                )
            )
            for index, artifact_result in enumerate(artifact_results):
                if (
                    artifact_result.semantic_fingerprint_status == "pending_cross_check"
                    and artifact_result.role in {role for role, _value in declarations}
                ):
                    artifact_results[index] = ArtifactValidationResult(
                        **{**artifact_result.__dict__, "semantic_fingerprint_status": "cross_reference_mismatch"}
                    )
        else:
            for index, artifact_result in enumerate(artifact_results):
                if (
                    artifact_result.semantic_fingerprint_status == "pending_cross_check"
                    and artifact_result.role in {role for role, _value in declarations}
                ):
                    status = "verified" if len(declarations) > 1 else "no_cross_reference_peer"
                    artifact_results[index] = ArtifactValidationResult(
                        **{**artifact_result.__dict__, "semantic_fingerprint_status": status}
                    )

    # --- Trusted-source confirmation ---------------------------------------
    if not trusted_source_confirmed:
        failures.append(
            ValidationFailure(
                code="trusted_source_confirmation_missing",
                message=(
                    "trusted_source_confirmed was not supplied as True by the caller; a handoff's own "
                    "trusted_source_declaration is never sufficient by itself"
                ),
            )
        )

    valid = not failures
    load_eligible = valid and bool(trusted_source_confirmed)

    return ValidationResult(
        valid=valid,
        schema_valid=schema_valid,
        trusted_source_confirmed=bool(trusted_source_confirmed),
        load_eligible=load_eligible,
        handoff_id=handoff_id,
        validated_identities=MappingProxyType(validated_identities),
        artifact_results=tuple(artifact_results),
        failures=tuple(failures),
        warnings=tuple(warnings),
        generated_at=generated_at or _utc_now_iso(),
    )

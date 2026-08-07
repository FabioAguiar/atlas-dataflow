"""
Project Spec S0166: Dataset Integration Authoring Manifest, Semantic Intent,
Capability Profile, and Provenance Contract.

Narrow, side-effect-free validator for the governed dataset-integration
authoring contract family:

    pipeline/dataset-integration-authoring-manifest.schema.json
    pipeline/dataset-semantic-intent.schema.json
    pipeline/capability-profile.schema.json

This module validates schema shape and the cross-artifact invariants
S0163 requires (dataset-identity agreement, capability-profile
identity/version agreement, required/forbidden/optional role applicability,
semantic target applicability, and provenance path safety). It never
derives execution, runtime, or public contracts; never loads, deserializes,
or predicts with a model; never assembles a release candidate; never
invokes publisher behavior; never writes registry state or activates a
release; and never reads an external project through an absolute path
stored in an Atlas artifact.

Capability applicability is resolved entirely from the supplied capability
profile document's own `artifact_roles`/`semantic_requirements` -- this
module contains no dataset-slug or dataset-name conditional anywhere.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_MANIFEST_SCHEMA_PATH = Path(__file__).parent / "dataset-integration-authoring-manifest.schema.json"
_SEMANTIC_INTENT_SCHEMA_PATH = Path(__file__).parent / "dataset-semantic-intent.schema.json"
_CAPABILITY_PROFILE_SCHEMA_PATH = Path(__file__).parent / "capability-profile.schema.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class ValidationFailure:
    """A single, typed validation failure identifying the exact field,
    role, or path that failed."""

    code: str
    message: str
    role: str | None = None
    path: str | None = None
    field_path: str | None = None


@dataclass(frozen=True)
class AuthoringContractValidationResult:
    """Deterministic, typed result for one authoring-contract validation run."""

    valid: bool
    manifest_schema_valid: bool
    semantic_intent_schema_valid: bool | None
    capability_profile_schema_valid: bool
    dataset_slug: str | None
    capability_profile_id: str | None
    capability_profile_version: str | None
    failures: tuple[ValidationFailure, ...]
    warnings: tuple[str, ...]
    generated_at: str


def _load_schema(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_instance(instance: dict | str | Path) -> tuple[dict | None, ValidationFailure | None]:
    if isinstance(instance, dict):
        return instance, None
    instance_path = Path(instance)
    try:
        parsed = json.loads(instance_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ValidationFailure(code="artifact_not_found", message=f"artifact file not found: {instance_path}")
    except json.JSONDecodeError as exc:
        return None, ValidationFailure(code="artifact_not_valid_json", message=f"artifact is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        return None, ValidationFailure(code="artifact_not_an_object", message="parsed artifact payload is not a JSON object")
    return parsed, None


def _schema_failures(instance: dict, schema: dict) -> list[ValidationFailure]:
    import jsonschema

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
    though the schema's own pattern already constrains reference paths --
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


def _is_lowercase_sha256(candidate: str) -> bool:
    if not isinstance(candidate, str) or len(candidate) != 64:
        return False
    return all(character in "0123456789abcdef" for character in candidate)


def _resolve_within_root(root: Path, relative_path: str) -> Path | None:
    """Resolve `relative_path` beneath `root`, following symlinks, and
    return None if the resolved location escapes root (path or
    symlink-based escape) -- checked before any content is read."""
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _sha256_of_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_authoring_contracts(
    manifest: dict | str | Path,
    capability_profile: dict | str | Path,
    *,
    semantic_intent: dict | str | Path | None = None,
    artifact_root: str | Path | None = None,
    expected_dataset_slug: str | None = None,
    generated_at: str | None = None,
) -> AuthoringContractValidationResult:
    """Validate one dataset-integration authoring manifest against its
    selected capability profile, and optionally its dataset semantic-intent
    artifact, proving the S0163 cross-artifact invariants.

    `manifest` and `capability_profile` are required; `semantic_intent` is
    optional (some validation runs only need manifest/profile agreement).
    `artifact_root` is the caller's own, explicitly supplied filesystem
    root used only to verify `manifest.artifact_references[].sha256`
    against real file bytes -- never inferred from any path named inside
    an artifact.

    Performs no writes anywhere. Never loads or deserializes a model.
    Never derives execution/runtime/public contracts, assembles a release
    candidate, or invokes publisher behavior.
    """
    failures: list[ValidationFailure] = []
    warnings: list[str] = []

    manifest_instance, load_failure = _load_instance(manifest)
    if load_failure is not None:
        return AuthoringContractValidationResult(
            valid=False,
            manifest_schema_valid=False,
            semantic_intent_schema_valid=None,
            capability_profile_schema_valid=False,
            dataset_slug=None,
            capability_profile_id=None,
            capability_profile_version=None,
            failures=(load_failure,),
            warnings=(),
            generated_at=generated_at or _utc_now_iso(),
        )

    profile_instance, profile_load_failure = _load_instance(capability_profile)
    if profile_load_failure is not None:
        return AuthoringContractValidationResult(
            valid=False,
            manifest_schema_valid=False,
            semantic_intent_schema_valid=None,
            capability_profile_schema_valid=False,
            dataset_slug=None,
            capability_profile_id=None,
            capability_profile_version=None,
            failures=(profile_load_failure,),
            warnings=(),
            generated_at=generated_at or _utc_now_iso(),
        )

    semantic_intent_instance: dict | None = None
    if semantic_intent is not None:
        semantic_intent_instance, semantic_load_failure = _load_instance(semantic_intent)
        if semantic_load_failure is not None:
            return AuthoringContractValidationResult(
                valid=False,
                manifest_schema_valid=False,
                semantic_intent_schema_valid=False,
                capability_profile_schema_valid=False,
                dataset_slug=None,
                capability_profile_id=None,
                capability_profile_version=None,
                failures=(semantic_load_failure,),
                warnings=(),
                generated_at=generated_at or _utc_now_iso(),
            )

    manifest_schema = _load_schema(_MANIFEST_SCHEMA_PATH)
    profile_schema = _load_schema(_CAPABILITY_PROFILE_SCHEMA_PATH)

    manifest_schema_failures = _schema_failures(manifest_instance, manifest_schema)
    profile_schema_failures = _schema_failures(profile_instance, profile_schema)
    manifest_schema_valid = not manifest_schema_failures
    capability_profile_schema_valid = not profile_schema_failures

    semantic_intent_schema_valid: bool | None = None
    semantic_intent_schema_failures: list[ValidationFailure] = []
    if semantic_intent_instance is not None:
        semantic_intent_schema = _load_schema(_SEMANTIC_INTENT_SCHEMA_PATH)
        semantic_intent_schema_failures = _schema_failures(semantic_intent_instance, semantic_intent_schema)
        semantic_intent_schema_valid = not semantic_intent_schema_failures

    failures.extend(manifest_schema_failures)
    failures.extend(profile_schema_failures)
    failures.extend(semantic_intent_schema_failures)

    if not manifest_schema_valid or not capability_profile_schema_valid or (
        semantic_intent_instance is not None and not semantic_intent_schema_valid
    ):
        # Stop before any cross-artifact inspection: an untrustworthy shape
        # cannot safely be walked further.
        return AuthoringContractValidationResult(
            valid=False,
            manifest_schema_valid=manifest_schema_valid,
            semantic_intent_schema_valid=semantic_intent_schema_valid,
            capability_profile_schema_valid=capability_profile_schema_valid,
            dataset_slug=None,
            capability_profile_id=None,
            capability_profile_version=None,
            failures=tuple(failures),
            warnings=tuple(warnings),
            generated_at=generated_at or _utc_now_iso(),
        )

    dataset_slug = manifest_instance["dataset_identity"]["dataset_slug"]
    manifest_profile_selection = manifest_instance["capability_profile_selection"]
    manifest_profile_id = manifest_profile_selection["capability_profile_id"]
    manifest_profile_version = manifest_profile_selection["capability_profile_version"]
    profile_id = profile_instance["capability_profile_id"]
    profile_version = profile_instance["capability_profile_version"]

    # --- Dataset identity agreement -----------------------------------------
    if expected_dataset_slug is not None and dataset_slug != expected_dataset_slug:
        failures.append(
            ValidationFailure(
                code="dataset_slug_mismatch",
                message=f"manifest dataset_slug {dataset_slug!r} does not match expected {expected_dataset_slug!r}",
                field_path="dataset_identity.dataset_slug",
            )
        )

    if semantic_intent_instance is not None:
        semantic_dataset_slug = semantic_intent_instance["dataset_identity"]["dataset_slug"]
        if semantic_dataset_slug != dataset_slug:
            failures.append(
                ValidationFailure(
                    code="dataset_identity_mismatch",
                    message=(
                        f"semantic-intent dataset_slug {semantic_dataset_slug!r} does not agree with "
                        f"manifest dataset_slug {dataset_slug!r}"
                    ),
                    field_path="dataset_identity.dataset_slug",
                )
            )

    # --- Capability profile identity/version agreement ----------------------
    if manifest_profile_id != profile_id or manifest_profile_version != profile_version:
        failures.append(
            ValidationFailure(
                code="capability_profile_identity_mismatch",
                message=(
                    f"manifest capability_profile_selection {manifest_profile_id!r}/{manifest_profile_version!r} "
                    f"does not agree with capability profile document identity {profile_id!r}/{profile_version!r}"
                ),
                field_path="capability_profile_selection",
            )
        )

    if semantic_intent_instance is not None:
        semantic_profile = semantic_intent_instance["governing_capability_profile"]
        semantic_profile_id = semantic_profile["capability_profile_id"]
        semantic_profile_version = semantic_profile["capability_profile_version"]
        if semantic_profile_id != profile_id or semantic_profile_version != profile_version:
            failures.append(
                ValidationFailure(
                    code="capability_profile_identity_mismatch",
                    message=(
                        f"semantic-intent governing_capability_profile {semantic_profile_id!r}/"
                        f"{semantic_profile_version!r} does not agree with capability profile document identity "
                        f"{profile_id!r}/{profile_version!r}"
                    ),
                    field_path="governing_capability_profile",
                )
            )

    # --- Manifest artifact reference safety (defense in depth) --------------
    artifact_references: list[dict] = manifest_instance.get("artifact_references", [])
    observed_roles: dict[str, str] = {}
    root_path: Path | None = None
    if artifact_root is not None:
        candidate_root = Path(artifact_root)
        if candidate_root.is_dir():
            root_path = candidate_root.resolve()
        else:
            failures.append(
                ValidationFailure(
                    code="artifact_root_not_a_directory",
                    message=f"artifact_root is not a directory: {candidate_root}",
                )
            )

    for entry in artifact_references:
        role = entry["role"]
        path = entry["path"]
        declared_sha256 = entry["sha256"]

        if role in observed_roles and observed_roles[role] != path:
            failures.append(
                ValidationFailure(
                    code="duplicate_manifest_role",
                    message=f"role {role!r} is declared more than once with conflicting paths",
                    role=role,
                )
            )
        observed_roles.setdefault(role, path)

        if not _is_safe_relative_path(path):
            failures.append(
                ValidationFailure(
                    code="unsafe_artifact_reference_path",
                    message=f"artifact_references path is not a safe relative reference: {path!r}",
                    role=role,
                    path=path,
                )
            )
            continue

        if not _is_lowercase_sha256(declared_sha256):
            failures.append(
                ValidationFailure(
                    code="malformed_sha256",
                    message=f"artifact_references sha256 is not a lowercase 64-character hex digest: {declared_sha256!r}",
                    role=role,
                    path=path,
                )
            )

        if root_path is not None:
            resolved = _resolve_within_root(root_path, path)
            if resolved is None:
                failures.append(
                    ValidationFailure(
                        code="artifact_reference_escapes_root",
                        message=f"artifact_references path resolves outside artifact_root: {path!r}",
                        role=role,
                        path=path,
                    )
                )
            elif not resolved.is_file():
                failures.append(
                    ValidationFailure(
                        code="artifact_reference_missing",
                        message=f"artifact_references path does not exist under artifact_root: {path!r}",
                        role=role,
                        path=path,
                    )
                )
            else:
                observed_sha256 = _sha256_of_file(resolved)
                if observed_sha256 != declared_sha256:
                    failures.append(
                        ValidationFailure(
                            code="artifact_reference_hash_mismatch",
                            message=(
                                f"byte SHA-256 mismatch for role={role!r} path={path!r}: "
                                f"declared={declared_sha256} observed={observed_sha256}"
                            ),
                            role=role,
                            path=path,
                        )
                    )

    # --- Provenance path safety ----------------------------------------------
    provenance_records: list[dict] = manifest_instance.get("provenance", [])
    for record in provenance_records:
        relative_path = record["relative_path"]
        if not _is_safe_relative_path(relative_path):
            failures.append(
                ValidationFailure(
                    code="unsafe_provenance_path",
                    message=f"provenance relative_path is not a safe relative reference: {relative_path!r}",
                    role=record.get("artifact_role"),
                    path=relative_path,
                )
            )
        if not _is_lowercase_sha256(record["sha256"]):
            failures.append(
                ValidationFailure(
                    code="malformed_sha256",
                    message=f"provenance sha256 is not a lowercase 64-character hex digest: {record['sha256']!r}",
                    role=record.get("artifact_role"),
                    path=relative_path,
                )
            )

    # --- Role applicability: required presence / forbidden absence ---------
    role_applicability: dict[str, str] = {
        role_entry["role_name"]: role_entry["applicability"] for role_entry in profile_instance["artifact_roles"]
    }
    for role_name, applicability in role_applicability.items():
        present = role_name in observed_roles
        if applicability == "required" and not present:
            failures.append(
                ValidationFailure(
                    code="required_role_missing",
                    message=f"required role is absent from manifest artifact_references: {role_name!r}",
                    role=role_name,
                )
            )
        elif applicability == "forbidden" and present:
            failures.append(
                ValidationFailure(
                    code="forbidden_role_present",
                    message=f"forbidden role is present in manifest artifact_references: {role_name!r}",
                    role=role_name,
                )
            )
        # applicability == "optional": presence or absence is both valid.

    # --- Semantic target applicability ---------------------------------------
    target_semantics_applicability = profile_instance["semantic_requirements"]["target_semantics_applicability"]
    if semantic_intent_instance is not None:
        target_semantics_present = "target_semantics" in semantic_intent_instance
        if target_semantics_applicability == "forbidden" and target_semantics_present:
            failures.append(
                ValidationFailure(
                    code="target_semantics_forbidden_but_present",
                    message="semantic-intent declares target_semantics but the resolved capability profile forbids target semantics",
                    field_path="target_semantics",
                )
            )
        elif target_semantics_applicability == "required" and not target_semantics_present:
            failures.append(
                ValidationFailure(
                    code="target_semantics_required_but_absent",
                    message="semantic-intent omits target_semantics but the resolved capability profile requires target semantics",
                    field_path="target_semantics",
                )
            )
        # "optional": either presence or absence is valid.

    valid = not failures

    return AuthoringContractValidationResult(
        valid=valid,
        manifest_schema_valid=manifest_schema_valid,
        semantic_intent_schema_valid=semantic_intent_schema_valid,
        capability_profile_schema_valid=capability_profile_schema_valid,
        dataset_slug=dataset_slug,
        capability_profile_id=manifest_profile_id,
        capability_profile_version=manifest_profile_version,
        failures=tuple(failures),
        warnings=tuple(warnings),
        generated_at=generated_at or _utc_now_iso(),
    )

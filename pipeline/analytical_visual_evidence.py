"""Side-effect-free validation for governed analytical visual evidence.

The validator only checks contract shape and supplied local evidence.  It never
executes notebooks, generates charts, loads models, predicts, publishes,
activates releases, or mutates registry state.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_VISUAL_SCHEMA = Path(__file__).parent / "analytical-visualizations.schema.json"
_CAPABILITY_SCHEMA = Path(__file__).parent / "capability-profile.schema.json"
DEFAULT_ROLE_NAME = "analytical_visual_evidence"


@dataclass(frozen=True)
class ValidationFailure:
    code: str
    message: str
    field_path: str | None = None


@dataclass(frozen=True)
class AnalyticalVisualEvidenceValidationResult:
    valid: bool
    schema_valid: bool | None
    capability_profile_schema_valid: bool | None
    failures: tuple[ValidationFailure, ...]
    warnings: tuple[str, ...]
    generated_at: str


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load(value: dict | str | Path) -> tuple[dict | None, ValidationFailure | None]:
    if isinstance(value, dict):
        return value, None
    path = Path(value)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, ValidationFailure("artifact_not_found", f"artifact file not found: {path}")
    except json.JSONDecodeError as exc:
        return None, ValidationFailure("artifact_not_valid_json", f"artifact is not valid JSON: {exc}")
    if not isinstance(parsed, dict):
        return None, ValidationFailure("artifact_not_an_object", "artifact must be a JSON object")
    return parsed, None


def _schema_failures(instance: dict, schema_path: Path) -> list[ValidationFailure]:
    import jsonschema

    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    return [
        ValidationFailure(
            "schema_validation_failed",
            error.message,
            ".".join(str(part) for part in error.absolute_path) or None,
        )
        for error in errors
    ]


def _safe_relative_path(value: object) -> bool:
    if not isinstance(value, str) or not value or value.startswith(("/", "file://", "//")):
        return False
    if "\\" in value or (len(value) > 1 and value[0].isalpha() and value[1] == ":"):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _lowercase_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _applicability(profile: dict | None, role_name: str) -> str | None:
    if profile is None:
        return None
    for role in profile.get("artifact_roles", []):
        if role.get("role_name") == role_name:
            return role.get("applicability")
    return None


def validate_analytical_visual_evidence(
    visual_evidence: dict | str | Path | None,
    *,
    capability_profile: dict | str | Path | None = None,
    asset_root: str | Path | None = None,
    expected_dataset_slug: str | None = None,
    expected_capability_profile_id: str | None = None,
    expected_capability_profile_version: str | None = None,
    role_name: str = DEFAULT_ROLE_NAME,
    generated_at: str | None = None,
) -> AnalyticalVisualEvidenceValidationResult:
    """Validate an optional visual-evidence role against explicitly supplied context."""
    failures: list[ValidationFailure] = []
    warnings: list[str] = []
    profile: dict | None = None
    profile_schema_valid: bool | None = None

    if capability_profile is not None:
        profile, load_failure = _load(capability_profile)
        if load_failure:
            failures.append(load_failure)
            profile_schema_valid = False
        else:
            profile_failures = _schema_failures(profile, _CAPABILITY_SCHEMA)
            failures.extend(profile_failures)
            profile_schema_valid = not profile_failures

    applicability = _applicability(profile if profile_schema_valid else None, role_name)
    if visual_evidence is None:
        if applicability == "required":
            failures.append(ValidationFailure("required_role_missing", f"required role {role_name!r} is absent"))
        return AnalyticalVisualEvidenceValidationResult(
            not failures, None, profile_schema_valid, tuple(failures), tuple(warnings), generated_at or _now()
        )
    if applicability == "forbidden":
        failures.append(ValidationFailure("forbidden_role_present", f"forbidden role {role_name!r} is present"))

    artifact, load_failure = _load(visual_evidence)
    if load_failure:
        failures.append(load_failure)
        return AnalyticalVisualEvidenceValidationResult(False, False, profile_schema_valid, tuple(failures), tuple(warnings), generated_at or _now())

    schema_errors = _schema_failures(artifact, _VISUAL_SCHEMA)
    failures.extend(schema_errors)
    schema_valid = not schema_errors
    if not schema_valid:
        return AnalyticalVisualEvidenceValidationResult(False, False, profile_schema_valid, tuple(failures), tuple(warnings), generated_at or _now())

    # Legacy artifacts are deliberately accepted by the preserved v1 branch.
    if artifact.get("schema_version") == "analytical-visualizations.v1":
        return AnalyticalVisualEvidenceValidationResult(not failures, True, profile_schema_valid, tuple(failures), tuple(warnings), generated_at or _now())

    dataset_slug = artifact["dataset_identity"]["dataset_slug"]
    selected_profile = artifact["capability_profile"]
    checks = (
        (expected_dataset_slug, dataset_slug, "dataset_identity_mismatch", "dataset_identity.dataset_slug"),
        (expected_capability_profile_id, selected_profile["capability_profile_id"], "capability_profile_id_mismatch", "capability_profile.capability_profile_id"),
        (expected_capability_profile_version, selected_profile["capability_profile_version"], "capability_profile_version_mismatch", "capability_profile.capability_profile_version"),
    )
    for expected, actual, code, field_path in checks:
        if expected is not None and expected != actual:
            failures.append(ValidationFailure(code, f"expected {expected!r}, found {actual!r}", field_path))

    if profile_schema_valid:
        if selected_profile["capability_profile_id"] != profile["capability_profile_id"]:
            failures.append(ValidationFailure("capability_profile_id_mismatch", "artifact and supplied capability profile ids differ", "capability_profile.capability_profile_id"))
        if selected_profile["capability_profile_version"] != profile["capability_profile_version"]:
            failures.append(ValidationFailure("capability_profile_version_mismatch", "artifact and supplied capability profile versions differ", "capability_profile.capability_profile_version"))

    visual_ids: set[str] = set()
    root = Path(asset_root).resolve() if asset_root is not None else None
    for index, visual in enumerate(artifact["visuals"]):
        prefix = f"visuals.{index}"
        if not visual["public_suitability_reason"].strip():
            failures.append(ValidationFailure("public_suitability_reason_missing", "public suitability requires a non-blank rationale", f"{prefix}.public_suitability_reason"))
        visual_id = visual["visual_id"]
        if visual_id in visual_ids:
            failures.append(ValidationFailure("duplicate_visual_id", f"duplicate visual_id {visual_id!r}", f"{prefix}.visual_id"))
        visual_ids.add(visual_id)
        relative_path = visual["relative_asset_path"]
        if not _safe_relative_path(relative_path):
            failures.append(ValidationFailure("unsafe_relative_asset_path", f"unsafe relative asset path: {relative_path!r}", f"{prefix}.relative_asset_path"))
            continue
        if not _lowercase_sha256(visual["sha256"]):
            failures.append(ValidationFailure("invalid_sha256", "asset sha256 must be lowercase hexadecimal", f"{prefix}.sha256"))
            continue
        if root is not None:
            candidate = (root / relative_path).resolve()
            try:
                candidate.relative_to(root)
            except ValueError:
                failures.append(ValidationFailure("asset_path_escapes_root", "asset path resolves outside supplied root", f"{prefix}.relative_asset_path"))
                continue
            if not candidate.is_file():
                failures.append(ValidationFailure("asset_not_found", f"asset file not found: {relative_path}", f"{prefix}.relative_asset_path"))
            elif _hash_file(candidate) != visual["sha256"]:
                failures.append(ValidationFailure("asset_hash_mismatch", f"asset hash does not match: {relative_path}", f"{prefix}.sha256"))

    return AnalyticalVisualEvidenceValidationResult(
        not failures, True, profile_schema_valid, tuple(failures), tuple(warnings), generated_at or _now()
    )

"""
Candidate assembly pipeline for atlas-dataflow (M13-04).

Assembles a publisher-compatible candidate artifact set from build outputs
and a pre-staged source directory, validates the assembled candidate against
publisher requirements, and returns a JSON result to stdout.

Does NOT call publisher/promote.py.
Does NOT read or modify registry/datasets.json.
Does NOT write to any path outside releases/candidates/.
"""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent

_REQUIRED_SOURCE_ARTIFACTS = [
    "contracts/runtime-contract.json",
    "contracts/public-contract.json",
    "metrics/metrics.json",
    "predictions/bundle.json",
    "model-card.json",
    "public-context.json",
    "manifest-input.json",
]

_CANDIDATE_STAGING_PREFIX = "releases/candidates"


def _load_source_input(path: str) -> tuple:
    """Load and parse the source-contract-input JSON. Returns (data, error_message)."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f), None
    except FileNotFoundError:
        return None, f"file not found: {path}"
    except json.JSONDecodeError as exc:
        return None, f"not valid JSON: {exc}"


def _rejection(phase: str, reason: str, **extra) -> dict:
    return {"status": "rejected", "reason": reason, "rejection_phase": phase, **extra}


def _acceptance(dataset_slug: str, release_id: str, candidate_dir: Path, validation: dict) -> dict:
    return {
        "status": "accepted",
        "dataset_slug": dataset_slug,
        "release_id": release_id,
        "candidate_dir": str(candidate_dir),
        "publisher_validation": {
            "valid": validation.get("valid"),
            "role_results": validation.get("role_results"),
            "identifier_consistency": validation.get("identifier_consistency"),
            "schema_compatibility": validation.get("schema_compatibility"),
        },
    }


def _build_release_candidate(
    dataset_slug: str, release_id: str, release_version: str | None
) -> dict:
    """Build release-candidate.json conforming to publisher/release-candidate.schema.json."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema_version": "release-candidate.v1",
        "candidate_kind": "release_candidate",
        "dataset_identity": {
            "dataset_slug": dataset_slug,
            "dataset_title": dataset_slug.replace("-", " ").title(),
        },
        "release_identity": {
            "release_id": release_id,
            "release_version": release_version or "1.0.0-rc.1",
            "created_at": now,
        },
        "source_run": {
            "run_id": f"m13-04-assembly-{release_id}",
            "producer": "pipeline/assemble_candidate.py",
            "created_at": now,
        },
        "artifact_roles": {
            "contracts": {
                "role": "contracts",
                "path": "contracts/runtime-contract.json",
                "required": True,
                "media_type": "application/json",
            },
            "predictive_bundle": {
                "role": "predictive_bundle",
                "path": "predictions/bundle.json",
                "required": True,
                "media_type": "application/json",
            },
            "metrics": {
                "role": "metrics",
                "path": "metrics/metrics.json",
                "required": True,
                "media_type": "application/json",
            },
            "model_card": {
                "role": "model_card",
                "path": "model-card.json",
                "required": True,
                "media_type": "application/json",
            },
            "public_context": {
                "role": "public_context",
                "path": "public-context.json",
                "required": True,
                "media_type": "application/json",
            },
            "manifest_input": {
                "role": "manifest_input",
                "path": "manifest-input.json",
                "required": True,
                "media_type": "application/json",
            },
            "candidate_metadata": {
                "role": "candidate_metadata",
                "path": "release-candidate.json",
                "required": True,
                "media_type": "application/json",
            },
        },
        "candidate_metadata": {
            "assembled_by": "pipeline/assemble_candidate.py",
            "assembled_at": now,
            "intended_publisher_action": "validate_candidate",
            "completeness_validation": {
                "required_artifact_roles": [
                    "contracts",
                    "predictive_bundle",
                    "metrics",
                    "model_card",
                    "public_context",
                    "manifest_input",
                    "candidate_metadata",
                ],
                "hash_policy": "publisher_calculates_hashes",
                "manifest_policy": "publisher_generates_manifest",
            },
        },
        "state_boundaries": {
            "pipeline_run_is_publishable": False,
            "candidate_is_published_release": False,
            "promotion_required": True,
            "registry_update_allowed_in_candidate": False,
            "public_upload_required": False,
            "web_administration_required": False,
            "database_publication_management_required": False,
            "runtime_consumes_temporary_pipeline_output": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assemble a publisher-compatible candidate from build outputs."
    )
    parser.add_argument(
        "source_input",
        help="Path to the source-contract-input JSON file",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Candidate staging base directory (e.g. releases/candidates/)",
    )
    parser.add_argument(
        "--source-dir",
        required=True,
        help="Pre-staged artifacts source directory",
    )
    parser.add_argument(
        "--release-version",
        default=None,
        help="Release version string (optional)",
    )
    args = parser.parse_args()

    # Step 1: Load source-contract-input JSON; extract dataset_slug and release_id.
    source_data, load_err = _load_source_input(args.source_input)
    if load_err:
        phase = "source_input_read" if "not found" in load_err else "source_input_parse"
        print(json.dumps(_rejection(
            phase, load_err,
            dataset_slug=None, release_id=None, candidate_dir=None,
        ), indent=2))
        return 1

    dataset_slug = source_data.get("dataset_slug")
    release_id = source_data.get("release_id")
    if not dataset_slug or not release_id:
        print(json.dumps(_rejection(
            "source_input_parse",
            "source-contract-input JSON must contain 'dataset_slug' and 'release_id'",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=None,
        ), indent=2))
        return 1

    # Step 2: Construct candidate_dir and assert it is under releases/candidates/.
    candidate_dir = (Path(args.output_dir) / dataset_slug / release_id).resolve()
    staging_prefix = Path(_CANDIDATE_STAGING_PREFIX).resolve()
    if not candidate_dir.is_relative_to(staging_prefix):
        print(json.dumps(_rejection(
            "staging_path_violation",
            f"candidate_dir must be under {_CANDIDATE_STAGING_PREFIX}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
        ), indent=2))
        return 1

    # Step 3: Assert --source-dir is a valid directory.
    source_dir = Path(args.source_dir)
    if not source_dir.is_dir():
        print(json.dumps(_rejection(
            "source_dir_invalid",
            f"--source-dir does not exist or is not a directory: {args.source_dir}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
        ), indent=2))
        return 1

    # Step 4: Verify all required source artifacts are present.
    missing = [p for p in _REQUIRED_SOURCE_ARTIFACTS if not (source_dir / p).is_file()]
    if missing:
        print(json.dumps(_rejection(
            "source_artifact_missing",
            f"required source artifacts missing from --source-dir: {missing}",
            dataset_slug=dataset_slug,
            release_id=release_id,
            candidate_dir=str(candidate_dir),
            missing_paths=missing,
        ), indent=2))
        return 1

    # Step 5: Create candidate_dir and necessary subdirectories.
    candidate_dir.mkdir(parents=True, exist_ok=True)

    # Step 6: Copy each required source artifact to the candidate directory.
    for rel_path in _REQUIRED_SOURCE_ARTIFACTS:
        dst = candidate_dir / rel_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_dir / rel_path, dst)

    # Step 7: Write release-candidate.json (publisher/release-candidate.schema.json).
    release_candidate = _build_release_candidate(dataset_slug, release_id, args.release_version)
    (candidate_dir / "release-candidate.json").write_text(
        json.dumps(release_candidate, indent=2), encoding="utf-8"
    )

    # Step 8: Invoke publisher.validate.validate_candidate_file() via Python import.
    sys.path.insert(0, str(_REPO_ROOT))
    from publisher import validate  # noqa: PLC0415
    result = validate.validate_candidate_file(candidate_dir)

    # Step 9: Write reduced build-evidence.json (pipeline-internal; NOT in artifact_roles).
    from pipeline import evidence  # noqa: PLC0415
    assembled = _REQUIRED_SOURCE_ARTIFACTS + ["release-candidate.json"]
    build_evidence = evidence.build_build_evidence(
        dataset_slug,
        release_id,
        args.source_input,
        result,
        assembled,
    )
    evidence.write_build_evidence(candidate_dir, build_evidence, _REPO_ROOT)

    # Steps 10-11: Emit result JSON and exit.
    if result.get("valid"):
        print(json.dumps(_acceptance(dataset_slug, release_id, candidate_dir, result), indent=2))
        return 0

    print(json.dumps(_rejection(
        "publisher_validation",
        "publisher validation rejected the assembled candidate",
        dataset_slug=dataset_slug,
        release_id=release_id,
        candidate_dir=str(candidate_dir),
        publisher_validation=result,
    ), indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())

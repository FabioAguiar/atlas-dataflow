import json
import shutil
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pipeline import assemble_candidate  # noqa: E402
from publisher import validate  # noqa: E402


DATASET_SLUG = "telco-customer-churn"
RELEASE_ID = "release-20260620-001"
RELEASE_VERSION = "2026.06.20"


REQUIRED_SOURCE_ARTIFACTS = (
    "contracts/runtime-contract.json",
    "contracts/public-contract.json",
    "metrics/metrics.json",
    "predictions/bundle.json",
    "model-card.json",
    "public-context.json",
    "manifest-input.json",
)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _write_source_input(tmp_path: Path, **overrides) -> Path:
    data = {
        "schema_version": "source-contract-input.v1",
        "dataset_slug": DATASET_SLUG,
        "release_id": RELEASE_ID,
        "source_contract_ref": "contracts/runtime-contract.schema.json",
        "source_data_ref": "datasets/telco-customer-churn/v1",
    }
    data.update(overrides)

    source_input = tmp_path / "source-contract-input.json"
    _write_json(source_input, data)
    return source_input


def _write_source_artifacts(tmp_path: Path, *, missing: str | None = None) -> Path:
    source_dir = tmp_path / "source-artifacts"
    for relative in REQUIRED_SOURCE_ARTIFACTS:
        if relative == missing:
            continue
        _write_json(source_dir / relative, {"fixture": True, "path": relative})
    return source_dir


def _copy_publisher_operational_note(tmp_repo: Path) -> None:
    src = REPO_ROOT / "publisher" / "release-candidate.operational-note.json"
    dst = tmp_repo / "publisher" / "release-candidate.operational-note.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _assemble_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    source_input: Path | None = None,
    source_dir: Path | None = None,
) -> tuple[int, dict, Path]:
    tmp_repo = tmp_path / "repo"
    output_dir = tmp_repo / "releases" / "candidates"
    source_input = source_input or _write_source_input(tmp_path)
    source_dir = source_dir or _write_source_artifacts(tmp_path)
    schema_dst = tmp_repo / "pipeline" / "build-evidence.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pipeline" / "build-evidence.schema.json", schema_dst)

    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_repo)
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(source_input),
            "--output-dir",
            str(output_dir),
            "--source-dir",
            str(source_dir),
            "--release-version",
            RELEASE_VERSION,
        ],
    )

    exit_code = assemble_candidate.main()
    candidate_dir = output_dir / DATASET_SLUG / RELEASE_ID
    return exit_code, json.loads((candidate_dir / "release-candidate.json").read_text()), candidate_dir


def test_successful_build_creates_candidate_layout_and_required_artifacts(tmp_path, monkeypatch):
    exit_code, release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)

    assert exit_code == 0
    assert candidate_dir.is_dir()
    assert release_candidate["dataset_identity"]["dataset_slug"] == DATASET_SLUG
    assert release_candidate["release_identity"]["release_id"] == RELEASE_ID
    assert release_candidate["release_identity"]["release_version"] == RELEASE_VERSION

    for relative in REQUIRED_SOURCE_ARTIFACTS:
        assert (candidate_dir / relative).is_file()

    assert (candidate_dir / "release-candidate.json").is_file()
    assert (candidate_dir / "build-evidence.json").is_file()
    assert "build-evidence.json" not in {
        role["path"] for role in release_candidate["artifact_roles"].values()
    }


def test_successful_build_writes_reduced_evidence_and_boundary_confirmations(tmp_path, monkeypatch):
    exit_code, _release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)

    assert exit_code == 0
    evidence = json.loads((candidate_dir / "build-evidence.json").read_text())
    assert evidence["schema_version"] == "build-evidence.v1"
    assert evidence["source_input"]["dataset_slug"] == DATASET_SLUG
    assert evidence["source_input"]["release_id"] == RELEASE_ID
    assert evidence["publisher_validation"] == {
        "valid": True,
        "validation_outcome": "accepted",
        "validated_at": evidence["publisher_validation"]["validated_at"],
    }
    assert evidence["build_boundary_confirmations"] == {
        "promotion_occurred": False,
        "registry_mutation_occurred": False,
    }
    assert evidence["evidence_policy"] == {
        "raw_logs_prohibited": True,
        "raw_runtime_prohibited": True,
        "raw_api_payloads_prohibited": True,
        "secrets_prohibited": True,
        "private_source_paths_prohibited": True,
        "reduced_and_sanitized": True,
    }
    assert "build-evidence.json" not in evidence["assembled_artifacts"]
    assert "role_results" not in evidence["publisher_validation"]
    assert "schema_compatibility" not in evidence["publisher_validation"]


def test_missing_source_artifact_rejects_without_publishable_candidate(tmp_path, monkeypatch, capsys):
    source_dir = _write_source_artifacts(
        tmp_path,
        missing="contracts/public-contract.json",
    )
    source_input = _write_source_input(tmp_path)

    output_dir = tmp_path / "repo" / "releases" / "candidates"
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(source_input),
            "--output-dir",
            str(output_dir),
            "--source-dir",
            str(source_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "source_artifact_missing"
    assert "contracts/public-contract.json" in result["missing_paths"]
    assert not (output_dir / DATASET_SLUG / RELEASE_ID / "release-candidate.json").exists()


def test_missing_required_source_input_field_rejects_before_candidate_creation(
    tmp_path,
    monkeypatch,
    capsys,
):
    source_input = _write_source_input(tmp_path)
    data = json.loads(source_input.read_text())
    del data["release_id"]
    source_input.write_text(json.dumps(data, indent=2), encoding="utf-8")

    source_dir = _write_source_artifacts(tmp_path)
    output_dir = tmp_path / "repo" / "releases" / "candidates"
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(source_input),
            "--output-dir",
            str(output_dir),
            "--source-dir",
            str(source_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "source_input_parse"
    assert result["release_id"] is None
    assert not output_dir.exists()


def test_invalid_public_projection_rejects_in_publisher_validation(tmp_path, monkeypatch, capsys):
    source_dir = _write_source_artifacts(tmp_path)
    (source_dir / "model-card.json").write_text("not json", encoding="utf-8")
    source_input = _write_source_input(tmp_path)

    output_dir = tmp_path / "repo" / "releases" / "candidates"
    schema_dst = tmp_path / "repo" / "pipeline" / "build-evidence.schema.json"
    schema_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(REPO_ROOT / "pipeline" / "build-evidence.schema.json", schema_dst)
    monkeypatch.setattr(assemble_candidate, "_REPO_ROOT", tmp_path / "repo")
    monkeypatch.setattr(assemble_candidate, "_CANDIDATE_STAGING_PREFIX", output_dir)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "assemble_candidate.py",
            str(source_input),
            "--output-dir",
            str(output_dir),
            "--source-dir",
            str(source_dir),
        ],
    )

    assert assemble_candidate.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "rejected"
    assert result["rejection_phase"] == "publisher_validation"
    rejection_codes = {
        reason["code"]
        for reason in result["publisher_validation"]["rejection_reasons"]
    }
    assert "model_card_schema_incompatible" in rejection_codes


def test_assembled_candidate_is_publisher_validation_compatible_without_promotion(
    tmp_path,
    monkeypatch,
):
    exit_code, _release_candidate, candidate_dir = _assemble_candidate(tmp_path, monkeypatch)
    assert exit_code == 0

    tmp_repo = tmp_path / "repo"
    _copy_publisher_operational_note(tmp_repo)
    validation_result = validate.run(str(candidate_dir), repo_root=tmp_repo)

    assert validation_result["validation_outcome"] == "accepted"
    assert validation_result["promotion_gate"] == {
        "promotion_allowed": True,
        "registry_update_allowed": True,
    }
    assert validation_result["publisher_boundaries"]["release_promoted"] is False
    assert validation_result["publisher_boundaries"]["registry_updated"] is False
    assert (tmp_repo / "publisher" / "runs").is_dir()
    assert not (tmp_repo / "releases" / RELEASE_ID).exists()
    assert not (tmp_repo / "registry" / "datasets.json").exists()

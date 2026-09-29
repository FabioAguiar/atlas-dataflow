"""
Registry backups under a non-root API process.

The API runs as uid 10001 against bind-mounted registry files owned by the
host user or root, with write access granted only by ACL. Backups must
therefore preserve content, never Unix metadata: shutil.copy2()/copystat()
raise EPERM on a destination the process does not own even though the
content write succeeds. These tests prove the backup path never depends on
metadata copy, and that every failing stage of registry update and dataset
removal restores the primary files (and their backups) byte-for-byte.

Run from the repository root:
    python -m pytest tests/registry/test_registry_nonroot_backup.py -v
"""

import ast
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

import registry.update as registry_update  # noqa: E402
from registry.file_backup import backup_file_contents  # noqa: E402
from registry.update import remove_dataset_entry, run as registry_update_run  # noqa: E402

_VIEW = {
    "schema_version": "1.0.0",
    "view_id": "churn-risk-overview",
    "dataset_slug": "telco-customer-churn",
    "display": {"title": "Churn Risk Overview", "summary": "Estimate churn."},
    "intent": {"prediction_goal": "Estimate churn.", "audience": "Public visitors."},
    "binding": {"dataset_slug": "telco-customer-churn", "release": {"mode": "active"}},
    "contract_precedence": {
        "canonical_contracts_are_source_of_truth": True,
        "view_metadata_defines_runtime_validation": False,
        "view_metadata_duplicates_contract": False,
    },
}

PRIOR_REGISTRY_BACKUP = b'{"prior": "registry backup owned by host uid 1002"}'
PRIOR_PREDICT_VIEWS_BACKUP = b'{"prior": "predict-views backup owned by root"}'


def _fail_metadata_copy(*_args, **_kwargs):
    raise PermissionError(1, "Operation not permitted")


@pytest.fixture
def no_metadata_copy(monkeypatch):
    """Make every metadata-preserving copy fail as it does for uid 10001."""
    monkeypatch.setattr(shutil, "copy2", _fail_metadata_copy)
    monkeypatch.setattr(shutil, "copystat", _fail_metadata_copy)
    monkeypatch.setattr(shutil, "copymode", _fail_metadata_copy)


def _dataset_entry(slug: str, release_id: str) -> dict:
    return {
        "dataset_slug": slug,
        "active_release": release_id,
        "public_metadata": {
            "title": slug, "summary": "s", "domain": "general", "visibility": "public", "tags": [],
        },
    }


def _write_repo(repo_root: Path, *, with_backups: bool) -> Path:
    """Registry with a telco view whose promotion removes it (forces a predict-views rewrite)."""
    registry_dir = repo_root / "registry"
    registry_dir.mkdir(parents=True)
    (registry_dir / "datasets.json").write_text(json.dumps({
        "schema_version": "atlas.dataflow.registry.v1",
        "datasets": [
            _dataset_entry("other-dataset", "release-20260101-001"),
            _dataset_entry("telco-customer-churn", "release-20260101-999"),
        ],
    }), encoding="utf-8")
    (registry_dir / "predict-views.json").write_text(json.dumps({
        "schema_version": "atlas.dataflow.predict-views.v1",
        "predict_views": [_VIEW],
    }), encoding="utf-8")
    (registry_dir / "predict-view-customizations.json").write_text(json.dumps({
        "schema_version": "atlas.dataflow.predict-view-customizations.v1",
        "predict_view_customizations": [],
    }), encoding="utf-8")
    if with_backups:
        (registry_dir / "datasets.json.previous").write_bytes(PRIOR_REGISTRY_BACKUP)
        (registry_dir / "predict-views.json.previous").write_bytes(PRIOR_PREDICT_VIEWS_BACKUP)

    release_dir = repo_root / "releases" / "release-20260102-005"
    release_dir.mkdir(parents=True)
    (release_dir / "public-context.json").write_text(json.dumps({
        "schema_version": "1.0.0",
        "dataset_slug": "telco-customer-churn",
        "title": "T",
        "description": "D",
        "domain": "general",
        "predict_views": [],
    }), encoding="utf-8")
    (release_dir / "manifest.json").write_text(json.dumps({"artifacts": []}), encoding="utf-8")

    run_dir = repo_root / "publisher" / "runs" / "run-nonroot"
    run_dir.mkdir(parents=True)
    (run_dir / "promotion-result.json").write_text(json.dumps({
        "promotion_outcome": "promoted",
        "candidate_identity": {"dataset_slug": "telco-customer-churn", "release_id": "release-20260102-005"},
    }), encoding="utf-8")
    return run_dir


def _registry_files(repo_root: Path) -> dict[str, bytes | None]:
    registry_dir = repo_root / "registry"
    names = ("datasets.json", "datasets.json.previous", "predict-views.json", "predict-views.json.previous")
    return {
        name: (registry_dir / name).read_bytes() if (registry_dir / name).is_file() else None
        for name in names
    }


# ---------------------------------------------------------------------------
# backup_file_contents()
# ---------------------------------------------------------------------------

def test_backup_creates_missing_destination_with_identical_bytes(tmp_path, no_metadata_copy):
    source = tmp_path / "datasets.json"
    source.write_bytes(b'{"datasets": []}\n\x00\xff')
    destination = tmp_path / "datasets.json.previous"

    backup_file_contents(source, destination)

    assert destination.read_bytes() == source.read_bytes()


def test_backup_overwrites_existing_destination_with_identical_bytes(tmp_path, no_metadata_copy):
    source = tmp_path / "datasets.json"
    source.write_bytes(b"short")
    destination = tmp_path / "datasets.json.previous"
    destination.write_bytes(b"a much longer previous backup that must be fully replaced")

    backup_file_contents(source, destination)

    assert destination.read_bytes() == b"short"


def test_backup_does_not_copy_mode_or_timestamps(tmp_path):
    source = tmp_path / "datasets.json"
    source.write_bytes(b"content")
    os.chmod(source, 0o600)
    os.utime(source, (1_000_000_000, 1_000_000_000))
    destination = tmp_path / "datasets.json.previous"
    destination.write_bytes(b"old")
    os.chmod(destination, 0o664)

    backup_file_contents(source, destination)

    stat = destination.stat()
    assert stat.st_mode & 0o777 == 0o664
    assert stat.st_mtime != 1_000_000_000
    assert destination.read_bytes() == b"content"


def test_backup_rejects_symlinked_destination(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "target.json"
    target.write_bytes(b"untouched")
    registry_dir = tmp_path / "registry"
    registry_dir.mkdir()
    source = registry_dir / "datasets.json"
    source.write_bytes(b"content")
    destination = registry_dir / "datasets.json.previous"
    destination.symlink_to(target)

    with pytest.raises(OSError):
        backup_file_contents(source, destination)
    assert target.read_bytes() == b"untouched"


def test_backup_rejects_destination_outside_source_directory(tmp_path):
    (tmp_path / "registry").mkdir()
    source = tmp_path / "registry" / "datasets.json"
    source.write_bytes(b"content")

    with pytest.raises(OSError):
        backup_file_contents(source, tmp_path / "registry" / ".." / "datasets.json.previous")
    assert not (tmp_path / "datasets.json.previous").exists()


def test_backup_propagates_os_error(tmp_path):
    source = tmp_path / "datasets.json"

    with pytest.raises(OSError):
        backup_file_contents(source, tmp_path / "datasets.json.previous")


def test_registry_modules_do_not_use_metadata_preserving_copy():
    offenders = []
    for path in sorted((REPO_ROOT / "registry").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"copy2", "copystat", "copymode", "copy"}:
                if isinstance(node.value, ast.Name) and node.value.id == "shutil":
                    offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == []


# ---------------------------------------------------------------------------
# registry.update.run()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("with_backups", [True, False])
def test_run_succeeds_without_metadata_copy(tmp_path, no_metadata_copy, with_backups):
    run_dir = _write_repo(tmp_path, with_backups=with_backups)
    before = _registry_files(tmp_path)

    result = registry_update_run(str(run_dir), repo_root=tmp_path)

    after = _registry_files(tmp_path)
    assert result["update_applied"] is True
    assert result["predict_view_materialization"]["action"] == "removed"
    assert after["datasets.json.previous"] == before["datasets.json"]
    assert after["predict-views.json.previous"] == before["predict-views.json"]
    registry = json.loads(after["datasets.json"])
    telco = next(e for e in registry["datasets"] if e["dataset_slug"] == "telco-customer-churn")
    assert telco["active_release"] == "release-20260102-005"
    assert json.loads(after["predict-views.json"])["predict_views"] == []


_STAGES = {
    "A_registry_backup": ("backup", "datasets.json.previous"),
    "B_registry_write": ("write", "datasets.json"),
    "C_predict_views_backup": ("backup", "predict-views.json.previous"),
    "D_predict_views_write": ("write", "predict-views.json"),
}


def _install_stage_failure(monkeypatch, stage: str) -> None:
    """Fail one stage after a partial write, as copy2 did (bytes written, then EPERM)."""
    kind, failing_name = _STAGES[stage]

    if kind == "backup":
        real_backup = registry_update.backup_file_contents

        def failing_backup(source, destination):
            if Path(destination).name == failing_name:
                Path(destination).write_bytes(b'{"partial')
                raise PermissionError(1, "Operation not permitted")
            real_backup(source, destination)

        monkeypatch.setattr(registry_update, "backup_file_contents", failing_backup)
    else:
        real_write_text = Path.write_text

        def failing_write_text(self, data, *args, **kwargs):
            if self.name == failing_name and self.parent.name == "registry":
                real_write_text(self, data[:7], *args, **kwargs)
                raise OSError(28, "No space left on device")
            return real_write_text(self, data, *args, **kwargs)

        monkeypatch.setattr(Path, "write_text", failing_write_text)


@pytest.mark.parametrize("with_backups", [True, False])
@pytest.mark.parametrize("stage", sorted(_STAGES))
def test_run_failure_at_any_stage_restores_exact_bytes(tmp_path, monkeypatch, stage, with_backups):
    run_dir = _write_repo(tmp_path, with_backups=with_backups)
    before = _registry_files(tmp_path)
    _install_stage_failure(monkeypatch, stage)

    with pytest.raises(RuntimeError, match="could not be written"):
        registry_update_run(str(run_dir), repo_root=tmp_path)

    assert _registry_files(tmp_path) == before


# ---------------------------------------------------------------------------
# registry.update.remove_dataset_entry()
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("with_backups", [True, False])
def test_remove_succeeds_without_metadata_copy(tmp_path, no_metadata_copy, with_backups):
    _write_repo(tmp_path, with_backups=with_backups)
    before = _registry_files(tmp_path)

    result = remove_dataset_entry("other-dataset", repo_root=tmp_path)

    after = _registry_files(tmp_path)
    assert result["removed"] is True
    assert result["errors"] == []
    assert after["datasets.json.previous"] == before["datasets.json"]
    slugs = {e["dataset_slug"] for e in json.loads(after["datasets.json"])["datasets"]}
    assert slugs == {"telco-customer-churn"}
    assert after["predict-views.json"] == before["predict-views.json"]
    assert after["predict-views.json.previous"] == before["predict-views.json.previous"]


@pytest.mark.parametrize("with_backups", [True, False])
@pytest.mark.parametrize("stage", ["A_registry_backup", "B_registry_write"])
def test_remove_failure_restores_exact_bytes(tmp_path, monkeypatch, stage, with_backups):
    _write_repo(tmp_path, with_backups=with_backups)
    before = _registry_files(tmp_path)
    _install_stage_failure(monkeypatch, stage)

    result = remove_dataset_entry("other-dataset", repo_root=tmp_path)

    assert result["removed"] is False
    assert result["errors"] == [registry_update.REGISTRY_WRITE_FAILED_ERROR]
    assert _registry_files(tmp_path) == before

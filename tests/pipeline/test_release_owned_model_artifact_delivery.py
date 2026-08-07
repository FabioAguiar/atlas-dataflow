import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pipeline.assemble_candidate import deliver_model_artifact


def _delivery(payload: bytes, destination: str = "models/classifier.bin") -> dict:
    return {
        "role": "model_artifact",
        "artifact_id": "classifier-v1",
        "artifact_format": "opaque-binary",
        "loader_family": "governed-loader",
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "destination_path": destination,
        "inference_bundle_id": "bundle-v1",
        "provenance": {"source_reference": "training-run-v1", "source_revision": "rev-1"},
    }


def test_delivers_exact_opaque_bytes_with_release_relative_lineage(tmp_path: Path) -> None:
    payload = b"not-a-pickle\x00opaque-model\xff"
    source = tmp_path / "source.bin"
    source.write_bytes(payload)
    candidate = tmp_path / "candidate"

    metadata = deliver_model_artifact(_delivery(payload), source, candidate)

    delivered = candidate / metadata["path"]
    assert delivered.read_bytes() == payload
    assert metadata["sha256"] == hashlib.sha256(payload).hexdigest()
    assert metadata["inference_bundle_id"] == "bundle-v1"
    assert delivered.resolve().is_relative_to(candidate.resolve())


def test_rejects_missing_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing regular file"):
        deliver_model_artifact(_delivery(b"x"), tmp_path / "missing", tmp_path / "candidate")


def test_rejects_source_hash_mismatch_before_copy(tmp_path: Path) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"actual")
    with pytest.raises(ValueError, match="source SHA-256"):
        deliver_model_artifact(_delivery(b"expected"), source, tmp_path / "candidate")
    assert not (tmp_path / "candidate").exists()


@pytest.mark.parametrize(
    "destination",
    ["/absolute/model.bin", "../model.bin", "models/../../model.bin", "C:\\model.bin"],
)
def test_rejects_unsafe_destination(tmp_path: Path, destination: str) -> None:
    source = tmp_path / "source.bin"
    source.write_bytes(b"model")
    with pytest.raises(ValueError, match="release-relative|escapes"):
        deliver_model_artifact(_delivery(b"model", destination), source, tmp_path / "candidate")


def test_rejects_non_regular_source_directory(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    with pytest.raises(ValueError, match="regular file"):
        deliver_model_artifact(_delivery(b"model"), source, tmp_path / "candidate")

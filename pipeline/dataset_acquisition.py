"""
Generic Atlas-owned Rdatasets source acquisition helper (Project Spec S0254).

This module is dataset-agnostic: it must never branch on a specific dataset
slug, encode Nottingham-specific period logic, or contain forecasting,
training, or publisher logic. It owns exactly one responsibility --
materializing (or safely reusing) a normalized local CSV copy of a named
Rdatasets dataset inside the Atlas repository, over the Python standard
library's HTTPS client, with no third-party network dependency.

Boundaries enforced by this module:
- Callers supply a dataset/package identity (`<package>::<dataset_name>`),
  never a raw URL or filesystem path.
- The canonical Rdatasets raw CSV endpoint is owned exclusively here.
- The destination is always resolved and bound inside the Atlas repository
  root; destinations that escape the repository root are rejected.
- A valid existing destination file is reused without any network call and
  is never rewritten. An invalid existing destination fails closed and is
  never silently overwritten.
- A missing destination is fetched, validated, and written atomically; any
  fetch/parse/validation failure leaves no partial destination file.
- Returned/raised information is reduced: no credentials, tokens, raw HTTP
  headers, raw response bodies, or absolute filesystem paths.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Sequence


_RDATASETS_CSV_BASE_URL = (
    "https://raw.githubusercontent.com/vincentarelbundock/Rdatasets/master/csv"
)
_DEFAULT_TIMEOUT_SECONDS = 30
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.]*$")


class DatasetAcquisitionError(RuntimeError):
    """Raised when Rdatasets source acquisition or local reuse validation fails.

    The message identifies the failing acquisition stage (identity
    validation, destination resolution, existing-file reuse validation,
    network fetch, decode/parse, schema/row-count validation, or
    materialization) without embedding secrets, raw HTTP bodies, or absolute
    external-study/user filesystem paths.
    """


def _validate_identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DatasetAcquisitionError(
            f"{field_name} must be a non-empty string identifier."
        )
    if not _IDENTIFIER_PATTERN.match(value) or ".." in value:
        raise DatasetAcquisitionError(
            f"{field_name} must be a simple identifier (letters, digits, '_', "
            f"'.'); path-like, traversal, or URL-like values are rejected."
        )
    return value


def _resolve_repository_bound_destination(
    destination_relative_path: str | Path, repo_root: Path
) -> Path:
    relative = Path(destination_relative_path)
    if relative.is_absolute():
        raise DatasetAcquisitionError(
            "destination_relative_path must be repository-relative, not absolute."
        )
    root = repo_root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise DatasetAcquisitionError(
            "destination_relative_path resolves outside the Atlas repository root."
        ) from exc
    return candidate


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_local_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _validate_rows_shape(
    rows: list[dict[str, str]],
    expected_columns: list[str],
    expected_row_count: int,
) -> None:
    ordered_columns = list(rows[0].keys()) if rows else []
    if ordered_columns != expected_columns:
        raise DatasetAcquisitionError(
            "raw destination columns do not match the expected ordered columns."
        )
    if len(rows) != expected_row_count:
        raise DatasetAcquisitionError(
            "raw destination row count does not match the expected row count."
        )


def _write_normalized_csv_atomic(
    destination: Path, ordered_columns: list[str], rows: list[dict[str, str]]
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(destination.parent), prefix=f".{destination.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(ordered_columns)
            for row in rows:
                writer.writerow([row[column] for column in ordered_columns])
        tmp_path.replace(destination)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _fetch_rdataset_csv_bytes(
    dataset_name: str, package: str, timeout_seconds: int
) -> bytes:
    url = f"{_RDATASETS_CSV_BASE_URL}/{package}/{dataset_name}.csv"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if status != 200:
                raise DatasetAcquisitionError(
                    f"Rdatasets source responded with unexpected HTTP status {status}."
                )
            return response.read()
    except DatasetAcquisitionError:
        raise
    except urllib.error.HTTPError as exc:
        raise DatasetAcquisitionError(
            f"Rdatasets source responded with HTTP error status {exc.code}."
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise DatasetAcquisitionError(
            "Rdatasets source fetch failed due to a network/transport error."
        ) from exc


def _parse_rdatasets_csv(
    raw_bytes: bytes,
    expected_columns: list[str],
    expected_row_count: int,
) -> tuple[list[str], list[dict[str, str]]]:
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DatasetAcquisitionError(
            "Rdatasets source response is not valid UTF-8."
        ) from exc

    reader = csv.DictReader(io.StringIO(text))
    fieldnames = reader.fieldnames
    if not fieldnames or len(fieldnames) < 2:
        raise DatasetAcquisitionError(
            "Rdatasets source response has an unexpected column shape."
        )

    data_columns = list(fieldnames[1:])
    if data_columns != expected_columns:
        raise DatasetAcquisitionError(
            "Rdatasets source columns do not match the expected ordered columns."
        )

    rows: list[dict[str, str]] = []
    for record in reader:
        row: dict[str, str] = {}
        for column in data_columns:
            value = record.get(column)
            if value is None:
                raise DatasetAcquisitionError(
                    "Rdatasets source row has an unexpected/missing column shape."
                )
            row[column] = value
        rows.append(row)

    if len(rows) != expected_row_count:
        raise DatasetAcquisitionError(
            "Rdatasets source row count does not match the expected row count."
        )

    return data_columns, rows


def acquire_rdataset_csv(
    *,
    dataset_name: str,
    package: str,
    destination_relative_path: str,
    expected_columns: Sequence[str],
    expected_row_count: int,
    repo_root: str | Path | None = None,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Materialize or reuse a normalized Rdatasets CSV inside the Atlas repository.

    Parameters
    ----------
    dataset_name, package:
        Rdatasets dataset/package identity. Validated as simple identifiers;
        path-like, traversal, or URL-like values are rejected.
    destination_relative_path:
        Repository-relative destination, resolved and bound inside
        `repo_root`; destinations escaping the repository root are rejected.
    expected_columns:
        Ordered data columns required after the Rdatasets transport/index
        column (the CSV's first column) is stripped.
    expected_row_count:
        Exact row count required of the normalized data.
    repo_root:
        Atlas repository root. Defaults to `pipeline.discovery_evidence
        .resolve_repository_root()` when not supplied.
    timeout_seconds:
        HTTPS request timeout used only when the destination is missing.

    Returns a reduced acquisition-evidence dict:
    `source_kind`, `source_reference` (`package::dataset_name`), `provider`,
    `materialization_status` (`materialized` | `reused`), `relative_path`,
    `sha256`, `row_count`, `ordered_columns`.

    Raises `DatasetAcquisitionError` for identity/destination validation,
    existing-file reuse validation, network, decode/parse, schema, or
    row-count failures. A raised error never leaves a partial/corrupt
    destination file behind.
    """
    _validate_identifier(dataset_name, "dataset_name")
    _validate_identifier(package, "package")

    if repo_root is None:
        from pipeline.discovery_evidence import resolve_repository_root

        repo_root = resolve_repository_root()
    repo_root = Path(repo_root)

    destination = _resolve_repository_bound_destination(
        destination_relative_path, repo_root
    )
    expected_columns_list = list(expected_columns)
    relative_path = destination.relative_to(repo_root.resolve()).as_posix()
    source_reference = f"{package}::{dataset_name}"

    if destination.exists():
        try:
            existing_rows = _read_local_csv(destination)
        except (OSError, UnicodeDecodeError) as exc:
            raise DatasetAcquisitionError(
                "existing raw destination could not be read as a valid CSV file."
            ) from exc
        _validate_rows_shape(existing_rows, expected_columns_list, expected_row_count)
        return {
            "source_kind": "rdataset",
            "source_reference": source_reference,
            "provider": "rdatasets_https",
            "materialization_status": "reused",
            "relative_path": relative_path,
            "sha256": _sha256_bytes(destination.read_bytes()),
            "row_count": len(existing_rows),
            "ordered_columns": expected_columns_list,
        }

    raw_bytes = _fetch_rdataset_csv_bytes(dataset_name, package, timeout_seconds)
    ordered_columns, rows = _parse_rdatasets_csv(
        raw_bytes, expected_columns_list, expected_row_count
    )
    _write_normalized_csv_atomic(destination, ordered_columns, rows)
    return {
        "source_kind": "rdataset",
        "source_reference": source_reference,
        "provider": "rdatasets_https",
        "materialization_status": "materialized",
        "relative_path": relative_path,
        "sha256": _sha256_bytes(destination.read_bytes()),
        "row_count": len(rows),
        "ordered_columns": ordered_columns,
    }

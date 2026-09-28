"""Scientific-environment provenance and compatibility classification.

A Dataset Study pins its own interpreter and dependency lock. Atlas never
merges those locks into its own environment: the study lock is provenance and
a compatibility requirement. This module

* extracts the reproduction-relevant pins (interpreter plus the declared core
  numerical packages) from a PEP 751 ``pylock.toml`` at contract-authoring
  time, and
* classifies the environment an Atlas reproduction actually runs in against
  those pins.

Classification vocabulary (worst component wins):

``exact``         interpreter version, every core package version, and the
                  platform equal the scientific reference run.
``compatible``    no component crosses its declared compatibility boundary
                  (by default: same interpreter major.minor, same core package
                  major.minor), but at least one differs. Every difference is
                  listed; none is ignored.
``incompatible``  at least one component crosses its boundary or a core package
                  is missing from the runtime.
``unknown``       the contract carries no usable environment evidence.
"""

from __future__ import annotations

import hashlib
import platform
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Mapping, Sequence


EXACT = "exact"
COMPATIBLE = "compatible"
INCOMPATIBLE = "incompatible"
UNKNOWN = "unknown"

_SEVERITY = {EXACT: 0, COMPATIBLE: 1, UNKNOWN: 2, INCOMPATIBLE: 3}

# Boundaries a compatibility policy may declare per component.
BOUNDARY_EXACT = "exact"
BOUNDARY_SAME_MINOR = "same_minor"
BOUNDARY_SAME_MAJOR = "same_major"
_BOUNDARIES = (BOUNDARY_EXACT, BOUNDARY_SAME_MINOR, BOUNDARY_SAME_MAJOR)


class EnvironmentEvidenceError(ValueError):
    """Raised when lock evidence is missing or malformed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-").replace(".", "-")


def extract_core_pins_from_pylock(
    lock_path: Path, core_packages: Sequence[str]
) -> dict[str, str]:
    """Return ``{package: version}`` for the requested packages of a PEP 751 lock."""
    import tomllib

    lock = tomllib.loads(Path(lock_path).read_text(encoding="utf-8"))
    packages = lock.get("packages")
    if not isinstance(packages, list):
        raise EnvironmentEvidenceError(f"{lock_path} is not a PEP 751 lock (no [[packages]]).")
    versions: dict[str, set[str]] = {}
    for entry in packages:
        name = entry.get("name")
        version = entry.get("version")
        if isinstance(name, str) and isinstance(version, str):
            versions.setdefault(_normalize_name(name), set()).add(version)
    pins: dict[str, str] = {}
    for package in core_packages:
        found = versions.get(_normalize_name(package))
        if not found:
            raise EnvironmentEvidenceError(f"core package {package!r} is absent from {lock_path}.")
        if len(found) != 1:
            raise EnvironmentEvidenceError(
                f"core package {package!r} has several locked versions {sorted(found)}; "
                "a single reproduction pin cannot be derived."
            )
        pins[package] = next(iter(found))
    return pins


def capture_runtime_environment(core_packages: Sequence[str]) -> dict[str, Any]:
    """Describe the interpreter, platform, and core package versions in use."""
    packages: dict[str, str | None] = {}
    for package in core_packages:
        try:
            packages[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            packages[package] = None
    return {
        "python": platform.python_version(),
        "implementation": sys.implementation.name,
        "platform": f"{sys.platform}-{platform.machine().lower()}",
        "core_packages": packages,
    }


def _release_parts(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    for token in version.split("."):
        digits = ""
        for char in token:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts)


def _compare_versions(reference: str, observed: str | None, boundary: str) -> tuple[str, str]:
    if observed is None:
        return INCOMPATIBLE, "missing from the reproduction runtime"
    if observed == reference:
        return EXACT, "identical"
    ref, obs = _release_parts(reference), _release_parts(observed)
    width = {BOUNDARY_EXACT: None, BOUNDARY_SAME_MINOR: 2, BOUNDARY_SAME_MAJOR: 1}[boundary]
    if width is not None and len(ref) >= width and ref[:width] == obs[:width]:
        return COMPATIBLE, f"differs within the declared {boundary} boundary"
    return INCOMPATIBLE, f"crosses the declared {boundary} boundary"


def classify_environment(
    scientific_environment: Mapping[str, Any] | None,
    runtime: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify ``runtime`` against the contract's ``scientific_environment``."""
    if not scientific_environment or not scientific_environment.get("core_packages"):
        return {
            "classification": UNKNOWN,
            "components": [],
            "reason": "the study contract carries no core-package environment evidence",
        }
    policy = scientific_environment.get("compatibility_policy", {})
    python_boundary = policy.get("python", BOUNDARY_SAME_MINOR)
    package_boundary = policy.get("core_packages", BOUNDARY_SAME_MINOR)
    platform_policy = policy.get("platform", "difference_is_compatible")
    for boundary in (python_boundary, package_boundary):
        if boundary not in _BOUNDARIES:
            raise EnvironmentEvidenceError(f"unknown compatibility boundary {boundary!r}")

    components: list[dict[str, Any]] = []
    status, note = _compare_versions(
        str(scientific_environment["python"]), runtime.get("python"), python_boundary
    )
    components.append({
        "component": "python",
        "reference": scientific_environment["python"],
        "observed": runtime.get("python"),
        "boundary": python_boundary,
        "classification": status,
        "note": note,
    })
    observed_packages = runtime.get("core_packages", {})
    for package, reference in sorted(scientific_environment["core_packages"].items()):
        status, note = _compare_versions(reference, observed_packages.get(package), package_boundary)
        components.append({
            "component": package,
            "reference": reference,
            "observed": observed_packages.get(package),
            "boundary": package_boundary,
            "classification": status,
            "note": note,
        })
    reference_platform = scientific_environment.get("platform")
    if reference_platform:
        same = reference_platform == runtime.get("platform")
        if same:
            platform_status = EXACT
        elif platform_policy == "difference_is_incompatible":
            platform_status = INCOMPATIBLE
        else:
            platform_status = COMPATIBLE
        components.append({
            "component": "platform",
            "reference": reference_platform,
            "observed": runtime.get("platform"),
            "boundary": platform_policy,
            "classification": platform_status,
            "note": "identical" if same else "different CPU architecture or operating system",
        })
    overall = max((c["classification"] for c in components), key=_SEVERITY.__getitem__)
    return {
        "classification": overall,
        "components": components,
        "differences": [c["component"] for c in components if c["classification"] != EXACT],
        "lock_scope": (
            "Only the interpreter and the declared core packages are compared; the full study "
            "lock is provenance (identified by its SHA-256) and is never installed into or "
            "merged with the Atlas environment."
        ),
    }

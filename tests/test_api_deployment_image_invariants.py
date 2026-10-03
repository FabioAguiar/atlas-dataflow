"""Project Spec S0291: public/private API image and deployment invariant gate.

The private (``docker-compose.yml``) and public (``docker-compose.prod.yml``)
Compose modes must run the API from one canonical, repository-owned image
build and share one minimum container security envelope.

Offline, deterministic and read-only: both Compose files are parsed
structurally with ``yaml.safe_load``; no Docker daemon, network, running
deployment or secret-bearing environment file is involved.

Intentionally NOT asserted equal across the two modes: environment
variables, volume mounts, health checks, Admin enablement and the web
service configuration. Those differ by design between the private and
public deployments.

This gate locks source/build provenance only. It does not, and cannot,
prove that the running public and private API containers share the same
Docker image ID; that remains a separate read-only operational observation
against the actual running environment.
"""

import posixpath
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PUBLIC_COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"

_COMPOSE_MODES = {
    "private": PRIVATE_COMPOSE_PATH,
    "public": PUBLIC_COMPOSE_PATH,
}

EXPECTED_API_BUILD = {"context": ".", "dockerfile": "api/Dockerfile"}
EXPECTED_API_PORT = "8000"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _api_service(path: Path) -> dict:
    services = _load(path).get("services") or {}
    assert "api" in services, f"{path.name} has no api service"
    return services["api"]


def _normalize_build(build) -> dict:
    """Return a comparable build definition (short string form → mapping)."""
    if isinstance(build, str):
        build = {"context": build}
    assert isinstance(build, dict), f"unexpected api.build shape: {build!r}"
    normalized = dict(build)
    normalized["context"] = posixpath.normpath(str(normalized.get("context", ".")))
    if "dockerfile" in normalized:
        normalized["dockerfile"] = posixpath.normpath(str(normalized["dockerfile"]))
    return normalized


def _normalize_ports(values) -> list[str]:
    return sorted(str(value).strip() for value in (values or []))


@pytest.fixture(scope="module")
def api_services() -> dict:
    return {mode: _api_service(path) for mode, path in _COMPOSE_MODES.items()}


@pytest.mark.parametrize("mode", sorted(_COMPOSE_MODES))
def test_compose_mode_defines_an_api_service(mode):
    assert isinstance(_api_service(_COMPOSE_MODES[mode]), dict)


def test_public_and_private_api_build_definitions_are_identical(api_services):
    private_build = _normalize_build(api_services["private"].get("build"))
    public_build = _normalize_build(api_services["public"].get("build"))
    assert private_build == public_build


def test_shared_api_build_is_repository_root_with_api_dockerfile(api_services):
    for mode, service in api_services.items():
        assert _normalize_build(service.get("build")) == EXPECTED_API_BUILD, mode


def test_no_api_image_override_bypasses_the_canonical_build(api_services):
    for mode, service in api_services.items():
        assert "image" not in service, f"{mode} api declares image: {service['image']!r}"


def test_api_port_is_never_published_to_the_host(api_services):
    for mode, service in api_services.items():
        assert not service.get("ports"), f"{mode} api publishes ports"


def test_api_exposes_exactly_the_internal_port_8000(api_services):
    for mode, service in api_services.items():
        assert _normalize_ports(service.get("expose")) == [EXPECTED_API_PORT], mode


def test_api_root_filesystem_stays_read_only(api_services):
    for mode, service in api_services.items():
        assert service.get("read_only") is True, mode


def test_api_keeps_no_new_privileges(api_services):
    for mode, service in api_services.items():
        assert "no-new-privileges:true" in (service.get("security_opt") or []), mode


def test_api_drops_all_capabilities_and_adds_none(api_services):
    for mode, service in api_services.items():
        assert "ALL" in (service.get("cap_drop") or []), mode
        assert not service.get("cap_add"), f"{mode} api adds capabilities"


# Guard the normalization helpers so the gate cannot pass vacuously.


def test_build_normalization_detects_divergent_context_or_dockerfile():
    canonical = _normalize_build({"context": "./", "dockerfile": "./api/Dockerfile"})
    assert canonical == EXPECTED_API_BUILD
    assert _normalize_build({"context": "api", "dockerfile": "Dockerfile"}) != canonical
    assert _normalize_build({"context": ".", "dockerfile": "web/Dockerfile"}) != canonical
    assert _normalize_build(".") != canonical


def test_port_normalization_treats_yaml_int_and_string_alike():
    assert _normalize_ports([8000]) == _normalize_ports(["8000"]) == [EXPECTED_API_PORT]
    assert _normalize_ports(["8000", "9000"]) != [EXPECTED_API_PORT]
    assert _normalize_ports(None) != [EXPECTED_API_PORT]

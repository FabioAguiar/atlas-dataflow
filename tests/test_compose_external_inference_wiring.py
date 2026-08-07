"""S0161: proves the external-inference Compose wiring matches the
S0160/G0001 naming/wiring decision -- present in both files, no host-
published port, exposes 8100, has a healthcheck, no incoming depends_on from
api or web, bounded read-only model mount in private mode only, no such
mount in production, and .dockerignore admits the new build-context paths
without removing existing allowlist entries.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_external_inference_service_present_in_both_compose_files():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        services = _load(path)["services"]
        assert "external-inference" in services, f"external-inference missing from {path.name}"


def test_external_inference_has_no_ports_entry_in_either_file():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        service = _load(path)["services"]["external-inference"]
        assert "ports" not in service, f"{path.name} must not publish a host port for external-inference"


def test_external_inference_exposes_8100_in_both_files():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        service = _load(path)["services"]["external-inference"]
        assert service.get("expose") == ["8100"], path.name


def test_external_inference_has_a_healthcheck_in_both_files():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        service = _load(path)["services"]["external-inference"]
        assert "healthcheck" in service and service["healthcheck"].get("test"), path.name
        assert "/live" in " ".join(service["healthcheck"]["test"])


def test_neither_api_nor_web_depends_on_external_inference():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        services = _load(path)["services"]
        for service_name in ("api", "web"):
            depends_on = services[service_name].get("depends_on")
            if depends_on is None:
                continue
            names = depends_on.keys() if isinstance(depends_on, dict) else depends_on
            assert "external-inference" not in names, f"{path.name}:{service_name}"


def test_private_compose_mounts_the_bounded_read_only_external_models_root():
    service = _load(PRIVATE_COMPOSE_PATH)["services"]["external-inference"]
    volumes = service.get("volumes") or []
    assert "./external-models:/app/external-models:ro" in volumes


def test_production_compose_has_no_external_models_mount():
    service = _load(PROD_COMPOSE_PATH)["services"]["external-inference"]
    volumes = service.get("volumes") or []
    assert not any("external-models" in str(volume) for volume in volumes)


def test_external_inference_build_uses_the_repository_root_context_and_its_own_dockerfile():
    for path in (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH):
        build = _load(path)["services"]["external-inference"]["build"]
        assert build["context"] == "."
        assert build["dockerfile"] == "external-inference/Dockerfile"


def test_dockerignore_admits_external_inference_and_external_models_without_removing_existing_allowlist():
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    for expected_allow_entry in (
        "!external-inference/",
        "!external-inference/**",
        "!external-models/",
        "!external-models/**",
        "!api/",
        "!api/**",
        "!registry/",
        "!runtime/",
        "!releases/",
        "!publisher/",
    ):
        assert expected_allow_entry in text, expected_allow_entry

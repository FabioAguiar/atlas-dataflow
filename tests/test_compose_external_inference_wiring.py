"""Project Spec S0285: retirement regression for the external-inference
Compose/build wiring.

This file was originally an S0161 regression proving the isolated
external-inference service existed in both Compose files and in the
``.dockerignore`` build allowlist. S0285 retired that service, so the file
is kept -- with its historical name for regression lineage -- as a bounded
*negative* regression: it now proves the service is absent, no replacement
service or external model mount appeared, and the build context still
admits the paths the main API / release-owned model loading require.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
PRIVATE_COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
PROD_COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"
DOCKERIGNORE_PATH = REPO_ROOT / ".dockerignore"

_COMPOSE_PATHS = (PRIVATE_COMPOSE_PATH, PROD_COMPOSE_PATH)


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_external_inference_service_absent_from_both_compose_files():
    for path in _COMPOSE_PATHS:
        services = _load(path)["services"]
        assert "external-inference" not in services, f"external-inference still present in {path.name}"


def test_no_replacement_inference_service_appears_in_either_compose_file():
    # Exactly the two retained services -- no second inference/runtime
    # service was introduced under another name.
    for path in _COMPOSE_PATHS:
        services = _load(path)["services"]
        assert set(services) == {"api", "web"}, f"{path.name} services: {sorted(services)}"


def test_no_compose_service_exposes_or_publishes_the_retired_inference_port():
    for path in _COMPOSE_PATHS:
        for name, service in _load(path)["services"].items():
            assert "8100" not in [str(p) for p in (service.get("expose") or [])], f"{path.name}:{name}"
            assert not any("8100" in str(p) for p in (service.get("ports") or [])), f"{path.name}:{name}"


def test_neither_api_nor_web_gained_a_new_service_dependency():
    # api has no depends_on at all; web depends only on api.
    private_services = _load(PRIVATE_COMPOSE_PATH)["services"]
    assert "depends_on" not in private_services["api"]
    web_depends = private_services["web"].get("depends_on") or {}
    web_names = web_depends.keys() if isinstance(web_depends, dict) else web_depends
    assert set(web_names) == {"api"}

    prod_services = _load(PROD_COMPOSE_PATH)["services"]
    assert "depends_on" not in prod_services["api"]
    prod_web_depends = prod_services["web"].get("depends_on") or {}
    prod_web_names = prod_web_depends.keys() if isinstance(prod_web_depends, dict) else prod_web_depends
    assert set(prod_web_names) == {"api"}


def test_no_external_model_mount_or_external_inference_build_remains():
    for path in _COMPOSE_PATHS:
        raw = path.read_text(encoding="utf-8")
        assert "external-models" not in raw, path.name
        assert "external-inference/Dockerfile" not in raw, path.name


def test_dockerignore_no_longer_admits_the_external_inference_build_context():
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    assert "!external-inference/" not in text
    assert "!external-inference/**" not in text


def test_dockerignore_still_admits_the_api_and_release_build_context():
    # Release-owned model loading requires releases/ (and the API's own
    # supporting directories) to remain in the image build context.
    text = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    for expected_allow_entry in (
        "!api/",
        "!api/**",
        "!registry/",
        "!runtime/",
        "!releases/",
        "!releases/**",
        "!publisher/",
    ):
        assert expected_allow_entry in text, expected_allow_entry

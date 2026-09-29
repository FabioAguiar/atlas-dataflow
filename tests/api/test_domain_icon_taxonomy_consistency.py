"""The domain-icon taxonomy exists twice by layer isolation (the API image
never ships web/, and the web bundle never imports Python): the backend
fallback profile generator and the frontend Home card fallback. They must be
identical, and they classify domains -- never dataset identities."""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "api"))

import public_profile_fallback  # noqa: E402

FRONTEND_SOURCE = REPO_ROOT / "web" / "src" / "lib" / "datasetPresentation.ts"


def _frontend_domain_icon_rules() -> list[tuple[str, list[str]]]:
    source = FRONTEND_SOURCE.read_text(encoding="utf-8")
    block = source[source.index("const DOMAIN_ICON_RULES"):]
    block = block[: block.index("];") + 2]
    rules = []
    for icon, keywords in re.findall(r'\{\s*icon:\s*"([^"]+)",\s*keywords:\s*\[([^\]]*)\]\s*\}', block):
        rules.append((icon, re.findall(r'"([^"]+)"', keywords)))
    return rules


def test_backend_and_frontend_domain_icon_rules_are_identical():
    frontend = _frontend_domain_icon_rules()
    assert frontend, "could not parse DOMAIN_ICON_RULES from datasetPresentation.ts"
    backend = [(icon, list(keywords)) for icon, keywords in public_profile_fallback._DOMAIN_ICON_RULES]
    assert backend == frontend


def test_taxonomy_keywords_are_domains_not_dataset_identities():
    registry = json.loads((REPO_ROOT / "registry" / "datasets.json").read_text(encoding="utf-8"))
    slug_tokens = {
        token
        for entry in registry["datasets"]
        for token in entry["dataset_slug"].split("-")
    }
    for _icon, keywords in public_profile_fallback._DOMAIN_ICON_RULES:
        assert "telco" not in keywords
        for keyword in keywords:
            assert keyword not in {entry["dataset_slug"] for entry in registry["datasets"]}
    # Registry domains are domain words, e.g. telecommunications, not a
    # dataset abbreviation.
    domains = {entry["public_metadata"]["domain"] for entry in registry["datasets"]}
    assert "telco" not in domains
    assert slug_tokens  # registry is not empty


def test_real_telecommunications_domain_still_resolves_to_telecom_icon():
    assert public_profile_fallback._derive_icon("telecommunications", []) == "telecom"
    assert public_profile_fallback._derive_icon("telecom", []) == "telecom"
    assert public_profile_fallback._derive_icon("telco", []) == "generic"

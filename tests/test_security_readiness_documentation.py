"""Project Spec S0293: security readiness documentation convergence gate.

``docs/current-architecture-overview.md`` presents itself as the current
architecture snapshot. This gate keeps it converged with the operational
milestone cursor and with the M53 evidence boundary: it must name the active
and last completed milestones recorded in
``docs/project-status/milestone-state.json``, keep the private/Admin versus
public deployment boundary and the Supabase identity/gateway ownership,
reference the repository-owned operational runbooks, and describe M53
readiness as evidence-derived instead of declaring it.

Offline, deterministic and read-only: documents are parsed as text only.
Checks use normalized semantic anchors and bounded patterns rather than exact
prose, so the overview can be reworded without breaking the gate.

This gate does not, and cannot, prove that Atlas is secure or publicly ready;
that remains M53 evidence recorded against the real deployment.
"""

import json
import re
import unicodedata
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
OVERVIEW_PATH = REPO_ROOT / "docs" / "current-architecture-overview.md"
MILESTONE_STATE_PATH = REPO_ROOT / "docs" / "project-status" / "milestone-state.json"

ACTIVE_MILESTONE_ID = "M53"
LAST_COMPLETED_MILESTONE_ID = "M52"
STALE_MILESTONE_IDS = ("M48", "M49")

READINESS_OUTCOMES = ("ready", "ready_with_documented_reservations", "blocked")

REFERENCED_RUNBOOKS = (
    "docs/operations/disaster-recovery.md",
    "docs/operations/inference-gateway-operations.md",
    "docs/operations/admin-operator-provisioning.md",
)
DEPLOYMENT_INVARIANT_TEST = "tests/test_api_deployment_image_invariants.py"

# Line labels (normalized) that carry the operational milestone cursor.
_ACTIVE_LABEL = re.compile(r"milestone operacional ativo|active (?:operational )?milestone")
_LAST_COMPLETED_LABEL = re.compile(
    r"ultimo milestone concluido|last completed milestone"
)
_MILESTONE_ID = re.compile(r"\bm\d+\b")

# Affirmative, unconditional readiness/security claims (normalized text).
_UNCONDITIONAL_CLAIMS = {
    "atlas_secure": re.compile(
        r"\batlas (?:is|e|esta) (?:fully |totalmente |completamente )?(?:secure|seguro)\b"
    ),
    "production_ready": re.compile(
        r"\b(?:production is ready|ready for production|production[- ]ready"
        r"|pront[oa] para (?:producao|exposicao publica|abertura publica)"
        r"|producao (?:esta )?pronta)\b"
    ),
    "backup_restore_verified": re.compile(
        r"\b(?:backups?(?:/| and | e )restores?|backups?|restores?|restauracao)"
        r" (?:is |are |was |were |foi |foram |esta |estao )?"
        r"(?:verified|tested|validated|proven|verificad[oa]s?|testad[oa]s?"
        r"|validad[oa]s?|comprovad[oa]s?)\b"
    ),
    "m53_completed": re.compile(
        r"\bm53 (?:is |was |foi |esta )?(?:completed|complete|concluido|finalizado)\b"
    ),
}
# A sentence carrying one of these tokens is evidence-qualified or negated.
_QUALIFIERS = re.compile(
    r"\b(?:nao|not|never|nunca|nenhum|nenhuma|sem|without|pendente|pending"
    r"|evidencia|evidence|only if|somente se|apenas se)\b"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+|\n+")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    stripped = stripped.replace("`", "").replace("*", "")
    return re.sub(r"[ \t]+", " ", stripped).lower()


def _milestones_on_labeled_lines(text: str, label: re.Pattern) -> list[str]:
    found = []
    for line in _normalize(text).splitlines():
        if label.search(line):
            found.extend(_MILESTONE_ID.findall(line))
    return found


def _unconditional_claims(text: str) -> list[tuple[str, str]]:
    hits = []
    for sentence in _SENTENCE_SPLIT.split(_normalize(text)):
        if _QUALIFIERS.search(sentence):
            continue
        for name, pattern in _UNCONDITIONAL_CLAIMS.items():
            if pattern.search(sentence):
                hits.append((name, sentence.strip()[:160]))
    return hits


# Pre-S0299 current-state claims superseded by the infrastructure-governed
# resource-limit contract, executable image-parity invariants and the
# infrastructure-owned production proxy/TLS topology (normalized text).
_STALE_PRE_S0299_CLAIMS = {
    "resource_limits_undefined": re.compile(
        r"(?:cpu|memoria|memory|pid)[^.;\n]*(?:nenhum valor (?:esta )?definido|undefined|indefinid[oa]s?)"
        r"|\bno (?:cpu|memory|pid)\b[^.;\n]*\bdefined\b"
    ),
    "image_parity_unevidenced": re.compile(
        r"(?:identidade|igualdade|paridade|identity|equality|parity)[^.;\n]*imagens?[^.;\n]*"
        r"(?:nao (?:esta )?evidenciad[oa]|unevidenced|not evidenced)"
    ),
    "local_caddy_as_production": re.compile(
        r"caddyfile versionado usa tls intern|caddyfile[^.;\n]*(?:is|e) the (?:current )?(?:public )?production"
    ),
}


def _stale_pre_s0299_claims(text: str) -> list[tuple[str, str]]:
    hits = []
    for sentence in _SENTENCE_SPLIT.split(_normalize(text)):
        for name, pattern in _STALE_PRE_S0299_CLAIMS.items():
            if pattern.search(sentence):
                hits.append((name, sentence.strip()[:160]))
    return hits


def _stale_or_missing_cursor(text: str) -> list[str]:
    problems = []
    active = _milestones_on_labeled_lines(text, _ACTIVE_LABEL)
    completed = _milestones_on_labeled_lines(text, _LAST_COMPLETED_LABEL)
    if active != [ACTIVE_MILESTONE_ID.lower()]:
        problems.append(f"active milestone lines name {active!r}")
    if completed != [LAST_COMPLETED_MILESTONE_ID.lower()]:
        problems.append(f"last completed milestone lines name {completed!r}")
    return problems


@pytest.fixture(scope="module")
def overview() -> str:
    assert OVERVIEW_PATH.is_file(), f"missing {OVERVIEW_PATH.relative_to(REPO_ROOT)}"
    return OVERVIEW_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def normalized(overview: str) -> str:
    return _normalize(overview)


def test_overview_exists_and_is_non_empty(overview: str) -> None:
    assert overview.strip()


def test_expected_cursor_matches_milestone_state() -> None:
    state = json.loads(MILESTONE_STATE_PATH.read_text(encoding="utf-8"))
    assert state["current_milestone"]["id"] == ACTIVE_MILESTONE_ID
    assert state["current_milestone"]["status"] == "active"
    assert state["last_completed_milestone"]["id"] == LAST_COMPLETED_MILESTONE_ID


def test_overview_names_current_milestone_cursor(overview: str) -> None:
    assert _stale_or_missing_cursor(overview) == []


def test_overview_does_not_present_stale_milestone_as_current(overview: str) -> None:
    labeled = _milestones_on_labeled_lines(
        overview, _ACTIVE_LABEL
    ) + _milestones_on_labeled_lines(overview, _LAST_COMPLETED_LABEL)
    for stale in STALE_MILESTONE_IDS:
        assert stale.lower() not in labeled


def test_overview_drops_obsolete_dated_snapshot_framing(normalized: str) -> None:
    assert "31 de agosto de 2026" not in normalized
    assert "snapshot documental baseado no estado auditado" not in normalized


def test_overview_states_m53_evidence_readiness_boundary(normalized: str) -> None:
    assert "m53" in normalized
    assert re.search(r"\bevidencia\b|\bevidence\b", normalized)
    for outcome in READINESS_OUTCOMES:
        assert re.search(rf"\b{outcome}\b", normalized), outcome


def test_overview_references_operational_runbooks(normalized: str) -> None:
    for path in REFERENCED_RUNBOOKS:
        assert path in normalized, path
        assert (REPO_ROOT / path).is_file(), path


def test_overview_references_deployment_invariant_gate(normalized: str) -> None:
    assert DEPLOYMENT_INVARIANT_TEST in normalized
    assert (REPO_ROOT / DEPLOYMENT_INVARIANT_TEST).is_file()


def test_overview_keeps_private_admin_versus_public_boundary(normalized: str) -> None:
    assert "docker-compose.yml" in normalized
    assert "docker-compose.prod.yml" in normalized
    assert "atlas_admin_enabled" in normalized
    assert re.search(r"desabilita (?:o )?admin|disables? (?:the )?admin", normalized)


def test_overview_keeps_supabase_identity_and_gateway_ownership(normalized: str) -> None:
    assert "supabase" in normalized
    assert "inference-gateway" in normalized
    assert re.search(r"anonymous auth|identidade anonima|anonymous visitor", normalized)
    assert re.search(r"\bcota\b|\bquota\b", normalized)
    assert re.search(r"identidade (?:exata )?do operador|operator identity", normalized)


def test_overview_describes_resource_limits_as_infrastructure_governed(normalized: str) -> None:
    assert re.search(r"\bcpu\b", normalized)
    assert re.search(r"cpu[^\n]*infraestrutura|cpu[^\n]*infrastructure", normalized)
    assert re.search(r"verificave(?:l|is) em runtime|runtime[- ]verifiable", normalized)


def test_overview_describes_image_parity_as_executable_invariants(normalized: str) -> None:
    assert re.search(r"invariantes? executave(?:l|is)|executable invariants?", normalized)
    assert re.search(r"evidencia de runtime|runtime evidence", normalized)


def test_overview_assigns_production_tls_proxy_topology_to_infrastructure(normalized: str) -> None:
    assert re.search(r"(?:tls|proxy)[^\n]*repositorio de infraestrutura|infrastructure repository", normalized)
    assert re.search(r"caddyfile[^\n]*(?:modelo local|local model)", normalized)


def test_overview_preserves_s0300_global_subject_quota(normalized: str) -> None:
    assert "s0300" in normalized
    assert re.search(r"cota global por sujeito|global (?:per[- ]subject )?quota", normalized)


def test_overview_has_no_stale_pre_s0299_current_state_claim(overview: str) -> None:
    assert _stale_pre_s0299_claims(overview) == []


def test_overview_has_no_unconditional_readiness_claim(overview: str) -> None:
    assert _unconditional_claims(overview) == []


# --- bounded negative checks: the gate must catch the regressions it guards ---


def test_gate_rejects_stale_active_milestone_variant(overview: str) -> None:
    stale = overview.replace(
        "`M53 — Security Validation and Public Readiness`",
        "`M49 — First-Version Release Readiness and Evidence Gate`",
    )
    assert stale != overview
    assert _stale_or_missing_cursor(stale)


@pytest.mark.parametrize(
    "stale",
    [
        "Limites de CPU, memória e PID — nenhum valor está definido no repositório.",
        "No CPU, memory or PID limit value is defined by this repository.",
        "A identidade das imagens efetivamente implantadas não está evidenciada.",
        "O `Caddyfile` versionado usa `tls internal`.",
    ],
)
def test_gate_rejects_stale_pre_s0299_claim_variant(overview: str, stale: str) -> None:
    assert _stale_pre_s0299_claims(overview + "\n\n" + stale + "\n")


def test_gate_rejects_missing_cursor_variant() -> None:
    assert _stale_or_missing_cursor("# Overview\n\nNo milestone cursor here.\n")


@pytest.mark.parametrize(
    "claim",
    [
        "Atlas is secure.",
        "O Atlas está totalmente seguro.",
        "Production is ready.",
        "A plataforma está pronta para produção.",
        "Backup/restore is verified.",
        "O restore foi testado.",
        "M53 is completed.",
    ],
)
def test_gate_rejects_unconditional_claim_variant(overview: str, claim: str) -> None:
    assert _unconditional_claims(overview + "\n\n" + claim + "\n")


@pytest.mark.parametrize(
    "qualified",
    [
        "Este documento não declara o Atlas seguro.",
        "Backup/restore is not verified until evidence is recorded.",
        "M53 is completed only if its evidence supports it.",
    ],
)
def test_gate_accepts_qualified_wording(qualified: str) -> None:
    assert _unconditional_claims(qualified) == []

"""Project Spec S0292: disaster-recovery runbook documentation gate.

``docs/operations/disaster-recovery.md`` is the repository-owned recovery
contract. This gate locks its minimum semantic coverage: the recovery asset
domains, the distinction between transactional ``*.previous`` rollback and
disaster recovery, an ordered restore sequence, a reduced recovery-evidence
model, and the explicit refusal to treat the runbook itself as evidence that
a backup or restore succeeded.

Offline, deterministic and read-only: the runbook is parsed as Markdown text
only. No Docker daemon, network, database, secret store or backup archive is
involved. Checks use stable headings and bounded patterns rather than exact
prose, so the runbook can be reworded without breaking the gate.

This gate does not, and cannot, prove that any backup exists or that any
restore works; that remains separate operational evidence against the real
deployment.
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "disaster-recovery.md"

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
_ORDERED_ITEM = re.compile(r"^\s*\d+\.\s+(.+)$", re.MULTILINE)

# Bounded patterns for obvious committed secret/private-key material.
_SECRET_PATTERNS = {
    "pem_private_key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "jwt": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"),
    "credentialed_url": re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s:/@<>]+:[^\s@<>]+@", re.IGNORECASE),
    "aws_access_key_id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "stripe_style_secret": re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{16,}"),
    "supabase_secret_key": re.compile(r"\bsb_secret_[A-Za-z0-9_-]{16,}"),
    "assigned_secret_value": re.compile(
        r"(?i)\b[A-Z0-9_]*(?:password|passwd|secret|token|api_?key|private_?key)[A-Z0-9_]*"
        r"\s*[:=]\s*['\"]?(?!<)[A-Za-z0-9/+_.-]{12,}"
    ),
}

# Concrete durations next to RPO/RTO/retention would invent operational
# commitments the repository does not establish.
_INVENTED_OBJECTIVE = re.compile(
    r"(?i)\b(?:RPO|RTO|retention)\b[^.\n|]{0,40}?\b\d+\s*(?:s|sec|seconds?|m|min|minutes?|h|hours?|d|days?|weeks?|months?|years?)\b"
)


def _text() -> str:
    return RUNBOOK_PATH.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Map each lowercased heading to the body up to the next heading of the same or higher level."""
    headings = list(_HEADING.finditer(text))
    sections = {}
    for index, match in enumerate(headings):
        level = len(match.group(1))
        end = len(text)
        for later in headings[index + 1 :]:
            if len(later.group(1)) <= level:
                end = later.start()
                break
        sections[match.group(2).strip().lower()] = text[match.end() : end]
    return sections


def _section(text: str, pattern: str) -> str:
    matches = [body for heading, body in _sections(text).items() if re.search(pattern, heading)]
    assert matches, f"runbook has no section whose heading matches {pattern!r}"
    return "\n".join(matches)


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text)
    return [s for s in re.split(r"(?<=[.!?])\s+|\|", flat) if s.strip()]


def _restore_steps(text: str) -> list[tuple[str, str]]:
    """Return (label, full text) per ordered restore step; the label is the bold lead or the text before a dash."""
    restore = _section(text, r"restore order|recovery order|recovery sequence")
    steps = []
    for item in _ORDERED_ITEM.findall(restore):
        bold = re.match(r"\*\*(.+?)\*\*", item)
        label = bold.group(1) if bold else re.split(r"\s+[—–-]\s+|:", item, maxsplit=1)[0]
        steps.append((label.lower(), item))
    return steps


def _secret_findings(text: str) -> list[str]:
    return [name for name, pattern in _SECRET_PATTERNS.items() if pattern.search(text)]


def test_runbook_exists_and_is_not_empty():
    assert RUNBOOK_PATH.is_file()
    text = _text()
    assert text.strip()
    assert _HEADING.search(text), "runbook has no Markdown headings"


def test_boundary_is_stated_near_the_beginning():
    text = _text()
    boundary = _section(text, r"boundary|purpose|scope")
    assert text.find(boundary) < len(text) // 3, "boundary section must appear near the beginning"

    sentences = _sentences(boundary)
    assert any(
        re.search(r"\bnot\b", s) and re.search(r"\bevidence\b", s) and re.search(r"backup|restore", s, re.I)
        for s in sentences
    ), "runbook must refuse to be treated as backup/restore evidence"
    assert any(
        re.search(r"readiness", s, re.I) and re.search(r"\bblocked\b", s) for s in sentences
    ), "missing sources or restore evidence must keep readiness blocked"
    assert any(
        re.search(r"\b(never|must not|do not)\b", s, re.I)
        and re.search(r"secret", s, re.I)
        and re.search(r"private key", s, re.I)
        and re.search(r"dump", s, re.I)
        for s in sentences
    ), "runbook must forbid committing secrets, private keys and dumps"


@pytest.mark.parametrize(
    "concept",
    [
        r"\bgit\b|source reconstruction",
        r"\.previous|transactional rollback",
        r"durable backup|recovery source",
        r"restore validation|recovery exercise",
    ],
)
def test_recovery_concepts_are_distinguished(concept):
    concepts = _section(_text(), r"concept")
    assert re.search(concept, concepts, re.I), f"recovery concepts do not cover {concept!r}"


def test_transactional_previous_files_are_not_disaster_recovery():
    # A table row or paragraph that names *.previous must also deny it is DR.
    blocks = re.split(r"\n\s*\n|\n(?=\|)", _text())
    assert any(
        re.search(r"\.previous", block)
        and re.search(r"\bnot\b[^.|]{0,30}\b(disaster recovery|durable|system backup)", block, re.I)
        for block in blocks
    ), "runbook must state that *.previous rollback is not disaster recovery"


@pytest.mark.parametrize(
    "domain, required",
    [
        ("database", [r"supabase", r"postgres", r"database"]),
        ("storage", [r"storage"]),
        ("canonical_state", [r"canonical", r"registry", r"release", r"\bruns?\b", r"profile", r"publication"]),
        ("secrets", [r"secret", r"non-versioned"]),
        ("tls_admin", [r"\btls\b", r"admin", r"\bca\b|trust chain", r"certificate"]),
        ("source", [r"revision", r"source"]),
        ("network", [r"dns", r"firewall", r"ingress"]),
        ("operator", [r"operator", r"authori[sz]ation"]),
    ],
)
def test_asset_classes_cover_required_domains(domain, required):
    assets = _section(_text(), r"asset")
    for pattern in required:
        assert re.search(pattern, assets, re.I), f"asset classes do not cover {domain}: missing {pattern!r}"


def test_ca_private_key_stays_outside_repository_and_host():
    text = _text()
    assert any(
        re.search(r"\bCA\b", s) and re.search(r"private key", s, re.I) and re.search(r"\b(never|not|stays?)\b", s, re.I)
        and re.search(r"repository", s, re.I)
        for s in _sentences(text)
    ), "runbook must keep the client CA private key out of the repository and application host"


@pytest.mark.parametrize(
    "scenario",
    [
        r"canonical[^.\n]*lost[^.\n]*database[^.\n]*surviv",
        r"database[^.\n]*lost[^.\n]*canonical[^.\n]*surviv",
        r"secrets?[^.\n]*lost",
        r"tls[^.\n]*lost",
        r"source[^.\n]*available[^.\n]*(state|persistent)[^.\n]*unavailable",
    ],
)
def test_loss_scenarios_are_described_independently(scenario):
    scenarios = _section(_text(), r"loss|scenario")
    assert re.search(scenario, scenarios, re.I), f"loss scenarios do not describe {scenario!r}"


def test_restore_order_is_an_ordered_dependency_sequence():
    labels = [label for label, _ in _restore_steps(_text())]
    assert len(labels) >= 9, "restore order must list at least nine ordered steps"

    def first_step(pattern: str) -> int:
        for index, label in enumerate(labels):
            if re.search(pattern, label):
                return index
        pytest.fail(f"restore order has no step labelled {pattern!r}: {labels}")

    sequence = [
        first_step(r"host|runtime prerequisite"),
        first_step(r"source|deployment definition"),
        first_step(r"secret|configuration"),
        first_step(r"database|storage"),
        first_step(r"canonical"),
        first_step(r"\btls\b"),
        first_step(r"start|recreate"),
        first_step(r"validat"),
        first_step(r"record"),
    ]
    assert sequence == sorted(sequence), f"restore steps are out of dependency order: {labels}"


def test_restore_order_validates_before_reexposing_traffic():
    validation = next((item for label, item in _restore_steps(_text()) if re.search(r"validat", label)), None)
    assert validation is not None, "restore order has no validation step"
    for pattern in (r"health", r"public", r"private", r"persistence|consisten", r"invariant", r"traffic|ingress|expos"):
        assert re.search(pattern, validation, re.I), f"validation step does not cover {pattern!r}"


def test_recovery_evidence_contract_is_reduced_and_blocks_on_gaps():
    evidence = _section(_text(), r"evidence|readiness")
    for pattern in (
        r"source_revision|source revision",
        r"target",
        r"digest",
        r"asset",
        r"step",
        r"validation",
        r"blocker",
        r"reservation",
        r"_at\b|timestamp",
        r"\bready\b",
        r"ready_with_documented_reservations",
        r"\bblocked\b",
        r"secrets_persisted|secret-free",
    ):
        assert re.search(pattern, evidence, re.I), f"recovery evidence contract does not cover {pattern!r}"

    assert any(
        re.search(r"\bblocked\b|\bblocker\b", s)
        and re.search(r"no identified recovery source|missing|absen", s, re.I)
        for s in _sentences(evidence)
    ), "missing recovery sources must be defined as a blocker"
    assert any(
        re.search(r"\bblocked\b|\bblocker\b", s) and re.search(r"restore", s, re.I) for s in _sentences(evidence)
    ), "missing restore evidence must be defined as a blocker"


def test_runbook_does_not_invent_recovery_objectives():
    match = _INVENTED_OBJECTIVE.search(_text())
    assert match is None, f"runbook invents a concrete recovery objective: {match.group(0)!r}"


def test_runbook_contains_no_obvious_secret_material():
    assert _secret_findings(_text()) == []


@pytest.mark.parametrize(
    "sample, expected",
    [
        ("-----BEGIN " + "RSA PRIVATE KEY-----", "pem_private_key"),
        ("-----BEGIN " + "PRIVATE KEY-----", "pem_private_key"),
        ("ey" + "J" + "a" * 20 + "." + "b" * 20 + "." + "c" * 20, "jwt"),
        ("postgresql://atlas:" + "hunter2hunter2" + "@db.internal:5432/atlas", "credentialed_url"),
        ("AKIA" + "ABCDEFGHIJKLMNOP", "aws_access_key_id"),
        ("ATLAS_INFERENCE_GATEWAY_TOKEN=" + "q" * 32, "assigned_secret_value"),
    ],
)
def test_secret_detector_flags_known_shapes(sample, expected):
    assert expected in _secret_findings(sample)


@pytest.mark.parametrize(
    "sample",
    [
        "ATLAS_ADMIN_USER_ID=<operator-user-uuid>",
        "inject values from `<approved-secret-source>`",
        "the client CA private key stays outside the repository",
    ],
)
def test_secret_detector_ignores_placeholders(sample):
    assert _secret_findings(sample) == []

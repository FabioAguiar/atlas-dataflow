"""Documentation guards for scientific-reproduction claims.

Repository documentation and the Dry Bean integration notebook must not
reference frozen study evidence through a mutable branch, and must not claim
that a test partition with recorded historical exposure was never seen.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARDED = [
    REPO_ROOT / "docs/scientific-reproduction.md",
    REPO_ROOT / "docs/scientific-reproduction-dry-bean.md",
    REPO_ROOT / "notebooks/datasets/dry-bean/dataset_integration.ipynb",
]
MUTABLE_STUDY_REF = re.compile(r"dataset-study-[a-z0-9-]+/(?:blob/|raw/|tree/)?(?:main|master)/")
NEVER_SEEN_CLAIMS = re.compile(
    r"(\d[\d,.]*\s+previously unseen observations|never (?:been )?seen by the author|test (?:was )?never opened)",
    re.IGNORECASE,
)


def _text(path: Path) -> str:
    if path.suffix == ".ipynb":
        notebook = json.loads(path.read_text(encoding="utf-8"))
        return "\n".join("".join(cell["source"]) for cell in notebook["cells"])
    return path.read_text(encoding="utf-8")


def test_docs_pin_study_evidence_instead_of_mutable_branches():
    for path in GUARDED:
        assert not MUTABLE_STUDY_REF.search(_text(path)), path


def test_docs_do_not_claim_historically_exposed_test_was_never_seen():
    for path in GUARDED:
        assert not NEVER_SEEN_CLAIMS.search(_text(path)), path


def test_dry_bean_docs_separate_the_three_concepts_and_the_exposure_limitation():
    text = _text(REPO_ROOT / "docs/scientific-reproduction-dry-bean.md")
    for heading in ("## 1. Scientific Study", "## 2. Scientific Reproduction in Atlas", "## 3. Active Atlas Native Release"):
        assert heading in text
    assert "superseded" in text and "procedimentalmente" in text
    assert "repro-20260929T163341Z" in text

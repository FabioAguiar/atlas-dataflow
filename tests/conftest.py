import pytest
from datetime import datetime, timezone


# =====================================================
# Issue #2 — Config Loader fixtures
# =====================================================

@pytest.fixture
def project_like_config_defaults_yaml() -> str:
    return """\
engine:
  fail_fast: true
  log_level: INFO
steps:
  ingest:
    enabled: true
  train:
    enabled: true
"""


@pytest.fixture
def project_like_config_local_yaml() -> str:
    return """\
engine:
  log_level: DEBUG
steps:
  train:
    enabled: false
"""


# =====================================================
# Issue #3 — Pipeline fixtures (Step + RunContext)
# =====================================================

@pytest.fixture
def dummy_config() -> dict:
    return {
        "engine": {"fail_fast": True, "log_level": "INFO"},
        "steps": {"ingest": {"enabled": True}},
    }


@pytest.fixture
def dummy_contract() -> dict:
    return {
        "contract_version": "1.0",
        "problem": {"type": "classification"},
        "target": {"name": "y", "type": "binary"},
        "features": {"numeric": ["x1"], "categorical": []},
        "types": {"x1": "float", "y": "int"},
    }


@pytest.fixture
def dummy_ctx(dummy_config, dummy_contract):
    # Import lazily so tests can fail with informative messages if module missing.
    from atlas_dataflow.core.pipeline.context import RunContext

    return RunContext(
        run_id="run-test-001",
        created_at=datetime(2026, 1, 16, 0, 0, 0, tzinfo=timezone.utc),
        config=dummy_config,
        contract=dummy_contract,
        meta={"source": "pytest"},
    )


@pytest.fixture
def DummyStep():
    # Factory that returns a minimal Step implementation (duck-typed).
    # Import lazily so tests can fail with informative messages if module missing.
    from atlas_dataflow.core.pipeline.types import StepKind, StepStatus, StepResult

    class _DummyStep:
        def __init__(
            self,
            step_id: str = "ingest.load",
            kind: StepKind = StepKind.DIAGNOSTIC,
            depends_on=None,
        ):
            self.id = step_id
            self.kind = kind
            self.depends_on = depends_on or []

        def run(self, ctx):
            ctx.set_artifact(f"{self.id}.ok", True)
            return StepResult(
                step_id=self.id,
                kind=self.kind,
                status=StepStatus.SUCCESS,
                summary="dummy ok",
                metrics={},
                warnings=[],
                artifacts={"ok": f"{self.id}.ok"},
                payload={"note": "dummy"},
            )

    return _DummyStep

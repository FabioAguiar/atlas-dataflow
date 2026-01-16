import pytest

@pytest.fixture
def project_like_config_defaults_yaml() -> str:
    return """engine:
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
    return """engine:
  log_level: DEBUG
steps:
  train:
    enabled: false
"""

import json
from pathlib import Path

import jsonschema


REPO_ROOT = Path(__file__).parent.parent
SCHEMA_PATH = REPO_ROOT / "contracts" / "dataset-public-profile.schema.json"
SNAPSHOT_SCHEMA_PATH = (
    REPO_ROOT / "contracts" / "dataset-public-profile-snapshot.schema.json"
)
VALID_EXAMPLE_PATH = (
    REPO_ROOT / "contracts" / "examples" / "dataset-public-profile.example.json"
)
INVALID_TECHNICAL_FIELD_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-technical-field.example.json"
)
INVALID_UNSUPPORTED_THEME_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-unsupported-theme.example.json"
)
INVALID_UNSUPPORTED_ICON_PATH = (
    REPO_ROOT
    / "contracts"
    / "examples"
    / "invalid-dataset-public-profile-unsupported-icon.example.json"
)

THEME_PRESET_IDS = [
    "atlas-green", "ocean-blue", "violet-insight", "amber-signal", "slate-ops",
    "rose-review", "teal-flow", "indigo-lab", "graphite", "citrus", "coral",
    "skyline", "plum", "neutral-light", "midnight-cyan", "emerald-noir",
    "solar-flare", "electric-magenta", "neon-lime", "aurora", "deep-sea",
    "desert-sand", "forest-moss", "ice-blue", "crimson-night", "copper-circuit",
    "lavender-mist", "monochrome-dark", "retro-terminal", "cyber-neon",
]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_schema_is_valid_draft7():
    schema = _load_json(SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(schema)

    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    jsonschema.Draft7Validator.check_schema(snapshot_schema)


def test_draft_and_snapshot_theme_catalogs_are_exact_and_accept_every_preset():
    draft_schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    draft_enum = draft_schema["definitions"]["theme"]["properties"]["preset"]["enum"]
    snapshot_enum = snapshot_schema["definitions"]["theme"]["properties"]["preset"]["enum"]

    assert draft_enum == THEME_PRESET_IDS
    assert snapshot_enum == THEME_PRESET_IDS

    for preset_id in THEME_PRESET_IDS:
        jsonschema.validate(
            {"schema_version": "0.1.0", "dataset_slug": "example-dataset", "theme": {"preset": preset_id}},
            draft_schema,
        )
        jsonschema.validate(
            {
                "schema_version": "0.1.0",
                "dataset_slug": "example-dataset",
                "published_at": "2026-07-13T12:00:00Z",
                "active_release_at_publish_time": "release-20260713-001",
                "profile": {"theme": {"preset": preset_id}},
            },
            snapshot_schema,
        )


def test_valid_dataset_public_profile_example_matches_schema():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(VALID_EXAMPLE_PATH)

    jsonschema.validate(example, schema)


def test_dataset_public_profile_rejects_technical_field():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_TECHNICAL_FIELD_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "Additional properties are not allowed" in error.message
        or "metrics" in error.message
        for error in errors
    )


def test_dataset_public_profile_rejects_unsupported_theme():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSUPPORTED_THEME_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "is not one of" in error.message or "custom-rainbow" in error.message
        for error in errors
    )

    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    invalid_snapshot = {
        "schema_version": "0.1.0",
        "dataset_slug": "telco-customer-churn",
        "published_at": "2026-07-13T12:00:00Z",
        "active_release_at_publish_time": "release-20260713-001",
        "profile": {"theme": example["theme"]},
    }
    assert list(jsonschema.Draft7Validator(snapshot_schema).iter_errors(invalid_snapshot))


def test_dataset_public_profile_rejects_unsupported_icon():
    schema = _load_json(SCHEMA_PATH)
    example = _load_json(INVALID_UNSUPPORTED_ICON_PATH)

    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(example))

    assert errors
    assert any(
        "is not one of" in error.message or "satellite" in error.message
        for error in errors
    )


# ---------------------------------------------------------------------------
# Project Spec S0196: optional Markdown documentation on the draft profile
# and on the published snapshot profile, sharing the exact same bounded
# {format, content} shape.
# ---------------------------------------------------------------------------


def _base_profile(**overrides):
    profile = {"schema_version": "0.1.0", "dataset_slug": "example-dataset"}
    profile.update(overrides)
    return profile


def _base_snapshot(profile_overrides=None):
    return {
        "schema_version": "0.1.0",
        "dataset_slug": "telco-customer-churn",
        "published_at": "2026-07-13T12:00:00Z",
        "active_release_at_publish_time": "release-20260713-001",
        "profile": profile_overrides or {},
    }


def test_valid_markdown_documentation_is_accepted_in_draft_and_snapshot():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": "# Heading\n\nSome **body** text."}

    jsonschema.validate(_base_profile(documentation=documentation), schema)
    jsonschema.validate(_base_snapshot({"documentation": documentation}), snapshot_schema)


def test_blank_documentation_content_is_accepted_as_unauthored_state():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": ""}

    jsonschema.validate(_base_profile(documentation=documentation), schema)
    jsonschema.validate(_base_snapshot({"documentation": documentation}), snapshot_schema)


def test_profiles_and_snapshots_without_documentation_remain_valid():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)

    jsonschema.validate(_base_profile(), schema)
    jsonschema.validate(_base_snapshot(), snapshot_schema)


def test_documentation_rejects_unsupported_format():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "html", "content": "<p>not markdown</p>"}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_rejects_non_string_content():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": 12345}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_rejects_unknown_properties():
    schema = _load_json(SCHEMA_PATH)
    snapshot_schema = _load_json(SNAPSHOT_SCHEMA_PATH)
    documentation = {"format": "markdown", "content": "Body", "rendered_html": "<p>Body</p>"}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))
    assert list(
        jsonschema.Draft7Validator(snapshot_schema).iter_errors(
            _base_snapshot({"documentation": documentation})
        )
    )


def test_documentation_enforces_max_length():
    schema = _load_json(SCHEMA_PATH)
    max_length = schema["definitions"]["documentation"]["properties"]["content"]["maxLength"]
    documentation = {"format": "markdown", "content": "a" * (max_length + 1)}

    assert list(jsonschema.Draft7Validator(schema).iter_errors(_base_profile(documentation=documentation)))


def test_documentation_does_not_bypass_technical_field_rejection():
    schema = _load_json(SCHEMA_PATH)
    profile = _base_profile(documentation={"format": "markdown", "content": "Body"})
    profile["metrics"] = {"accuracy": 0.9}

    errors = list(jsonschema.Draft7Validator(schema).iter_errors(profile))
    assert errors

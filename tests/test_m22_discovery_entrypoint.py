import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
NOTEBOOK_PATH = REPO_ROOT / "notebooks" / "datasets" / "telco-customer-churn" / "01_dataset_authoring.ipynb"


def _load_notebook() -> dict:
    return json.loads(NOTEBOOK_PATH.read_text(encoding="utf-8"))


def _all_code_source(nb: dict) -> str:
    return "\n".join(
        "".join(c["source"]) for c in nb["cells"] if c["cell_type"] == "code"
    )


def _all_source(nb: dict) -> str:
    return "\n".join("".join(c["source"]) for c in nb["cells"])


def _parameter_cells(nb: dict) -> list:
    return [
        c for c in nb["cells"]
        if "parameters" in c.get("metadata", {}).get("tags", [])
    ]


def test_notebook_exists():
    assert NOTEBOOK_PATH.exists(), f"Notebook not found: {NOTEBOOK_PATH}"


def test_notebook_is_valid_json():
    nb = _load_notebook()
    assert isinstance(nb, dict)
    assert "cells" in nb
    assert "nbformat" in nb


def test_notebook_has_parameters_cell():
    nb = _load_notebook()
    cells = _parameter_cells(nb)
    assert cells, "Notebook must have a cell tagged 'parameters'."
    source = "".join(cells[0]["source"])
    assert "dataset_relative_path" in source, (
        "Parameters cell must declare dataset_relative_path."
    )


def test_notebook_requires_explicit_repository_relative_dataset_path():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "dataset_relative_path" in source, (
        "Notebook must reference dataset_relative_path."
    )
    assert "raise FileNotFoundError" in source, (
        "Notebook must guard against a missing dataset file."
    )


def test_dataset_relative_path_default_is_repository_relative():
    nb = _load_notebook()
    cells = _parameter_cells(nb)
    assert cells, "Notebook must have a parameters cell."
    param_source = "".join(cells[0]["source"])
    assert "dataset_relative_path = \"data/raw/telco-customer-churn.csv\"" in param_source, (
        "dataset_relative_path default must be the repository-relative Telco CSV path."
    )
    assert "repo_root = None" in param_source, (
        "repo_root default must be None; an explicit override, not a hardcoded absolute path."
    )


def test_notebook_resolves_dataset_path_from_repository_root_not_notebook_directory():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "repo_root" in source and "dataset_relative_path" in source, (
        "Notebook must combine an explicit or default repo_root with the "
        "repository-relative dataset path."
    )
    assert "__file__" not in source, (
        "Notebook must not derive its dataset path from its own nested "
        "notebook file location."
    )
    assert "../" not in source, (
        "Notebook must not rely on fragile relative traversal tied to its "
        "old, less-nested location."
    )


def test_notebook_calls_reusable_helper_behavior():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "from pipeline.discovery_evidence import" in source, (
        "Notebook must call the reusable helper behavior from "
        "pipeline/discovery_evidence.py instead of duplicating common "
        "loading and inspection logic inline."
    )
    for helper in [
        "resolve_repository_path",
        "load_dataset_csv",
        "summarize_structure",
        "observe_authoring_fields",
        "summarize_target_column",
        "summarize_identifier_columns",
        "derive_feature_candidates",
        "authoring_helper_evidence_policy",
    ]:
        assert helper in source, f"Notebook must call helper: {helper}"


def test_notebook_records_authoring_observations():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "authoring_observations" in source, (
        "Notebook must record authoring_observations."
    )


def test_notebook_declares_forbidden_side_effects():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert "FORBIDDEN_SIDE_EFFECTS" in source, (
        "Notebook must declare FORBIDDEN_SIDE_EFFECTS boundary."
    )
    for forbidden in [
        "model_training",
        "release_candidate_creation",
        "release_promotion",
        "registry_state_mutation",
        "api_behavior_change",
        "ui_behavior_change",
    ]:
        assert forbidden in source, (
            f"Notebook must declare '{forbidden}' as a forbidden side effect."
        )


def test_notebook_declares_output_is_not_final_operational_truth():
    nb = _load_notebook()
    source = _all_source(nb)
    assert "not_final_operational_truth" in source or "not the final" in source, (
        "Notebook must declare that its output is not the final operational source of truth."
    )


def test_notebook_does_not_depend_on_public_services():
    nb = _load_notebook()
    source = _all_code_source(nb)
    forbidden_imports = ["requests", "urllib.request", "boto3", "google.cloud", "azure"]
    for imp in forbidden_imports:
        assert imp not in source, (
            f"Notebook must not import public service client '{imp}'; "
            "the entrypoint must run locally without public services."
        )


def test_old_root_level_notebook_path_is_not_the_active_path():
    old_path = REPO_ROOT / "notebooks" / "m22_discovery_entrypoint.ipynb"
    assert not old_path.exists(), (
        "The old root-level notebook path must not be required as the "
        "active notebook path for this spec."
    )


# ---------------------------------------------------------------------------
# Project Spec S0129: the notebook's release-candidate handoff readiness
# section must propagate a fifth `visualizations` training-related role
# through `normalize_training_handoff_references` (Project Spec S0031,
# extended by S0128) exactly the way it already propagates the other four
# roles -- not merely mention the word "visualizations" somewhere in source.
# ---------------------------------------------------------------------------

def _readiness_cell_source(nb: dict) -> str:
    for cell in nb["cells"]:
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"])
        if "TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS = {" in source:
            return source
    raise AssertionError(
        "Could not find the code cell declaring "
        "TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS."
    )


def _exec_readiness_cell(*, repo_root: Path, training_run_materialization: dict) -> dict:
    """Execute the notebook's actual readiness-cell source (not a
    reimplementation) against a controlled temporary repository root and a
    synthetic governed-training-run-materialization result, and return the
    resulting cell namespace for assertion."""
    nb = _load_notebook()
    source = _readiness_cell_source(nb)
    namespace = {
        "dataset_slug": "telco-customer-churn",
        "_repo_root_path": repo_root,
        "telco_training_run_materialization": training_run_materialization,
        "json": json,
    }
    exec(compile(source, "<readiness-cell>", "exec"), namespace)  # noqa: S102
    return namespace


def test_train_pending_training_role_paths_has_exactly_five_roles():
    namespace = _exec_readiness_cell(
        repo_root=REPO_ROOT,
        training_run_materialization={"status": "pending"},
    )
    role_paths = namespace["TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS"]
    assert list(role_paths.keys()) == [
        "training_parameter_record",
        "model_artifact",
        "training_metrics",
        "model_card",
        "visualizations",
    ], "TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS must declare exactly these five roles, in order."


def test_visualizations_blocked_placeholder_is_repository_relative_train_pending():
    namespace = _exec_readiness_cell(
        repo_root=REPO_ROOT,
        training_run_materialization={"status": "pending"},
    )
    placeholder = namespace["TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS"]["visualizations"]
    assert placeholder.endswith("train-pending/analytical-visualizations.json")
    assert not placeholder.startswith("/")
    assert placeholder == (
        "pipeline/training-runs/telco-customer-churn/"
        "train-pending/analytical-visualizations.json"
    )


def test_documentation_and_comments_describe_five_training_related_roles():
    nb = _load_notebook()
    source = _all_source(nb)
    assert "five training-related roles" in source, (
        "Notebook documentation/comments must describe five training-related roles."
    )
    assert "four training-related roles" not in source, (
        "Notebook must no longer describe four training-related roles."
    )


def test_readiness_cell_never_infers_a_training_run_by_globbing_or_newest_directory():
    nb = _load_notebook()
    source = _readiness_cell_source(nb)
    assert "glob(" not in source, (
        "Notebook must not infer a training run via glob()."
    )
    assert ".iterdir(" not in source, (
        "Notebook must not infer a training run by listing a directory."
    )
    assert "normalize_training_handoff_references(" in source, (
        "Notebook must source trained paths only through "
        "normalize_training_handoff_references()."
    )


def test_visualizations_role_blocked_when_training_is_not_trained():
    """A blocked/absent training result must keep the non-existing
    train-pending placeholder for visualizations, and readiness must remain
    blocked because of it -- proving the negative/blocked-state contract,
    not just the string 'visualizations' appearing somewhere."""
    namespace = _exec_readiness_cell(
        repo_root=REPO_ROOT,
        training_run_materialization={"status": "pending"},
    )
    role_paths = namespace["telco_training_handoff_role_paths"]
    placeholder = namespace["TELCO_TRAIN_PENDING_TRAINING_ROLE_PATHS"]["visualizations"]
    assert role_paths["visualizations"] == placeholder
    assert not (REPO_ROOT / placeholder).exists(), (
        "The train-pending placeholder path must never exist on disk; the "
        "notebook must never create it merely to satisfy readiness."
    )
    readiness = namespace["release_candidate_handoff_readiness"]
    visualizations_result = next(
        r for r in readiness["role_results"] if r["role"] == "visualizations"
    )
    assert visualizations_result["ready"] is False
    assert visualizations_result["reason"] == "missing_reference"
    assert "visualizations" in readiness["not_ready_roles"]


def test_visualizations_role_propagates_a_real_normalized_path_when_trained(tmp_path):
    """A synthetic *trained* result whose training_result carries a real,
    existing analytical_visualizations_path must flow, through the actual
    notebook cell code and the real normalize_training_handoff_references()
    boundary, all the way into TELCO_RELEASE_CANDIDATE_ARTIFACT_REFERENCES
    and into a `ready` release_candidate_handoff_readiness role result --
    proving propagation, not merely that the string 'visualizations' is
    present somewhere in the notebook source."""
    run_dir = "pipeline/training-runs/telco-customer-churn/train-s0129fixture/"
    visualizations_relative_path = f"{run_dir}analytical-visualizations.json"
    visualizations_abs_path = tmp_path / visualizations_relative_path
    visualizations_abs_path.parent.mkdir(parents=True)
    visualizations_abs_path.write_text(
        json.dumps({"artifact_kind": "analytical_visualizations", "charts": []}),
        encoding="utf-8",
    )

    training_run_materialization = {
        "status": "trained",
        "training_result": {
            "output_directory": run_dir,
            "analytical_visualizations_path": visualizations_relative_path,
        },
    }

    namespace = _exec_readiness_cell(
        repo_root=tmp_path,
        training_run_materialization=training_run_materialization,
    )

    assert (
        namespace["telco_training_handoff_normalization"]["role_paths"]["visualizations"]
        == visualizations_relative_path
    ), "normalize_training_handoff_references() must resolve the real trained path."
    assert (
        namespace["telco_training_handoff_role_paths"]["visualizations"]
        == visualizations_relative_path
    ), "The notebook's role-path merge must not discard the real normalized path."
    assert (
        namespace["TELCO_RELEASE_CANDIDATE_ARTIFACT_REFERENCES"]["visualizations"]
        == visualizations_relative_path
    ), "TELCO_RELEASE_CANDIDATE_ARTIFACT_REFERENCES must receive the projected visualizations role."

    readiness = namespace["release_candidate_handoff_readiness"]
    visualizations_result = next(
        r for r in readiness["role_results"] if r["role"] == "visualizations"
    )
    assert visualizations_result["ready"] is True
    assert visualizations_result["reason"] is None
    assert visualizations_result["path"] == visualizations_relative_path
    assert "visualizations" not in readiness["not_ready_roles"]
    assert not any(
        reason.startswith("visualizations:") for reason in readiness["blocking_reasons"]
    )


def test_downstream_candidate_and_publisher_materialization_remain_gated_by_readiness():
    nb = _load_notebook()
    source = _all_code_source(nb)
    assert (
        'if not release_candidate_handoff_readiness["is_release_candidate_input_ready"]:'
        in source
    ), (
        "Release-candidate assembly must remain gated by "
        "is_release_candidate_input_ready."
    )
    assert (
        'telco_release_candidate_assembly_result.get("status") != "accepted"' in source
    ), (
        "Publisher-validation run materialization must remain gated on an "
        "accepted release-candidate assembly."
    )

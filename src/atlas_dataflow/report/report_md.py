
"""
src/atlas_dataflow/report/report_md.py

Gerador canônico de `report.md` (v1) — Atlas DataFlow (M7-01)

Regras:
- O report.md é derivado EXCLUSIVAMENTE do Manifest final (dict).
- Não infere, não recalcula, não acessa filesystem fora do que está registrado.
- Mesmo Manifest => mesmo report.md (determinismo por ordenação estável).

Estrutura mínima obrigatória:
# Execution Report

## Executive Summary
## Pipeline Overview
## Decisions & Outcomes
## Metrics
## Generated Artifacts
## Traceability
## Limitations
## Execution Metadata
"""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Tuple


REQUIRED_SECTIONS: List[str] = [
    "# Execution Report",
    "## Executive Summary",
    "## Pipeline Overview",
    "## Decisions & Outcomes",
    "## Metrics",
    "## Generated Artifacts",
    "## Traceability",
    "## Limitations",
    "## Execution Metadata",
]


def _sorted_items(d: Any) -> List[Tuple[str, Any]]:
    if not isinstance(d, dict):
        return []
    return sorted(d.items(), key=lambda kv: kv[0])


def _as_pretty_json(value: Any) -> str:
    # Deterministic JSON rendering for payload excerpts
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)


def _require_manifest(manifest: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(manifest, dict) or not manifest:
        raise ValueError("Manifest is required to generate report.md")
    return manifest


def _extract_step(manifest: Dict[str, Any], step_id: str) -> Dict[str, Any] | None:
    steps = manifest.get("steps")
    if not isinstance(steps, dict):
        return None
    step = steps.get(step_id)
    return step if isinstance(step, dict) else None


def _collect_artifacts_from_steps(steps: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for step_id, step in _sorted_items(steps):
        if not isinstance(step, dict):
            continue
        artifacts = step.get("artifacts")
        if not isinstance(artifacts, dict) or not artifacts:
            continue
        for art_key, art_val in _sorted_items(artifacts):
            out.append(
                {
                    "artifact_key": art_key,
                    "path": art_val,
                    "produced_by": step_id,
                }
            )
    return out


def generate_report_md(manifest: Dict[str, Any]) -> str:
    """Gera o conteúdo completo do report.md a partir do Manifest final."""
    manifest = _require_manifest(manifest)

    run = manifest.get("run") if isinstance(manifest.get("run"), dict) else {}
    inputs = manifest.get("inputs") if isinstance(manifest.get("inputs"), dict) else {}
    steps = manifest.get("steps") if isinstance(manifest.get("steps"), dict) else {}
    events = manifest.get("events") if isinstance(manifest.get("events"), list) else []

    lines: List[str] = []

    # Title
    lines.append("# Execution Report\n")

    # Executive Summary (no inference: only what is explicitly recorded)
    lines.append("## Executive Summary")
    run_id = run.get("run_id", "<unknown>")
    started_at = run.get("started_at", "<unknown>")
    atlas_version = run.get("atlas_version", "<unknown>")
    lines.append(f"- **Run ID**: `{run_id}`")
    lines.append(f"- **Started At (UTC)**: `{started_at}`")
    lines.append(f"- **Atlas Version**: `{atlas_version}`")
    lines.append("\nThis report consolidates the pipeline execution strictly from the Manifest.")
    lines.append("If something is absent here, it was absent from the Manifest.\n")

    # Pipeline Overview
    lines.append("## Pipeline Overview")
    if steps:
        for step_id, step in _sorted_items(steps):
            if not isinstance(step, dict):
                continue
            status = step.get("status", "unknown")
            kind = step.get("kind", "unknown")
            summary = step.get("summary") or ""
            if summary:
                lines.append(f"- **{step_id}** (`{kind}`) — status: `{status}` — {summary}")
            else:
                lines.append(f"- **{step_id}** (`{kind}`) — status: `{status}`")
    else:
        lines.append("No steps recorded in the Manifest.")
    lines.append("")

    # Decisions & Outcomes
    # No heuristic: we surface payloads of known decision steps if present.
    lines.append("## Decisions & Outcomes")
    decision_step = _extract_step(manifest, "evaluate.model_selection")
    if decision_step and isinstance(decision_step.get("payload"), dict) and decision_step.get("payload"):
        lines.append("### evaluate.model_selection.payload")
        lines.append("```json")
        lines.append(_as_pretty_json(decision_step.get("payload")))
        lines.append("```")
    else:
        lines.append("No decision payload found for `evaluate.model_selection` in the Manifest.")
    lines.append("")

    # Metrics
    lines.append("## Metrics")
    metrics_step = _extract_step(manifest, "evaluate.metrics")
    metrics = metrics_step.get("metrics") if isinstance(metrics_step, dict) else None
    if isinstance(metrics, dict) and metrics:
        for k, v in _sorted_items(metrics):
            lines.append(f"- **{k}**: `{v}`")
    else:
        lines.append("No metrics found for `evaluate.metrics.metrics` in the Manifest.")
    lines.append("")

    # Generated Artifacts
    lines.append("## Generated Artifacts")
    artifacts = _collect_artifacts_from_steps(steps)
    if artifacts:
        for a in artifacts:
            lines.append(
                f"- **{a['artifact_key']}** — `{a['path']}` (produced_by: `{a['produced_by']}`)"
            )
    else:
        lines.append("No artifacts recorded in Manifest steps.")
    lines.append("")

    # Traceability
    lines.append("## Traceability")
    lines.append("- Source of truth: `Manifest` (final) only.")
    lines.append("- This report does not compute or infer missing information.")
    lines.append(f"- Events recorded: `{len(events)}`\n" if isinstance(events, list) else "- Events recorded: `<unknown>`\n")

    # Limitations
    lines.append("## Limitations")
    lines.append("- No PDF generation (out of scope v1).") 
    lines.append("- No charts/visualizations (out of scope v1).") 
    lines.append("- No interpretation or business commentary; this is a consolidation artifact.\n")

    # Execution Metadata
    lines.append("## Execution Metadata")
    lines.append("### run")
    lines.append("```json")
    lines.append(_as_pretty_json(run))
    lines.append("```")
    lines.append("### inputs")
    lines.append("```json")
    lines.append(_as_pretty_json(inputs))
    lines.append("```")

    content = "\n".join(lines)

    # sanity: ensure required sections exist
    for sec in REQUIRED_SECTIONS:
        if sec not in content:
            raise RuntimeError(f"Report generation failed: missing required section: {sec}")

    return content

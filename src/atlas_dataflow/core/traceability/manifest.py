from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, Tuple


def _ensure_tzaware_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return _ensure_tzaware_utc(dt).isoformat()


def _ms_between(start: datetime, end: datetime) -> int:
    s = _ensure_tzaware_utc(start)
    e = _ensure_tzaware_utc(end)
    return max(0, int((e - s).total_seconds() * 1000))


@dataclass
class AtlasManifest:
    """Manifest v1 (minimal) — forensic record of a pipeline run."""

    run: Dict[str, Any]
    inputs: Dict[str, Any]
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run": dict(self.run),
            "inputs": dict(self.inputs),
            "steps": {k: dict(v) for k, v in self.steps.items()},
            "events": [dict(e) for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AtlasManifest":
        return cls(
            run=dict(data.get("run", {})),
            inputs=dict(data.get("inputs", {})),
            steps={k: dict(v) for k, v in (data.get("steps", {}) or {}).items()},
            events=[dict(e) for e in (data.get("events", []) or [])],
        )


def create_manifest(
    *,
    run_id: str,
    started_at: datetime,
    atlas_version: str,
    config_hash: str,
    contract_hash: str,
) -> AtlasManifest:
    """Create the initial manifest at the start of a run.

    Tests expect this function to NOT emit any events implicitly.
    """
    started_at = _ensure_tzaware_utc(started_at)

    return AtlasManifest(
        run={
            "run_id": run_id,
            "started_at": _iso(started_at),
            "atlas_version": atlas_version,
        },
        inputs={
            "config_hash": config_hash,
            "contract_hash": contract_hash,
        },
        steps={},
        events=[],
    )


def add_event(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    event_type: str,
    ts: datetime,
    step_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    ts = _ensure_tzaware_utc(ts)
    m = manifest if isinstance(manifest, AtlasManifest) else AtlasManifest.from_dict(manifest)

    ev: Dict[str, Any] = {"event_type": event_type, "timestamp": _iso(ts)}
    if step_id is not None:
        ev["step_id"] = step_id
    if payload is not None:
        ev["payload"] = payload

    m.events.append(ev)

    if not isinstance(manifest, AtlasManifest):
        manifest.clear()
        manifest.update(m.to_dict())


def _get_manifest(manifest: Union[AtlasManifest, Dict[str, Any]]) -> Tuple[AtlasManifest, bool]:
    if isinstance(manifest, AtlasManifest):
        return manifest, False
    return AtlasManifest.from_dict(manifest), True


def step_started(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    kind: str,
    ts: datetime,
) -> None:
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    m.steps.setdefault(step_id, {})
    m.steps[step_id].update(
        {
            "step_id": step_id,
            "kind": kind,
            "status": "running",
            "started_at": _iso(ts),
        }
    )

    add_event(m, event_type="step_started", ts=ts, step_id=step_id, payload={"kind": kind})

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def step_finished(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    ts: datetime,
    result: Dict[str, Any],
) -> None:
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    s = m.steps.setdefault(step_id, {"step_id": step_id})
    started_iso = s.get("started_at")
    if started_iso:
        try:
            started_dt = datetime.fromisoformat(started_iso)
        except Exception:
            started_dt = ts
    else:
        started_dt = ts

    status = result.get("status", "success")
    s.update(
        {
            "status": status,
            "finished_at": _iso(ts),
            "duration_ms": _ms_between(started_dt, ts),
            "summary": result.get("summary"),
            "metrics": result.get("metrics", {}) or {},
            "warnings": result.get("warnings", []) or [],
            "artifacts": result.get("artifacts", {}) or {},
        }
    )

    add_event(
        m,
        event_type="step_finished",
        ts=ts,
        step_id=step_id,
        payload={"status": status, "duration_ms": s.get("duration_ms", 0)},
    )

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def step_failed(
    manifest: Union[AtlasManifest, Dict[str, Any]],
    *,
    step_id: str,
    ts: datetime,
    error: str,
) -> None:
    ts = _ensure_tzaware_utc(ts)
    m, is_dict = _get_manifest(manifest)

    s = m.steps.setdefault(step_id, {"step_id": step_id})
    s.update(
        {
            "status": "failed",
            "finished_at": _iso(ts),
            "error": error,
        }
    )

    add_event(m, event_type="step_failed", ts=ts, step_id=step_id, payload={"error": error})

    if is_dict:
        manifest.clear()
        manifest.update(m.to_dict())


def save_manifest(manifest: Union[AtlasManifest, Dict[str, Any]], path: Path) -> None:
    data = manifest.to_dict() if isinstance(manifest, AtlasManifest) else manifest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def load_manifest(path: Path) -> AtlasManifest:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AtlasManifest.from_dict(data)

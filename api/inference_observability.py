"""Project Spec S0317: bounded, privacy-preserving Prometheus inference telemetry.

Scope of what is measured
-------------------------
Only *handler invocations* of the two FastAPI inference routes are observed:

* ``surface="public"`` -- ``POST /datasets/{slug}/inference``. Observation
  starts when the route handler body runs, i.e. after
  ``InferenceGatewayCredentialMiddleware`` admitted the request and after
  FastAPI parsed the JSON body. A gateway-rejected request, a request whose
  body could not be parsed, and every rejection made upstream (Traefik, the
  Supabase inference gateway, Auth, Turnstile, the subject quota) never reach
  the handler and are therefore *not* counted here. Upstream rate-limit and
  quota denials need a separate metrics source and separately scoped work.
* ``surface="admin"`` -- ``POST /admin/datasets/{slug}/inference``.
  Observation starts only after the composed Admin authorization accepted the
  request; unauthorized probes (answered with the generic 404) are not counted.

A counted request is an HTTP handler invocation, never a completed model
execution: validation errors, readiness/maintenance denials, capacity
rejections and deadline expiries are counted with their own bounded
``result`` value. ``atlas_inference_duration_seconds`` is the wall-clock time
of that same handler invocation (resolution, validation, dispatch and error
return included; upstream gate time excluded). On a deadline expiry the
handler returns after the deadline while the model worker may keep running;
the in-flight gauge tracks handler invocations only and is never a surrogate
for the capacity-two semaphore.

Privacy and cardinality
-----------------------
Labels come from closed vocabularies only. The ``dataset`` label is the
canonical slug *after* trusted resolution (public readiness for the public
surface, registered-dataset resolution for authorized Admin); before that it
is the ``_unresolved`` sentinel, so unknown, hidden, malformed or arbitrary
caller-supplied slugs never become label values. At most
``MAX_DATASET_LABELS`` distinct slugs are admitted per process; any further
slug maps to ``_overflow``. No subject/visitor id, IP, path, query string,
credential, user agent, payload, feature, prediction, exception name or
traceback is ever recorded, logged or attached as an exemplar.

Metrics are process-local, held in a dedicated ``CollectorRegistry`` (no
default process/platform/GC collectors), reset on API restart, and recording
never performs network, disk or database I/O. Every recording step is
best-effort: a telemetry failure can never change an inference response.
"""

from __future__ import annotations

import hmac
import os
import re
import threading
import time

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    generate_latest,
)

# Deterministic exposition: no per-series ``*_created`` timestamps.
disable_created_metrics()

SURFACE_PUBLIC = "public"
SURFACE_ADMIN = "admin"
SURFACES = (SURFACE_PUBLIC, SURFACE_ADMIN)

DATASET_UNRESOLVED = "_unresolved"
DATASET_OVERFLOW = "_overflow"
MAX_DATASET_LABELS = 20
_DATASET_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_DATASET_SLUG_LENGTH = 64

RESULT_SUCCESS = "success"
RESULT_CLIENT_ERROR = "client_error"
RESULT_CAPACITY_EXCEEDED = "capacity_exceeded"
RESULT_TIMEOUT = "timeout"
RESULT_SERVER_ERROR = "server_error"
RESULT_UNHANDLED_EXCEPTION = "unhandled_exception"
RESULTS = (
    RESULT_SUCCESS,
    RESULT_CLIENT_ERROR,
    RESULT_CAPACITY_EXCEEDED,
    RESULT_TIMEOUT,
    RESULT_SERVER_ERROR,
    RESULT_UNHANDLED_EXCEPTION,
)
STATUS_CLASSES = ("2xx", "4xx", "5xx")

# Only these bounded public error codes are distinguished inside 5xx.
_ERROR_CODE_RESULTS = {
    b"INFERENCE_CAPACITY_EXCEEDED": RESULT_CAPACITY_EXCEEDED,
    b"INFERENCE_TIMEOUT": RESULT_TIMEOUT,
}
_ERROR_CODE_PATTERN = re.compile(rb'"error_code"\s*:\s*"([A-Z_]{1,64})"')

# Seconds. Cached predictions were calibrated at ~0.04 s and a cold model
# load at ~2.1 s (Issue M50-06); the inference deadline is 10 s, so a
# deadline expiry lands in the 15 s bucket. +Inf is appended by the client.
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 15.0, 30.0)

REGISTRY = CollectorRegistry(auto_describe=True)

INFERENCE_REQUESTS = Counter(
    "atlas_inference_requests",
    "Inference route handler invocations that entered the FastAPI handler "
    "(not upstream gateway/Auth/quota decisions, not completed model executions).",
    labelnames=("surface", "dataset", "result", "status_class"),
    registry=REGISTRY,
)
INFERENCE_DURATION = Histogram(
    "atlas_inference_duration_seconds",
    "Wall-clock duration of inference route handler invocations.",
    labelnames=("surface", "dataset", "status_class"),
    buckets=DURATION_BUCKETS,
    registry=REGISTRY,
)
INFERENCE_INFLIGHT = Gauge(
    "atlas_inference_inflight_requests",
    "Inference route handler invocations currently in progress.",
    labelnames=("surface",),
    registry=REGISTRY,
)
for _surface in SURFACES:
    INFERENCE_INFLIGHT.labels(surface=_surface).set(0)

# Monotonic clock seam; tests replace it with a deterministic fake.
monotonic = time.perf_counter

_admitted_datasets: set[str] = set()
_admitted_datasets_lock = threading.Lock()


def dataset_label(dataset_slug) -> str:
    """Map a trusted, canonically resolved slug onto the bounded vocabulary."""
    if (
        not isinstance(dataset_slug, str)
        or len(dataset_slug) > _MAX_DATASET_SLUG_LENGTH
        or not _DATASET_SLUG_PATTERN.match(dataset_slug)
    ):
        return DATASET_UNRESOLVED
    with _admitted_datasets_lock:
        if dataset_slug in _admitted_datasets:
            return dataset_slug
        if len(_admitted_datasets) >= MAX_DATASET_LABELS:
            return DATASET_OVERFLOW
        _admitted_datasets.add(dataset_slug)
        return dataset_slug


def classify_response(response) -> tuple[str, str]:
    """Return the bounded ``(result, status_class)`` of a handler return value."""
    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int):
        # FastAPI serializes a plain return value with the route's 200.
        return RESULT_SUCCESS, "2xx"
    if 200 <= status_code < 300:
        return RESULT_SUCCESS, "2xx"
    if 400 <= status_code < 500:
        return RESULT_CLIENT_ERROR, "4xx"
    result = RESULT_SERVER_ERROR
    body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        match = _ERROR_CODE_PATTERN.search(body[:512])
        if match:
            result = _ERROR_CODE_RESULTS.get(match.group(1), RESULT_SERVER_ERROR)
    return result, "5xx"


class InferenceObservation:
    """One handler invocation; use via :func:`observe_inference_handler`."""

    def __init__(self, surface: str) -> None:
        self._surface = surface if surface in SURFACES else SURFACE_PUBLIC
        self._dataset = DATASET_UNRESOLVED
        self._outcome: tuple[str, str] | None = None
        self._started = None

    def bind_dataset(self, dataset_slug) -> None:
        """Bind the canonical slug once trusted resolution has succeeded."""
        try:
            self._dataset = dataset_label(dataset_slug)
        except Exception:
            self._dataset = DATASET_UNRESOLVED

    def complete(self, response):
        """Classify the handler's return value and return it unchanged."""
        try:
            self._outcome = classify_response(response)
        except Exception:
            self._outcome = (RESULT_SERVER_ERROR, "5xx")
        return response

    def __enter__(self) -> "InferenceObservation":
        try:
            self._started = monotonic()
            INFERENCE_INFLIGHT.labels(surface=self._surface).inc()
        except Exception:
            self._started = None
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if self._started is not None:
                INFERENCE_INFLIGHT.labels(surface=self._surface).dec()
            if exc_type is not None or self._outcome is None:
                # The app-wide exception handler answers with a 500.
                result, status_class = RESULT_UNHANDLED_EXCEPTION, "5xx"
            else:
                result, status_class = self._outcome
            INFERENCE_REQUESTS.labels(
                surface=self._surface,
                dataset=self._dataset,
                result=result,
                status_class=status_class,
            ).inc()
            if self._started is not None:
                elapsed = max(0.0, monotonic() - self._started)
                INFERENCE_DURATION.labels(
                    surface=self._surface,
                    dataset=self._dataset,
                    status_class=status_class,
                ).observe(elapsed)
        except Exception:
            pass
        return False


def observe_inference_handler(surface: str) -> InferenceObservation:
    return InferenceObservation(surface)


# ---------------------------------------------------------------------------
# Private exposition access contract
# ---------------------------------------------------------------------------

METRICS_ENABLED_ENV = "ATLAS_OBSERVABILITY_METRICS_ENABLED"
METRICS_BEARER_ENV = "ATLAS_OBSERVABILITY_METRICS_BEARER"
MIN_BEARER_SECRET_LENGTH = 32
_BEARER_CHARSET = re.compile(r"^[A-Za-z0-9._~+/=-]+$")
_AUTHORIZATION_HEADER = b"authorization"
_BEARER_PREFIX = b"Bearer "
_DUMMY_SECRET = b"\x00" * MIN_BEARER_SECRET_LENGTH


def _configured_secret() -> bytes | None:
    if os.environ.get(METRICS_ENABLED_ENV) != "true":
        return None
    secret = os.environ.get(METRICS_BEARER_ENV, "")
    if len(secret) < MIN_BEARER_SECRET_LENGTH or not _BEARER_CHARSET.match(secret):
        return None
    return secret.encode("ascii")


def exposition_authorized(raw_headers) -> bool:
    """Decide once, fail closed, without revealing which condition failed.

    Requires the opt-in flag to be exactly ``true``, a configured secret of at
    least ``MIN_BEARER_SECRET_LENGTH`` token characters, and exactly one
    ``Authorization: Bearer <secret>`` header. A constant-time comparison
    always runs, against a fixed dummy when nothing usable is configured.
    """
    configured = _configured_secret()
    presented = [value for name, value in raw_headers if name.lower() == _AUTHORIZATION_HEADER]
    candidate = _DUMMY_SECRET + b"\x01"
    if len(presented) == 1 and presented[0].startswith(_BEARER_PREFIX):
        candidate = presented[0][len(_BEARER_PREFIX):]
    expected = configured if configured is not None else _DUMMY_SECRET
    digest_equal = hmac.compare_digest(candidate, expected)
    return configured is not None and len(presented) == 1 and digest_equal


def render_exposition() -> tuple[bytes, str]:
    """Prometheus text exposition of the dedicated registry only."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST

"""Project Spec S0317: bounded private Prometheus inference telemetry.

Every request goes through the real FastAPI/ASGI application with synthetic
credentials, synthetic dataset slugs and stubbed runtime seams; no network,
Supabase, Cloudflare, live secret or real model payload is involved. The
telemetry registry is process-global and cumulative, so assertions compare
sample deltas taken around each request.
"""

import asyncio
import json
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from prometheus_client.parser import text_string_to_metric_families

API_DIR = Path(__file__).resolve().parents[1] / "api"
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

import inference_observability as obs  # noqa: E402
import main as api_main  # noqa: E402

GATEWAY_CREDENTIAL = "synthetic-gateway-credential-for-tests"
EXPORTER_SECRET = "synthetic-exporter-secret-0123456789abcdefABCDEF"
RELEASE = "synthetic-release"
SYNTHETIC_CONTRACT = {
    "features": [
        {
            "name": "MonthlyCharges",
            "type": "numeric",
            "required": True,
            "domain_constraints": {"min": 0, "max": 100},
        }
    ]
}
METRICS_PATH = "/_internal/observability/metrics"
NOT_FOUND_BODY = b'{"detail":"Not Found"}'


def _request(method, path, *, body=None, headers=()):
    """Drive the real ASGI app; returns (status, headers, body bytes)."""
    request_body = b"" if body is None else body
    header_list = [(name.lower().encode("latin-1"), value.encode("latin-1")) for name, value in headers]
    if body is not None:
        header_list.append((b"content-type", b"application/json"))
        header_list.append((b"content-length", str(len(request_body)).encode("ascii")))
    messages = []
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": request_body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": header_list,
        "client": ("synthetic-client", 50000),
        "server": ("synthetic-server", 80),
    }
    try:
        asyncio.run(api_main.app(scope, receive, send))
    except Exception:
        # Starlette re-raises after its ServerErrorMiddleware sent the 500.
        pass
    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    response_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in start["headers"]}
    return start["status"], response_headers, response_body


def _post_public(slug, payload=None, *, credential=GATEWAY_CREDENTIAL, raw_body=None):
    headers = [("x-atlas-gateway-token", credential)] if credential else []
    body = raw_body if raw_body is not None else json.dumps(payload or {"MonthlyCharges": 10}).encode()
    return _request("POST", f"/datasets/{slug}/inference", body=body, headers=headers)


def _post_admin(slug, payload=None):
    body = json.dumps(payload or {"MonthlyCharges": 10}).encode()
    return _request("POST", f"/admin/datasets/{slug}/inference", body=body)


def _sample(name, **labels):
    return obs.REGISTRY.get_sample_value(name, labels) or 0.0


def _count(surface, dataset, result, status_class):
    return _sample(
        "atlas_inference_requests_total",
        surface=surface,
        dataset=dataset,
        result=result,
        status_class=status_class,
    )


def _total_requests():
    return sum(
        sample.value
        for family in obs.REGISTRY.collect()
        for sample in family.samples
        if sample.name == "atlas_inference_requests_total"
    )


def _inflight(surface):
    return _sample("atlas_inference_inflight_requests", surface=surface)


def _label_values(label):
    return {
        sample.labels[label]
        for family in obs.REGISTRY.collect()
        for sample in family.samples
        if label in sample.labels
    }


@pytest.fixture(autouse=True)
def _synthetic_environment(monkeypatch):
    monkeypatch.setenv("ATLAS_INFERENCE_GATEWAY_TOKEN", GATEWAY_CREDENTIAL)
    monkeypatch.delenv(obs.METRICS_ENABLED_ENV, raising=False)
    monkeypatch.delenv(obs.METRICS_BEARER_ENV, raising=False)
    monkeypatch.delenv("ATLAS_ADMIN_ENABLED", raising=False)
    # Isolate the bounded dataset vocabulary per test.
    monkeypatch.setattr(obs, "_admitted_datasets", set())


def _ready_public_dataset(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_resolve_public_dataset_detail_access",
        lambda slug: SimpleNamespace(dataset_slug=slug, active_release=RELEASE),
    )
    monkeypatch.setattr(api_main, "_resolve_public_prediction_capability", lambda _release: True)


def _authorized_admin(monkeypatch):
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setattr(
        api_main,
        "_admin_auth_decision_from_request",
        lambda request: SimpleNamespace(authorized=True, reason="synthetic_operator"),
    )
    monkeypatch.setattr(
        api_main,
        "resolve_dataset",
        lambda slug: SimpleNamespace(dataset_slug=slug, active_release=RELEASE),
    )


def _fake_clock(monkeypatch, *readings):
    values = iter(readings)
    monkeypatch.setattr(obs, "monotonic", lambda: next(values))


# ---------------------------------------------------------------------------
# Handler observation semantics
# ---------------------------------------------------------------------------


def test_one_public_handler_entry_is_one_counter_and_one_duration_sample(monkeypatch):
    _ready_public_dataset(monkeypatch)
    prediction = {"dataset_slug": "synthetic-alpha", "result": {"label": "yes"}}
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: prediction)
    _fake_clock(monkeypatch, 100.0, 100.3)

    before_count = _count("public", "synthetic-alpha", "success", "2xx")
    before_total = _total_requests()
    hist = dict(surface="public", dataset="synthetic-alpha", status_class="2xx")
    before_le_025 = _sample("atlas_inference_duration_seconds_bucket", le="0.25", **hist)
    before_le_05 = _sample("atlas_inference_duration_seconds_bucket", le="0.5", **hist)
    before_sum = _sample("atlas_inference_duration_seconds_sum", **hist)

    status, _headers, body = _post_public("synthetic-alpha")

    assert status == 200
    assert json.loads(body) == prediction
    assert _count("public", "synthetic-alpha", "success", "2xx") == before_count + 1
    assert _total_requests() == before_total + 1
    assert _sample("atlas_inference_duration_seconds_bucket", le="0.25", **hist) == before_le_025
    assert _sample("atlas_inference_duration_seconds_bucket", le="0.5", **hist) == before_le_05 + 1
    assert _sample("atlas_inference_duration_seconds_sum", **hist) == pytest.approx(before_sum + 0.3)
    assert _inflight("public") == 0


def test_gateway_rejected_and_unparsable_requests_are_not_handler_executions(monkeypatch):
    _ready_public_dataset(monkeypatch)
    monkeypatch.setattr(
        api_main,
        "_execute_governed_inference",
        lambda *_a, **_k: pytest.fail("a pre-handler rejection must never execute inference"),
    )
    before_total = _total_requests()

    missing_status, _h, _b = _post_public("synthetic-alpha", credential=None)
    wrong_status, _h, _b = _post_public("synthetic-alpha", credential="wrong-credential")
    unparsable_status, _h, _b = _post_public("synthetic-alpha", raw_body=b"{not-json")

    assert missing_status == 401
    assert wrong_status == 401
    assert unparsable_status == 422
    assert _total_requests() == before_total


def test_unresolved_or_not_ready_public_slugs_use_one_constant_sentinel(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_resolve_public_dataset_detail_access",
        lambda _slug: api_main.public_error_response(api_main.DATASET_NOT_FOUND),
    )
    before = _count("public", obs.DATASET_UNRESOLVED, "client_error", "4xx")

    status, _h, _b = _post_public("Arbitrary-Unknown_slug.Value")

    assert status == 404
    assert _count("public", obs.DATASET_UNRESOLVED, "client_error", "4xx") == before + 1
    assert "Arbitrary-Unknown_slug.Value" not in _label_values("dataset")

    monkeypatch.setattr(
        api_main,
        "_resolve_public_dataset_detail_access",
        lambda _slug: api_main.public_error_response(api_main.DATASET_MAINTENANCE),
    )
    hidden_status, _h, _b = _post_public("hidden-synthetic-dataset")
    assert hidden_status == api_main.DATASET_MAINTENANCE.status_code
    assert "hidden-synthetic-dataset" not in _label_values("dataset")


@pytest.mark.parametrize(
    ("public_error", "expected_result", "status_class"),
    (
        ("INFERENCE_CAPACITY_EXCEEDED", "capacity_exceeded", "5xx"),
        ("INFERENCE_TIMEOUT", "timeout", "5xx"),
        ("INFERENCE_FAILURE", "server_error", "5xx"),
        ("CONTRACT_UNAVAILABLE", "server_error", "5xx"),
        ("PUBLIC_PREDICTION_NOT_AVAILABLE", "client_error", "4xx"),
    ),
)
def test_bounded_result_classification(monkeypatch, public_error, expected_result, status_class):
    _ready_public_dataset(monkeypatch)
    error = getattr(api_main, public_error)
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: api_main.public_error_response(error))
    before = _count("public", "synthetic-beta", expected_result, status_class)

    status, _h, body = _post_public("synthetic-beta")

    assert status == error.status_code
    assert json.loads(body)["error_code"] == public_error
    assert _count("public", "synthetic-beta", expected_result, status_class) == before + 1
    assert _label_values("result") <= set(obs.RESULTS)
    assert _label_values("status_class") <= set(obs.STATUS_CLASSES)


def test_validation_error_is_a_client_error_observation(monkeypatch):
    _ready_public_dataset(monkeypatch)
    monkeypatch.setattr(api_main, "load_contract", lambda _release: SYNTHETIC_CONTRACT)
    before = _count("public", "synthetic-gamma", "client_error", "4xx")

    status, _h, body = _post_public("synthetic-gamma", {"MonthlyCharges": 424242})

    assert status == 422
    assert json.loads(body)["error_code"] == "INVALID_PAYLOAD"
    assert _count("public", "synthetic-gamma", "client_error", "4xx") == before + 1


def test_unhandled_exception_is_counted_and_inflight_is_restored(monkeypatch):
    _ready_public_dataset(monkeypatch)

    def _explode(*_args, **_kwargs):
        raise RuntimeError("synthetic failure with private detail")

    monkeypatch.setattr(api_main, "_execute_governed_inference", _explode)
    before = _count("public", "synthetic-delta", "unhandled_exception", "5xx")

    status, _h, body = _post_public("synthetic-delta")

    assert status == 500
    assert json.loads(body)["error_code"] == "UNEXPECTED_ERROR"
    assert _count("public", "synthetic-delta", "unhandled_exception", "5xx") == before + 1
    assert _inflight("public") == 0
    assert "RuntimeError" not in obs.render_exposition()[0].decode()


def test_inflight_gauge_tracks_concurrent_handlers_and_returns_to_baseline(monkeypatch):
    _ready_public_dataset(monkeypatch)
    entered = threading.Barrier(3)
    release = threading.Event()

    def _blocking(*_args, **_kwargs):
        entered.wait(timeout=5)
        release.wait(timeout=5)
        return {"dataset_slug": "synthetic-epsilon", "result": {}}

    monkeypatch.setattr(api_main, "_execute_governed_inference", _blocking)
    before = _count("public", "synthetic-epsilon", "success", "2xx")
    statuses = []
    threads = [
        threading.Thread(target=lambda: statuses.append(_post_public("synthetic-epsilon")[0])) for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    try:
        entered.wait(timeout=5)
        assert _inflight("public") == 2
    finally:
        release.set()
        for thread in threads:
            thread.join(timeout=5)

    assert statuses == [200, 200]
    assert _inflight("public") == 0
    assert _count("public", "synthetic-epsilon", "success", "2xx") == before + 2


def test_real_capacity_rejection_is_unchanged_and_classified(monkeypatch):
    _ready_public_dataset(monkeypatch)
    limiter = api_main._InferenceCapacityLimiter(api_main._INFERENCE_CAPACITY)
    monkeypatch.setattr(api_main, "_INFERENCE_CAPACITY_LIMITER", limiter)
    monkeypatch.setattr(api_main, "load_contract", lambda _release: SYNTHETIC_CONTRACT)
    monkeypatch.setattr(api_main, "_read_active_release_manifest", lambda _release: (Path("/nonexistent"), {}))
    assert limiter.try_acquire() and limiter.try_acquire()
    before = _count("public", "synthetic-zeta", "capacity_exceeded", "5xx")
    try:
        status, _h, body = _post_public("synthetic-zeta")
    finally:
        limiter.release()
        limiter.release()

    assert status == 503
    assert json.loads(body) == {
        "error_type": "inference_capacity_exceeded",
        "error_code": "INFERENCE_CAPACITY_EXCEEDED",
        "message": api_main.INFERENCE_CAPACITY_EXCEEDED.message,
    }
    assert _count("public", "synthetic-zeta", "capacity_exceeded", "5xx") == before + 1


def test_real_deadline_expiry_is_unchanged_and_worker_keeps_its_slot(monkeypatch):
    _ready_public_dataset(monkeypatch)
    limiter = api_main._InferenceCapacityLimiter(api_main._INFERENCE_CAPACITY)
    monkeypatch.setattr(api_main, "_INFERENCE_CAPACITY_LIMITER", limiter)
    monkeypatch.setattr(api_main, "_INFERENCE_EXECUTION_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(api_main, "load_contract", lambda _release: SYNTHETIC_CONTRACT)
    monkeypatch.setattr(api_main, "_read_active_release_manifest", lambda _release: (Path("/nonexistent"), {}))
    worker_release = threading.Event()
    worker_done = threading.Event()

    def _slow_worker():
        try:
            worker_release.wait(timeout=5)
            raise RuntimeError("synthetic late failure")
        finally:
            worker_done.set()

    monkeypatch.setattr(api_main, "_reconcile_runtime_cache_from_registry", _slow_worker)
    before = _count("public", "synthetic-eta", "timeout", "5xx")
    try:
        status, _h, body = _post_public("synthetic-eta")
        assert status == 503
        assert json.loads(body)["error_code"] == "INFERENCE_TIMEOUT"
        assert _count("public", "synthetic-eta", "timeout", "5xx") == before + 1
        # The handler finished; the model worker still holds its slot.
        assert _inflight("public") == 0
        assert limiter.try_acquire() is True
        assert limiter.try_acquire() is False
        limiter.release()
    finally:
        worker_release.set()
        assert worker_done.wait(timeout=5)
    # The worker's own finally released its slot (shortly after worker_done).
    for _ in range(100):
        if limiter.try_acquire():
            break
        threading.Event().wait(0.01)
    else:
        pytest.fail("worker never released its capacity slot")
    assert limiter.try_acquire() is True
    limiter.release()
    limiter.release()


def test_authorized_admin_surface_is_distinguished(monkeypatch):
    _authorized_admin(monkeypatch)
    prediction = {"dataset_slug": "synthetic-admin", "result": {"value": 1}}
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: prediction)
    before_admin = _count("admin", "synthetic-admin", "success", "2xx")
    before_public = _count("public", "synthetic-admin", "success", "2xx")

    status, _h, body = _post_admin("synthetic-admin")

    assert status == 200
    assert json.loads(body) == prediction
    assert _count("admin", "synthetic-admin", "success", "2xx") == before_admin + 1
    assert _count("public", "synthetic-admin", "success", "2xx") == before_public
    assert _inflight("admin") == 0


def test_unauthorized_admin_requests_are_not_observed(monkeypatch):
    monkeypatch.setattr(
        api_main,
        "_execute_governed_inference",
        lambda *_a, **_k: pytest.fail("unauthorized Admin must never execute inference"),
    )
    before_total = _total_requests()

    disabled_status, _h, disabled_body = _post_admin("synthetic-admin")
    monkeypatch.setenv("ATLAS_ADMIN_ENABLED", "true")
    monkeypatch.setattr(
        api_main,
        "_admin_auth_decision_from_request",
        lambda request: SimpleNamespace(authorized=False, reason="synthetic_denied"),
    )
    denied_status, _h, denied_body = _post_admin("synthetic-admin")

    assert (disabled_status, disabled_body) == (404, NOT_FOUND_BODY)
    assert (denied_status, denied_body) == (404, NOT_FOUND_BODY)
    assert _total_requests() == before_total


def test_unresolved_admin_dataset_uses_the_sentinel(monkeypatch):
    _authorized_admin(monkeypatch)

    def _unknown(_slug):
        raise api_main.DatasetUnavailableError()

    monkeypatch.setattr(api_main, "resolve_dataset", _unknown)
    before = _count("admin", obs.DATASET_UNRESOLVED, "client_error", "4xx")

    status, _h, _b = _post_admin("not-registered")

    assert status == 404
    assert _count("admin", obs.DATASET_UNRESOLVED, "client_error", "4xx") == before + 1


def test_hundreds_of_slugs_cannot_create_unbounded_series(monkeypatch):
    _ready_public_dataset(monkeypatch)
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: {"result": {}})
    before_overflow = _count("public", obs.DATASET_OVERFLOW, "success", "2xx")

    slugs = [f"synthetic-slug-{index}" for index in range(300)]
    for slug in slugs:
        assert _post_public(slug)[0] == 200

    admitted = set(slugs) & _label_values("dataset")
    assert len(admitted) == obs.MAX_DATASET_LABELS
    assert _count("public", obs.DATASET_OVERFLOW, "success", "2xx") == before_overflow + 300 - obs.MAX_DATASET_LABELS


def test_non_canonical_resolved_values_never_become_labels(monkeypatch):
    for raw in ("UPPER", "a/b", "x" * 65, "", None, "slug with space", "../etc", "ümlaut"):
        assert obs.dataset_label(raw) == obs.DATASET_UNRESOLVED
    assert obs.dataset_label("valid-slug-1") == "valid-slug-1"


def test_telemetry_failure_never_changes_the_inference_response(monkeypatch):
    _ready_public_dataset(monkeypatch)
    prediction = {"dataset_slug": "synthetic-theta", "result": {"ok": True}}
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: prediction)

    def _broken(*_args, **_kwargs):
        raise RuntimeError("synthetic telemetry failure")

    monkeypatch.setattr(obs.INFERENCE_REQUESTS, "labels", _broken)
    monkeypatch.setattr(obs.INFERENCE_INFLIGHT, "labels", _broken)

    status, _h, body = _post_public("synthetic-theta")

    assert status == 200
    assert json.loads(body) == prediction


def test_direct_handler_calls_return_the_exact_response_object(monkeypatch):
    _ready_public_dataset(monkeypatch)
    sentinel = {"dataset_slug": "synthetic-iota", "result": {"ok": True}}
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: sentinel)

    assert api_main.validate_dataset_inference_payload("synthetic-iota", payload={"MonthlyCharges": 1}) is sentinel


# ---------------------------------------------------------------------------
# Histogram contract
# ---------------------------------------------------------------------------


def test_histogram_buckets_are_static_monotonic_and_cover_the_deadline():
    buckets = obs.DURATION_BUCKETS
    assert list(buckets) == sorted(set(buckets))
    assert buckets[0] <= 0.05  # cached path
    assert any(1.0 <= bound <= 2.5 for bound in buckets)  # cold path
    assert api_main._INFERENCE_EXECUTION_DEADLINE_SECONDS in buckets
    assert buckets[-1] > api_main._INFERENCE_EXECUTION_DEADLINE_SECONDS


def test_exposed_histogram_buckets_are_cumulative(monkeypatch):
    _ready_public_dataset(monkeypatch)
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: {"result": {}})
    for start, end in ((0.0, 0.004), (1.0, 1.7), (2.0, 12.5), (3.0, 60.0)):
        _fake_clock(monkeypatch, start, end)
        _post_public("synthetic-kappa")

    families = {f.name: f for f in text_string_to_metric_families(obs.render_exposition()[0].decode())}
    buckets = [
        (float(sample.labels["le"]), sample.value)
        for sample in families["atlas_inference_duration_seconds"].samples
        if sample.name.endswith("_bucket") and sample.labels["dataset"] == "synthetic-kappa"
    ]
    buckets.sort()
    values = [value for _bound, value in buckets]
    assert values == sorted(values)
    assert buckets[-1] == (float("inf"), 4.0)
    assert dict(buckets)[0.005] == 1.0
    assert dict(buckets)[2.5] == 2.0
    assert dict(buckets)[15.0] == 3.0
    assert dict(buckets)[30.0] == 3.0


# ---------------------------------------------------------------------------
# Private exposition endpoint
# ---------------------------------------------------------------------------


def _enable_exporter(monkeypatch, secret=EXPORTER_SECRET, flag="true"):
    monkeypatch.setenv(obs.METRICS_ENABLED_ENV, flag)
    monkeypatch.setenv(obs.METRICS_BEARER_ENV, secret)


def _get_metrics(*headers, method="GET", path=METRICS_PATH):
    return _request(method, path, headers=headers)


def _assert_not_found(response):
    status, headers, body = response
    assert status == 404
    assert body == NOT_FOUND_BODY
    assert EXPORTER_SECRET not in body.decode()
    assert "location" not in headers


def test_exporter_is_disabled_by_default_even_with_a_valid_looking_credential(monkeypatch):
    monkeypatch.setenv(obs.METRICS_BEARER_ENV, EXPORTER_SECRET)
    _assert_not_found(_get_metrics(("Authorization", f"Bearer {EXPORTER_SECRET}")))


@pytest.mark.parametrize("flag", ("", "TRUE", "True", "1", "yes", " true", "true "))
def test_exporter_opt_in_flag_must_be_exactly_true(monkeypatch, flag):
    _enable_exporter(monkeypatch, flag=flag)
    _assert_not_found(_get_metrics(("Authorization", f"Bearer {EXPORTER_SECRET}")))


@pytest.mark.parametrize(
    "secret",
    ("", "   ", "short-secret", " " + EXPORTER_SECRET, EXPORTER_SECRET + " ", "has space " + EXPORTER_SECRET),
)
def test_exporter_requires_a_strong_configured_secret(monkeypatch, secret):
    _enable_exporter(monkeypatch, secret=secret)
    _assert_not_found(_get_metrics(("Authorization", f"Bearer {secret}")))


@pytest.mark.parametrize(
    "headers",
    (
        (),
        (("Authorization", f"Bearer {EXPORTER_SECRET}x"),),
        (("Authorization", f"bearer {EXPORTER_SECRET}"),),
        (("Authorization", f"Basic {EXPORTER_SECRET}"),),
        (("Authorization", EXPORTER_SECRET),),
        (("Authorization", f"Bearer  {EXPORTER_SECRET}"),),
        (("Authorization", f"Bearer {EXPORTER_SECRET}"), ("Authorization", f"Bearer {EXPORTER_SECRET}")),
        (("X-Atlas-Gateway-Token", GATEWAY_CREDENTIAL),),
    ),
)
def test_exporter_rejects_missing_wrong_malformed_or_duplicated_credentials(monkeypatch, headers):
    _enable_exporter(monkeypatch)
    _assert_not_found(_get_metrics(*headers))


@pytest.mark.parametrize("method", ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"))
def test_exporter_rejects_every_other_method_even_when_authorized(monkeypatch, method):
    _enable_exporter(monkeypatch)
    status, headers, body = _get_metrics(("Authorization", f"Bearer {EXPORTER_SECRET}"), method=method)
    assert status == 404
    assert method == "HEAD" or body == NOT_FOUND_BODY
    assert "location" not in headers


@pytest.mark.parametrize(
    "path",
    (METRICS_PATH + "/", "/metrics", "/_internal/observability", "/_internal/OBSERVABILITY/metrics"),
)
def test_no_alias_or_slash_variant_serves_the_exporter(monkeypatch, path):
    _enable_exporter(monkeypatch)
    _assert_not_found(_get_metrics(("Authorization", f"Bearer {EXPORTER_SECRET}"), path=path))


def test_authorized_exporter_serves_only_the_dedicated_registry(monkeypatch):
    _ready_public_dataset(monkeypatch)
    monkeypatch.setattr(api_main, "_execute_governed_inference", lambda *_a, **_k: {"result": {}})
    _post_public("synthetic-lambda")
    _enable_exporter(monkeypatch)

    status, headers, body = _get_metrics(("Authorization", f"Bearer {EXPORTER_SECRET}"))

    assert status == 200
    assert headers["content-type"].startswith("text/plain; version=")
    assert headers["cache-control"] == "no-store"
    text = body.decode("utf-8")
    assert EXPORTER_SECRET not in text
    assert GATEWAY_CREDENTIAL not in text
    families = {family.name: family.type for family in text_string_to_metric_families(text)}
    assert families == {
        "atlas_inference_requests": "counter",
        "atlas_inference_duration_seconds": "histogram",
        "atlas_inference_inflight_requests": "gauge",
    }
    assert "_created" not in text
    for line in text.splitlines():
        if line and not line.startswith("#"):
            assert line.startswith("atlas_inference_")
    assert 'dataset="synthetic-lambda"' in text


def test_exporter_is_hidden_from_openapi_and_dataset_metrics_route_is_unchanged():
    paths = {route.path for route in api_main.app.routes}
    assert "/datasets/{dataset_slug}/metrics" in paths
    assert "/metrics" not in paths
    assert METRICS_PATH in paths
    assert METRICS_PATH not in api_main.app.openapi()["paths"]


def test_only_bounded_label_names_exist():
    allowed = {"surface", "dataset", "result", "status_class", "le"}
    for family in obs.REGISTRY.collect():
        for sample in family.samples:
            assert set(sample.labels) <= allowed
    assert _label_values("surface") <= set(obs.SURFACES)

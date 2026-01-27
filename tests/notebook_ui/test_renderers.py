
# tests/notebook_ui/test_renderers.py

import copy

from atlas_dataflow.notebook_ui.renderers import (
    render_payload,
    render_kv_table_html,
    render_table_html,
)


def test_render_kv_table_html_basic():
    payload = {"a": 1, "b": "x"}
    html = render_kv_table_html(payload, title="metrics")
    assert "<table>" in html
    assert "metrics" in html
    assert "a" in html
    assert "1" in html


def test_render_table_html_list_of_dicts():
    payload = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    html = render_table_html(payload, title="rows")
    assert "<table>" in html
    assert "rows" in html
    assert "<th>a</th>" in html
    assert "<th>b</th>" in html


def test_render_payload_fallback_unknown_payload_to_text():
    payload = object()
    result = render_payload(payload)
    assert result.text
    assert result.html is None


def test_purity_renderer_does_not_mutate_input_dict():
    payload = {"a": {"nested": 1}, "b": [1, 2, 3]}
    before = copy.deepcopy(payload)
    _ = render_payload(payload)
    assert payload == before


def test_purity_renderer_does_not_mutate_input_list():
    payload = [{"a": 1}, {"a": 2}]
    before = copy.deepcopy(payload)
    _ = render_payload(payload)
    assert payload == before

# src/atlas_dataflow/notebook_ui/renderers.py
"""
Notebook UI Adapter (v1)

Objetivo:
- Renderizar payloads (dict/list/primitive) para saída legível em notebooks.
- NÃO altera payloads.
- NÃO infere semântica.
- NÃO acessa Manifest.
- NÃO importa o core de pipeline (Engine/RunContext/Steps/etc).

Saídas:
- HTML (string) quando possível
- fallback seguro em string (JSON pretty ou repr)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Optional
import copy
import html
import json


@dataclass(frozen=True)
class RenderResult:
    """Resultado de renderização (apenas apresentação)."""
    html: Optional[str]  # HTML string (quando aplicável)
    text: str            # fallback textual (sempre preenchido)


def _escape(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _as_pretty_json(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    except TypeError:
        return repr(payload)


def render_payload(payload: Any) -> RenderResult:
    """
    Renderizador genérico v1:
    - dict com chaves simples -> tenta tabela key/value
    - list[dict] homogêneo -> tabela
    - caso contrário -> JSON pretty (fallback)

    Garantia de pureza:
    - Verificada explicitamente apenas para tipos mutáveis suportados (dict, list).
    - Tipos opacos/imutáveis (ex.: object()) não são comparados por deepcopy.
    """
    # Pureza: só validamos não-mutação para tipos mutáveis comuns
    before = copy.deepcopy(payload) if isinstance(payload, (dict, list)) else None

    html_out: Optional[str] = None
    text_out: str

    if isinstance(payload, Mapping):
        html_out = render_kv_table_html(payload)
        text_out = _as_pretty_json(payload)
    elif isinstance(payload, Sequence) and not isinstance(payload, (str, bytes, bytearray)):
        html_out = render_table_html(payload)
        text_out = _as_pretty_json(payload)
    else:
        text_out = _as_pretty_json(payload)

    after = copy.deepcopy(payload) if isinstance(payload, (dict, list)) else None
    if before is not None and before != after:
        raise AssertionError("Notebook UI renderer mutated the input payload")

    return RenderResult(html=html_out, text=text_out)


def render_kv_table_html(payload: Mapping[str, Any], title: Optional[str] = None) -> str:
    """Renderiza dict como tabela key/value (HTML puro)."""
    rows = []
    for k in payload.keys():
        rows.append(
            f"<tr><td><code>{_escape(k)}</code></td><td>{_escape(payload[k])}</td></tr>"
        )

    heading = f"<h4>{_escape(title)}</h4>" if title else ""
    return (
        f"{heading}"
        "<table>"
        "<thead><tr><th>key</th><th>value</th></tr></thead>"
        "<tbody>"
        + "".join(rows) +
        "</tbody></table>"
    )


def render_table_html(payload: Sequence[Any], title: Optional[str] = None, max_rows: int = 50) -> str:
    """
    Renderiza list payload como tabela:
    - list[dict] -> colunas = união das chaves (ordem estável)
    - caso contrário -> tabela de 1 coluna (value)
    """
    items = list(payload)[:max_rows]

    heading = f"<h4>{_escape(title)}</h4>" if title else ""

    if not items:
        return f"{heading}<div><em>(empty)</em></div>"

    if all(isinstance(x, Mapping) for x in items):
        columns = []
        seen = set()
        for k in items[0].keys():
            columns.append(k); seen.add(k)
        for row in items[1:]:
            for k in row.keys():
                if k not in seen:
                    columns.append(k); seen.add(k)

        th = "".join(f"<th>{_escape(c)}</th>" for c in columns)
        trs = []
        for row in items:
            tds = "".join(f"<td>{_escape(row.get(c))}</td>" for c in columns)
            trs.append(f"<tr>{tds}</tr>")

        return (
            f"{heading}"
            "<table>"
            f"<thead><tr>{th}</tr></thead>"
            "<tbody>" + "".join(trs) + "</tbody>"
            "</table>"
        )

    trs = "".join(f"<tr><td>{_escape(x)}</td></tr>" for x in items)
    return (
        f"{heading}"
        "<table>"
        "<thead><tr><th>value</th></tr></thead>"
        f"<tbody>{trs}</tbody>"
        "</table>"
    )


def render_card_html(payload: Mapping[str, Any], title: str, subtitle: Optional[str] = None) -> str:
    """Renderiza um card simples em HTML (apresentação pura)."""
    st = f"<div style='opacity:0.75'>{_escape(subtitle)}</div>" if subtitle else ""
    body = render_kv_table_html(payload)
    return (
        "<div style='border:1px solid #ddd; border-radius:12px; padding:12px; margin:8px 0;'>"
        f"<h3 style='margin:0 0 6px 0;'>{_escape(title)}</h3>"
        f"{st}"
        f"{body}"
        "</div>"
    )

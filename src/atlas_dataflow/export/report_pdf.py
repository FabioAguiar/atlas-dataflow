"""
src/atlas_dataflow/export/report_pdf.py

MD to PDF conversion layer (engine-pluggable) — Atlas DataFlow
Milestone: M7 — Reporting (MD/PDF)
Issue: M7-02 — Export report.md to PDF

Rules:
- This module is NOT part of the semantic core.
- No inference, no recomputation, no Manifest access.
- Deterministic conversion for a fixed input + engine + options.
- Engines MUST be explicitly configured (no implicit default engine selection).

Engines:
- "simple": built-in, pure-Python minimal PDF generator (CI-safe, no external deps)
- "reportlab": optional engine if reportlab is installed
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Tuple


class PdfEngine(ABC):
    """Abstract base class for MD to PDF conversion engines."""

    name: str

    @abstractmethod
    def convert(self, md_path: Path, pdf_path: Path, **opts: Any) -> None:
        """Convert a Markdown file to PDF."""
        raise NotImplementedError


# -----------------------------------------------------------------------------
# Engine registry (explicit, no implicit defaults)
# -----------------------------------------------------------------------------

ENGINE_REGISTRY: Dict[str, PdfEngine] = {}


def register_engine(engine: PdfEngine) -> None:
    if not engine or not getattr(engine, "name", None):
        raise ValueError("Invalid PdfEngine: missing name")
    ENGINE_REGISTRY[engine.name] = engine


def get_engine(name: str) -> PdfEngine:
    try:
        return ENGINE_REGISTRY[name]
    except KeyError:
        raise KeyError(f"PDF engine not registered: {name}")


def convert_md_to_pdf(
    *,
    md_path: Path,
    pdf_path: Path,
    engine_name: str,
    engine_opts: Dict[str, Any] | None = None,
) -> None:
    """Convert a Markdown file to PDF using a configured engine."""
    if not md_path.exists():
        raise FileNotFoundError(f"report.md not found: {md_path}")

    engine = get_engine(engine_name)
    opts = engine_opts or {}

    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    engine.convert(md_path=md_path, pdf_path=pdf_path, **opts)


# -----------------------------------------------------------------------------
# Built-in engine (v1): simple (pure-Python, minimal PDF)
# -----------------------------------------------------------------------------

def _escape_pdf_text(s: str) -> str:
    # Escape parens and backslashes for PDF literal strings
    return s.replace("\\\\", "\\\\\\\\").replace("(", "\\\\(").replace(")", "\\\\)")


def _read_md_lines(md_path: Path) -> List[str]:
    lines: List[str] = []
    with md_path.open("r", encoding="utf-8") as f:
        for raw in f.readlines():
            line = raw.rstrip("\\n").rstrip("\\r")
            lines.append(line)
    return lines


def _normalize_md_to_plain(lines: List[str]) -> List[Tuple[int, str]]:
    """
    Convert Markdown lines to a simple (level, text) stream.

    Levels:
    - 1,2,3 for headings (#,##,###)
    - 0 for normal text
    """
    out: List[Tuple[int, str]] = []
    for ln in lines:
        s = ln.strip()
        if not s:
            out.append((0, ""))
            continue
        if s.startswith("# "):
            out.append((1, s[2:].strip()))
        elif s.startswith("## "):
            out.append((2, s[3:].strip()))
        elif s.startswith("### "):
            out.append((3, s[4:].strip()))
        elif s.startswith("- ") or s.startswith("* "):
            out.append((0, f"• {s[2:].strip()}"))
        else:
            out.append((0, s))
    return out


@dataclass(frozen=True)
class SimplePdfEngine(PdfEngine):
    """
    Minimal deterministic PDF generator.

    - One page (A4) by default.
    - Writes plain text with simple heading sizing.
    - No external dependencies.
    """
    name: str = "simple"

    def convert(self, md_path: Path, pdf_path: Path, **opts: Any) -> None:
        # Page size: A4 in points
        width = int(opts.get("page_width", 595))   # 8.27 in * 72
        height = int(opts.get("page_height", 842)) # 11.69 in * 72

        margin_left = int(opts.get("margin_left", 50))
        margin_top = int(opts.get("margin_top", 60))
        line_gap = int(opts.get("line_gap", 14))

        md_lines = _read_md_lines(md_path)
        items = _normalize_md_to_plain(md_lines)

        # Build PDF content stream with basic text drawing
        y = height - margin_top

        content_ops: List[str] = []
        content_ops.append("BT")  # begin text

        def set_font(size: int) -> None:
            content_ops.append(f"/F1 {size} Tf")

        def move_to(x: int, y_: int) -> None:
            content_ops.append(f"{x} {y_} Td")

        set_font(11)
        move_to(margin_left, y)

        for level, text in items:
            if y < 50:
                # v1 limit: one page only. If overflow, truncate deterministically.
                break

            if text == "":
                y -= line_gap
                content_ops.append(f"0 {-line_gap} Td")
                continue

            if level == 1:
                set_font(16)
            elif level == 2:
                set_font(14)
            elif level == 3:
                set_font(12)
            else:
                set_font(11)

            esc = _escape_pdf_text(text)
            content_ops.append(f"({esc}) Tj")
            y -= line_gap
            content_ops.append(f"0 {-line_gap} Td")

        content_ops.append("ET")  # end text
        content_stream = "\\n".join(content_ops).encode("latin-1", "replace")

        # Minimal PDF with xref
        objects: List[bytes] = []

        def obj(n: int, body: bytes) -> bytes:
            return f"{n} 0 obj\\n".encode() + body + b"\\nendobj\\n"

        objects.append(obj(1, b"<< /Type /Catalog /Pages 2 0 R >>"))
        objects.append(obj(2, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"))
        objects.append(
            obj(
                3,
                (
                    f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] "
                    f"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
                ).encode(),
            )
        )
        objects.append(obj(4, b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"))
        objects.append(
            obj(
                5,
                f"<< /Length {len(content_stream)} >>\\nstream\\n".encode()
                + content_stream
                + b"\\nendstream",
            )
        )

        out = bytearray()
        out.extend(b"%PDF-1.4\\n%\\xe2\\xe3\\xcf\\xd3\\n")

        offsets = [0]
        for o in objects:
            offsets.append(len(out))
            out.extend(o)

        xref_start = len(out)
        out.extend(f"xref\\n0 {len(offsets)}\\n".encode())
        out.extend(b"0000000000 65535 f \\n")
        for off in offsets[1:]:
            out.extend(f"{off:010d} 00000 n \\n".encode())

        out.extend(b"trailer\\n")
        out.extend(f"<< /Size {len(offsets)} /Root 1 0 R >>\\n".encode())
        out.extend(b"startxref\\n")
        out.extend(f"{xref_start}\\n".encode())
        out.extend(b"%%EOF\\n")

        pdf_path.write_bytes(bytes(out))


# -----------------------------------------------------------------------------
# Optional engine: reportlab (if installed)
# -----------------------------------------------------------------------------

class ReportLabEngine(PdfEngine):
    name = "reportlab"

    def convert(self, md_path: Path, pdf_path: Path, **opts: Any) -> None:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import (
                SimpleDocTemplate,
                Paragraph,
                Spacer,
                ListFlowable,
                ListItem,
            )
        except Exception as e:  # pragma: no cover
            raise RuntimeError("reportlab is required for the 'reportlab' engine") from e

        styles = getSampleStyleSheet()
        story = []

        with md_path.open("r", encoding="utf-8") as f:
            for raw in f.readlines():
                line = raw.rstrip()

                if not line:
                    story.append(Spacer(1, 8))
                    continue

                if line.startswith("# "):
                    story.append(Paragraph(f"<b>{line[2:]}</b>", styles["Heading1"]))
                elif line.startswith("## "):
                    story.append(Paragraph(f"<b>{line[3:]}</b>", styles["Heading2"]))
                elif line.startswith("### "):
                    story.append(Paragraph(f"<b>{line[4:]}</b>", styles["Heading3"]))
                elif line.startswith("- ") or line.startswith("* "):
                    story.append(ListFlowable([ListItem(Paragraph(line[2:], styles["Normal"]))]))
                else:
                    story.append(Paragraph(line, styles["Normal"]))

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )
        doc.build(story)


# Register built-in engines explicitly
register_engine(SimplePdfEngine())

# reportlab is optional; register only if available
try:  # pragma: no cover
    import reportlab  # type: ignore
    register_engine(ReportLabEngine())
except Exception:  # pragma: no cover
    pass


__all__ = [
    "PdfEngine",
    "ENGINE_REGISTRY",
    "register_engine",
    "get_engine",
    "convert_md_to_pdf",
]

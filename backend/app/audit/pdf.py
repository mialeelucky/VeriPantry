"""PDF version of the transaction report (audit-log §7.1).

The PDF is converted from the same Markdown as the HTML report, so all three
formats carry identical content. ReportLab's invariant mode removes creation
timestamps and random IDs: the same events always give the same PDF bytes.

Security: the converter may only load the font files below. Every other URL
(images, stylesheets, file:// paths) is refused, even if markup reached the
HTML despite escaping.
"""

from __future__ import annotations

import html
import io
import os
from pathlib import Path

from reportlab import rl_config
from xhtml2pdf import pisa
from xhtml2pdf.config.resources import ResourceAccessPolicy

from app.audit.render import markdown_to_html_body, render_markdown
from app.audit.store import AuditStore
from app.audit.views import View

rl_config.invariant = 1  # deterministic output: no timestamps or random document IDs

# Fonts with the glyphs the report uses (€, →, ä, ö, ·). The first pair found wins.
_FONT_CANDIDATES = [
    (os.environ.get("VERIPANTRY_PDF_FONT"), os.environ.get("VERIPANTRY_PDF_FONT_BOLD")),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
]
# Built-in PDF fonts lack some glyphs; substitutes used only when no TTF font is found.
_FALLBACK_GLYPHS = str.maketrans({"→": "->", "≥": ">=", "≤": "<="})


def _fonts() -> tuple[str, str] | None:
    for regular, bold in _FONT_CANDIDATES:
        if regular and bold and Path(regular).is_file() and Path(bold).is_file():
            return Path(regular).as_posix(), Path(bold).as_posix()
    return None


def _stylesheet(fonts: tuple[str, str] | None) -> str:
    face = ""
    family = "Helvetica"
    if fonts:
        face = (
            f"@font-face {{ font-family: Report; src: url('{fonts[0]}'); }}"
            f"@font-face {{ font-family: Report; font-weight: bold; src: url('{fonts[1]}'); }}"
        )
        family = "Report"
    return face + f"""
    @page {{ size: a4; margin: 1.6cm 1.5cm 1.8cm 1.5cm;
             @frame footer {{ -pdf-frame-content: footer; bottom: 0.8cm; margin-left: 1.5cm; margin-right: 1.5cm; height: 0.6cm; }} }}
    body {{ font-family: {family}; font-size: 9pt; line-height: 1.35; color: #1f1f1f; }}
    h1 {{ font-size: 15pt; margin: 0 0 6pt 0; }}
    h2 {{ font-size: 11.5pt; margin: 12pt 0 4pt 0; padding-bottom: 2pt; border-bottom: 0.5pt solid #bbbbbb; }}
    h3 {{ font-size: 10pt; margin: 8pt 0 3pt 0; }}
    p, li {{ margin: 0 0 3pt 0; }}
    table {{ width: 100%; margin: 3pt 0 6pt 0; }}
    th, td {{ border: 0.5pt solid #cccccc; padding: 3pt 4pt; text-align: left; vertical-align: top; }}
    th {{ background-color: #f2f2f2; }}
    blockquote {{ margin: 0 0 4pt 0; padding-left: 8pt; color: #555555; border-left: 1.5pt solid #cccccc; }}
    sub {{ font-size: 7pt; color: #777777; }}
    #footer {{ font-size: 7pt; color: #888888; text-align: right; }}
    """


def html_to_pdf(body_html: str, footer: str) -> bytes:
    fonts = _fonts()
    if fonts is None:
        body_html = body_html.translate(_FALLBACK_GLYPHS)
    allowed = set(fonts or ())

    def only_fonts(uri: str, rel: str) -> str:
        return uri if uri in allowed else ""

    document = (
        f"<html><head><meta charset='utf-8'><style>{_stylesheet(fonts)}</style></head><body>"
        f"<div id='footer'>{footer} · page <pdf:pagenumber/> of <pdf:pagecount/></div>"
        f"{body_html}</body></html>"
    )
    # Two layers: the converter's own policy (no network; local reads confined to
    # the font directory) and a whitelist of the exact font files.
    policy = ResourceAccessPolicy(
        allow_remote=False,
        base_dir=Path(fonts[0]).parent if fonts else None,
        extra_roots=(Path(fonts[1]).parent,) if fonts else (),
    )
    out = io.BytesIO()
    result = pisa.CreatePDF(document, dest=out, encoding="utf-8", link_callback=only_fonts, resource_policy=policy)
    if result.err:
        raise RuntimeError(f"PDF conversion failed with {result.err} error(s)")
    return out.getvalue()


def render_report_pdf(store: AuditStore, transaction_id: str, view: View, customer: str | None, jwks: list[dict]) -> bytes:
    body = markdown_to_html_body(render_markdown(store, transaction_id, view, customer, jwks))
    footer = html.escape(f"VeriPantry audit report · {transaction_id} · {view} view", quote=False)  # id comes from the agent
    return html_to_pdf(body, footer=footer)

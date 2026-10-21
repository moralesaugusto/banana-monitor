"""Renders a report's Markdown to PDF. Only the Markdown the reports use is handled: headings, bullet
lists, pipe tables and paragraphs, with **bold** and `code` inline."""

import io
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    Flowable,
    ListFlowable,
    ListItem,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

_BANANA = colors.HexColor("#e0a800")
_SPOT = colors.HexColor("#7a5200")


def _inline(text: str) -> str:
    text = escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r'<font face="Courier">\1</font>', text)


def _table(rows: list[list[str]], cell: ParagraphStyle) -> Table:
    data = [[Paragraph(_inline(c), cell) for c in row] for row in rows]
    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#fff3c4")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#c9ccd1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return table


def markdown_to_pdf(title: str, markdown: str) -> bytes:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10)
    h1 = ParagraphStyle("h1", parent=styles["Title"], textColor=_SPOT, alignment=0)
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], textColor=_SPOT, spaceBefore=12)
    h3 = ParagraphStyle("h3", parent=styles["Heading3"], spaceBefore=8)

    story: list[Flowable] = [Paragraph(_inline(title), h1), Spacer(1, 2 * mm)]
    bullets: list[str] = []
    rows: list[list[str]] = []

    def flush() -> None:
        if bullets:
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(_inline(b), body)) for b in bullets], bulletType="bullet", start="-"
                )
            )
            bullets.clear()
        if rows:
            story.append(_table(rows, cell))
            story.append(Spacer(1, 3 * mm))
            rows.clear()

    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells):
                rows.append(cells)
            continue
        flush()
        if not stripped:
            continue
        if stripped.startswith("### "):
            story.append(Paragraph(_inline(stripped[4:]), h3))
        elif stripped.startswith("## "):
            story.append(Paragraph(_inline(stripped[3:]), h2))
        elif stripped.startswith("# "):
            story.append(Paragraph(_inline(stripped[2:]), h2))
        elif stripped[:2] in ("- ", "* "):
            bullets.append(stripped[2:])
        else:
            story.append(Paragraph(_inline(stripped), body))
    flush()

    def footer(canvas: Canvas, doc: SimpleDocTemplate) -> None:
        canvas.saveState()
        canvas.setStrokeColor(_BANANA)
        canvas.setLineWidth(2)
        canvas.line(15 * mm, 12 * mm, A4[0] - 15 * mm, 12 * mm)
        canvas.setFont("Helvetica", 8)
        canvas.drawRightString(A4[0] - 15 * mm, 7 * mm, f"Banana - page {doc.page}")
        canvas.restoreState()

    buffer = io.BytesIO()
    SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=15 * mm, bottomMargin=18 * mm,
        title=title, author="Banana",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()

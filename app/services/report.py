import io
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "templates" / "report_template.txt"
)

pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
FONT = "HYGothic-Medium"


def _task_lines(tasks: list) -> str:
    if not tasks:
        return "- (없음)"
    lines = []
    for t in tasks:
        task = t.get("task", "")
        assignee = t.get("assignee", "") or "-"
        due = t.get("due", "") or "-"
        lines.append(f"- {task} (담당: {assignee}, 기한: {due})")
    return "\n".join(lines)


def _fill_template(analysis: dict) -> str:
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    return template.format(
        summary=analysis.get("summary", "") or "(요약 없음)",
        tasks=_task_lines(analysis.get("tasks", [])),
    )


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_text_report(analysis: dict) -> str:
    return _fill_template(analysis)


def build_pdf_report(analysis: dict) -> bytes:
    filled = _fill_template(analysis)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=20 * mm, bottomMargin=20 * mm,
        leftMargin=20 * mm, rightMargin=20 * mm,
    )
    body = ParagraphStyle("body", fontName=FONT, fontSize=11, leading=17)
    head = ParagraphStyle(
        "head", fontName=FONT, fontSize=14, leading=20, spaceBefore=10, spaceAfter=4
    )

    story = []
    for line in filled.splitlines():
        if line.strip() == "":
            story.append(Spacer(1, 6))
        elif line.startswith("[") or line.startswith("■"):
            story.append(Paragraph(_esc(line), head))
        else:
            story.append(Paragraph(_esc(line), body))

    doc.build(story)
    return buffer.getvalue()

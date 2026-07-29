import io
from datetime import datetime, timedelta, timezone

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.services.meeting_summary import EMPTY_VALUE, parse_structured_summary


pdfmetrics.registerFont(UnicodeCIDFont("HYGothic-Medium"))
FONT = "HYGothic-Medium"
INK = colors.HexColor("#252724")
MUTED = colors.HexColor("#747A73")
TEAL = colors.HexColor("#0F766E")
TEAL_SOFT = colors.HexColor("#E6F1EE")
PAPER = colors.HexColor("#F8F7F3")
LINE = colors.HexColor("#D8DDD9")
APRICOT_SOFT = colors.HexColor("#FFF0E2")
KST = timezone(timedelta(hours=9))


def _esc(value) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )


def _display_datetime(value) -> str:
    if isinstance(value, datetime):
        return value.astimezone(KST).strftime("%Y.%m.%d %H:%M")
    text = str(value or "").strip()
    if not text:
        return EMPTY_VALUE
    try:
        parsed = datetime.fromisoformat(text)
        return parsed.astimezone(KST).strftime("%Y.%m.%d %H:%M")
    except ValueError:
        return text


def _task_lines(tasks: list) -> list[str]:
    if not tasks:
        return ["- 등록된 실행 항목 없음"]
    lines = []
    for index, task in enumerate(tasks, start=1):
        lines.append(
            f"{index}. {task.get('task') or '업무명 없음'} "
            f"(담당: {task.get('assignee') or '미지정'}, "
            f"기한: {task.get('due') or '미정'}, "
            f"상태: {task.get('status') or '대기'})"
        )
    return lines


def build_text_report(analysis: dict) -> str:
    parsed = parse_structured_summary(
        analysis.get("summary", ""), analysis.get("title", "")
    )
    lines = [
        "[Noting 회의 결과 보고서]",
        "",
        f"보고서 번호: NTG-{int(analysis.get('id') or 0):04d}",
        f"회의 주제: {parsed['topic']}",
        f"회의 일시: {parsed['meeting_datetime']}",
        f"참석자: {parsed['participants']}",
        f"부서: {analysis.get('department') or EMPTY_VALUE}",
        f"등록 일시: {_display_datetime(analysis.get('created_at'))}",
        "",
        "1. 회의 목적",
        parsed["purpose"],
        "",
        "2. 핵심 논의",
        *[f"- {item}" for item in parsed["key_points"]],
        "",
        "3. 결정 사항",
        *[f"- {item}" for item in parsed["decisions"]],
        "",
        "4. 미결 사항",
        *[f"- {item}" for item in parsed["unresolved_items"]],
        "",
        "5. 업무 실행 계획",
        *_task_lines(analysis.get("tasks", [])),
    ]
    if analysis.get("masked_content"):
        lines.extend(("", "[부록] 회의록 전문", analysis["masked_content"]))
    return "\n".join(lines)


def _styles() -> dict:
    return {
        "eyebrow": ParagraphStyle(
            "eyebrow",
            fontName=FONT,
            fontSize=7.5,
            leading=10,
            textColor=TEAL,
            spaceAfter=4,
        ),
        "title": ParagraphStyle(
            "title",
            fontName=FONT,
            fontSize=22,
            leading=29,
            textColor=INK,
            spaceAfter=7,
        ),
        "subtitle": ParagraphStyle(
            "subtitle",
            fontName=FONT,
            fontSize=9,
            leading=14,
            textColor=MUTED,
            spaceAfter=12,
        ),
        "section": ParagraphStyle(
            "section",
            fontName=FONT,
            fontSize=12,
            leading=17,
            textColor=TEAL,
            spaceBefore=10,
            spaceAfter=7,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "body",
            fontName=FONT,
            fontSize=9.5,
            leading=15,
            textColor=INK,
            spaceAfter=5,
        ),
        "bullet": ParagraphStyle(
            "bullet",
            fontName=FONT,
            fontSize=9.3,
            leading=14,
            leftIndent=11,
            firstLineIndent=-7,
            textColor=INK,
            spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "small",
            fontName=FONT,
            fontSize=7.5,
            leading=11,
            textColor=MUTED,
        ),
        "table_head": ParagraphStyle(
            "table_head",
            fontName=FONT,
            fontSize=8,
            leading=11,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_body": ParagraphStyle(
            "table_body",
            fontName=FONT,
            fontSize=7.8,
            leading=11,
            textColor=INK,
        ),
        "table_center": ParagraphStyle(
            "table_center",
            fontName=FONT,
            fontSize=7.8,
            leading=11,
            textColor=INK,
            alignment=TA_CENTER,
        ),
    }


def _page_footer(canvas, doc):
    canvas.saveState()
    width, _ = A4
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(20 * mm, 14 * mm, width - 20 * mm, 14 * mm)
    canvas.setFont(FONT, 7)
    canvas.setFillColor(MUTED)
    canvas.drawString(20 * mm, 9 * mm, "Noting AI Meeting Report")
    canvas.drawRightString(width - 20 * mm, 9 * mm, f"{doc.page}")
    canvas.restoreState()


def _metadata_table(analysis: dict, parsed: dict, styles: dict) -> Table:
    rows = [
        [
            Paragraph("회의 주제", styles["small"]),
            Paragraph(_esc(parsed["topic"]), styles["body"]),
            Paragraph("보고서 번호", styles["small"]),
            Paragraph(
                f"NTG-{int(analysis.get('id') or 0):04d}",
                styles["body"],
            ),
        ],
        [
            Paragraph("회의 일시", styles["small"]),
            Paragraph(_esc(parsed["meeting_datetime"]), styles["body"]),
            Paragraph("부서", styles["small"]),
            Paragraph(_esc(analysis.get("department") or EMPTY_VALUE), styles["body"]),
        ],
        [
            Paragraph("참석자", styles["small"]),
            Paragraph(_esc(parsed["participants"]), styles["body"]),
            Paragraph("등록 일시", styles["small"]),
            Paragraph(
                _esc(_display_datetime(analysis.get("created_at"))),
                styles["body"],
            ),
        ],
    ]
    table = Table(
        rows,
        colWidths=[24 * mm, 67 * mm, 24 * mm, 47 * mm],
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), TEAL_SOFT),
                ("BACKGROUND", (2, 0), (2, -1), TEAL_SOFT),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("BACKGROUND", (3, 0), (3, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    return table


def _task_table(tasks: list, styles: dict) -> Table:
    header = [
        Paragraph("No.", styles["table_head"]),
        Paragraph("업무", styles["table_head"]),
        Paragraph("담당자", styles["table_head"]),
        Paragraph("기한", styles["table_head"]),
        Paragraph("요청사항", styles["table_head"]),
        Paragraph("상태", styles["table_head"]),
    ]
    rows = [header]
    if not tasks:
        rows.append(
            [
                Paragraph("-", styles["table_center"]),
                Paragraph("등록된 실행 항목이 없습니다.", styles["table_body"]),
                "",
                "",
                "",
                "",
            ]
        )
    else:
        for index, task in enumerate(tasks, start=1):
            rows.append(
                [
                    Paragraph(str(index), styles["table_center"]),
                    Paragraph(_esc(task.get("task") or "업무명 없음"), styles["table_body"]),
                    Paragraph(_esc(task.get("assignee") or "미지정"), styles["table_center"]),
                    Paragraph(_esc(task.get("due") or "미정"), styles["table_center"]),
                    Paragraph(_esc(task.get("request") or "-"), styles["table_body"]),
                    Paragraph(_esc(task.get("status") or "대기"), styles["table_center"]),
                ]
            )
    table = Table(
        rows,
        colWidths=[10 * mm, 47 * mm, 25 * mm, 28 * mm, 38 * mm, 18 * mm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), TEAL),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PAPER]),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("SPAN", (1, 1), (-1, 1)) if not tasks else ("LINEBELOW", (0, 0), (-1, 0), 0.8, TEAL),
            ]
        )
    )
    return table


def _add_list(story: list, values: list[str], styles: dict):
    for value in values:
        story.append(Paragraph(f"- {_esc(value)}", styles["bullet"]))


def build_pdf_report(analysis: dict) -> bytes:
    parsed = parse_structured_summary(
        analysis.get("summary", ""), analysis.get("title", "")
    )
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=18 * mm,
        bottomMargin=20 * mm,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
        title=f"{parsed['topic']} - Noting 회의 결과 보고서",
        author="Noting",
        subject="AI 회의 분석 결과",
    )

    story = [
        Paragraph("NOTING · AI MEETING REPORT", styles["eyebrow"]),
        Paragraph("회의 결과 보고서", styles["title"]),
        Paragraph(
            "회의록을 기반으로 AI가 정리한 핵심 내용과 실행 계획입니다.",
            styles["subtitle"],
        ),
        HRFlowable(width="100%", thickness=1.2, color=TEAL, spaceAfter=12),
        _metadata_table(analysis, parsed, styles),
        Spacer(1, 9),
        Paragraph("1. 회의 목적", styles["section"]),
        Paragraph(_esc(parsed["purpose"]), styles["body"]),
        Paragraph("2. 핵심 논의", styles["section"]),
    ]
    _add_list(story, parsed["key_points"], styles)
    story.append(Paragraph("3. 결정 사항", styles["section"]))
    _add_list(story, parsed["decisions"], styles)
    story.append(Paragraph("4. 미결 사항", styles["section"]))
    _add_list(story, parsed["unresolved_items"], styles)
    story.extend(
        [
            Paragraph("5. 업무 실행 계획", styles["section"]),
            _task_table(analysis.get("tasks", []), styles),
            Spacer(1, 8),
            Paragraph(
                "본 보고서는 마스킹된 회의록을 근거로 작성되며, 회의에 없는 내용은 포함하지 않습니다.",
                styles["small"],
            ),
        ]
    )

    transcript_content = str(analysis.get("masked_content") or "").strip()
    if transcript_content:
        story.extend(
            [
                PageBreak(),
                Paragraph("APPENDIX", styles["eyebrow"]),
                Paragraph("회의록 전문", styles["title"]),
                Paragraph(
                    "현재 사용자에게 허용된 범위에서 개인화된 마스킹 회의록입니다.",
                    styles["subtitle"],
                ),
                HRFlowable(width="100%", thickness=1, color=TEAL, spaceAfter=10),
            ]
        )
        for block in re_split_transcript(transcript_content):
            story.append(Paragraph(_esc(block), styles["body"]))

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)
    return buffer.getvalue()


def re_split_transcript(content: str) -> list[str]:
    blocks = [line.strip() for line in content.splitlines() if line.strip()]
    if blocks:
        return blocks
    return [content]

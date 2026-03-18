from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import models
from app.db import get_session
from app.dependencies import get_current_user
from app.permissions import is_at_least_user
from app.schemas.reports import AppearanceReport, AppearanceItem

router = APIRouter(prefix="/reports", tags=["reports"])


def _person_label(person: Optional[models.Person]) -> Optional[str]:
    if person is None:
        return None
    parts = [person.last_name, person.first_name, person.middle_name]
    return " ".join([p for p in parts if p]) or f"ID {person.person_id}"


async def _load_appearance_items(
    date_from: Optional[str],
    date_to: Optional[str],
    person_id: Optional[int],
    session: AsyncSession,
) -> Tuple[list[AppearanceItem], Optional[str], Optional[str], Optional[str]]:
    stmt = (
        select(models.Event, models.EventType, models.Person, models.Camera)
        .join(models.EventType, models.Event.event_type_id == models.EventType.event_type_id)
        .outerjoin(models.Person, models.Event.person_id == models.Person.person_id)
        .outerjoin(models.Camera, models.Event.camera_id == models.Camera.camera_id)
        .where(models.EventType.name == "face_recognized")
        .order_by(models.Event.event_ts.asc())
    )

    if person_id is not None:
        stmt = stmt.where(models.Event.person_id == person_id)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from)
            stmt = stmt.where(models.Event.event_ts >= dt_from)
        except ValueError:
            pass
    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to)
            stmt = stmt.where(models.Event.event_ts <= dt_to)
        except ValueError:
            pass

    res = await session.execute(stmt)
    rows = res.all()

    items: list[AppearanceItem] = []
    for ev, et, person, cam in rows:
        label = _person_label(person)
        items.append(
            AppearanceItem(
                event_id=ev.event_id,
                event_ts=str(ev.event_ts),
                camera_id=ev.camera_id,
                camera_name=cam.name if cam else None,
                person_id=ev.person_id,
                person_label=label,
                confidence=float(ev.confidence) if ev.confidence is not None else None,
            )
        )

    person_label = None
    if person_id is not None:
        person = await session.get(models.Person, person_id)
        person_label = _person_label(person) if person else f"ID {person_id}"

    return items, person_label, date_from, date_to


@router.get("/appearances", response_model=AppearanceReport)
async def appearances_report(
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    person_id: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
) -> AppearanceReport:
    if not is_at_least_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    items, _, _, _ = await _load_appearance_items(
        date_from=date_from,
        date_to=date_to,
        person_id=person_id,
        session=session,
    )

    return AppearanceReport(
        date_from=date_from,
        date_to=date_to,
        person_id=person_id,
        total=len(items),
        items=items,
    )


def _resolve_font_path() -> Optional[str]:
    base_dir = Path(__file__).resolve().parents[1]
    bundled = base_dir / "assets" / "fonts" / "Roboto-Regular.ttf"
    if bundled.exists():
        return str(bundled)
    windows_font = Path("C:/Windows/Fonts/arial.ttf")
    if windows_font.exists():
        return str(windows_font)
    linux_font = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if linux_font.exists():
        return str(linux_font)
    return None


def _format_period(date_from: Optional[str], date_to: Optional[str]) -> str:
    if date_from and date_to:
        return f"{date_from} — {date_to}"
    if date_from:
        return f"с {date_from}"
    if date_to:
        return f"по {date_to}"
    return "за весь период"


def _format_ts(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        normalized = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(normalized)
        return dt.strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return value


@router.get("/appearances/export")
async def appearances_report_export(
    format: str = Query(default="pdf", description="pdf|xlsx|docx"),
    date_from: Optional[str] = Query(default=None, description="ISO datetime start"),
    date_to: Optional[str] = Query(default=None, description="ISO datetime end"),
    person_id: Optional[int] = Query(default=None),
    session: AsyncSession = Depends(get_session),
    current_user: models.User = Depends(get_current_user),
):
    if not is_at_least_user(current_user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")

    fmt = format.lower().strip()
    if fmt not in {"pdf", "xlsx", "docx"}:
        raise HTTPException(status_code=400, detail="format must be pdf, xlsx or docx")

    items, person_label, df, dt = await _load_appearance_items(
        date_from=date_from,
        date_to=date_to,
        person_id=person_id,
        session=session,
    )

    period = _format_period(df, dt)
    person_title = person_label or "Все персоны"
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    filename = f"appearance-report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"

    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        wb = Workbook()
        ws = wb.active
        ws.title = "Отчёт"

        ws["A1"] = "Отчёт по появлению людей"
        ws.merge_cells("A1:E1")
        ws["A1"].font = Font(size=14, bold=True)
        ws["A1"].alignment = Alignment(horizontal="center")

        ws["A2"] = f"Период: {period}"
        ws.merge_cells("A2:E2")
        ws["A3"] = f"Персона: {person_title}"
        ws.merge_cells("A3:E3")
        ws["A4"] = f"Сформировано: {generated_at}"
        ws.merge_cells("A4:E4")

        headers = ["№", "Время", "Камера", "Персона", "Уверенность"]
        ws.append(headers)
        header_row = 5
        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)
        for col in range(1, 6):
            cell = ws.cell(row=header_row, column=col)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for idx, it in enumerate(items, start=1):
            ws.append(
                [
                    idx,
                    _format_ts(it.event_ts),
                    it.camera_name or f"Камера {it.camera_id}",
                    it.person_label or (f"ID {it.person_id}" if it.person_id else "-"),
                    f"{it.confidence:.2f}" if it.confidence is not None else "-",
                ]
            )

        ws.column_dimensions["A"].width = 6
        ws.column_dimensions["B"].width = 22
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 28
        ws.column_dimensions["E"].width = 14

        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if fmt == "docx":
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        doc = Document()
        title = doc.add_heading("Отчёт по появлению людей", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.add_paragraph(f"Период: {period}")
        doc.add_paragraph(f"Персона: {person_title}")
        doc.add_paragraph(f"Сформировано: {generated_at}")

        table = doc.add_table(rows=1, cols=5)
        table.style = "Table Grid"
        hdr_cells = table.rows[0].cells
        headers = ["№", "Время", "Камера", "Персона", "Уверенность"]
        for idx, text in enumerate(headers):
            run = hdr_cells[idx].paragraphs[0].add_run(text)
            run.bold = True

        for idx, it in enumerate(items, start=1):
            row_cells = table.add_row().cells
            row_cells[0].text = str(idx)
            row_cells[1].text = _format_ts(it.event_ts)
            row_cells[2].text = it.camera_name or f"Камера {it.camera_id}"
            row_cells[3].text = it.person_label or (f"ID {it.person_id}" if it.person_id else "-")
            row_cells[4].text = f"{it.confidence:.2f}" if it.confidence is not None else "-"

        buffer = BytesIO()
        doc.save(buffer)
        buffer.seek(0)

        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    # pdf
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_path = _resolve_font_path()
    font_name = "Helvetica"
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("CustomFont", font_path))
            font_name = "CustomFont"
        except Exception:
            pass

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontName=font_name,
        alignment=1,
        fontSize=16,
        spaceAfter=6,
    )
    text_style = ParagraphStyle("text", parent=styles["Normal"], fontName=font_name, fontSize=10, leading=12)

    elements = [
        Paragraph("Отчёт по появлению людей", title_style),
        Paragraph(f"Период: {period}", text_style),
        Paragraph(f"Персона: {person_title}", text_style),
        Paragraph(f"Сформировано: {generated_at}", text_style),
        Spacer(1, 8),
    ]

    header_style = ParagraphStyle(
        "header",
        parent=text_style,
        fontName=font_name,
        fontSize=9,
        leading=11,
        alignment=1,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "cell",
        parent=text_style,
        fontName=font_name,
        fontSize=8,
        leading=10,
    )

    data = [
        [
            Paragraph("№", header_style),
            Paragraph("Время", header_style),
            Paragraph("Камера", header_style),
            Paragraph("Персона", header_style),
            Paragraph("Уверенность", header_style),
        ]
    ]
    for idx, it in enumerate(items, start=1):
        data.append(
            [
                Paragraph(str(idx), cell_style),
                Paragraph(_format_ts(it.event_ts), cell_style),
                Paragraph(it.camera_name or f"Камера {it.camera_id}", cell_style),
                Paragraph(it.person_label or (f"ID {it.person_id}" if it.person_id else "-"), cell_style),
                Paragraph(f"{it.confidence:.2f}" if it.confidence is not None else "-", cell_style),
            ]
        )

    table = Table(data, colWidths=[14 * mm, 45 * mm, 28 * mm, 60 * mm, 25 * mm], repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, -1), font_name),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#D1D5DB")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
            ]
        )
    )

    elements.append(table)
    doc.build(elements)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

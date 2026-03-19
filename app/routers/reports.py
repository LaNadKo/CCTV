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
from app.schemas.reports import AppearanceItem, AppearanceReport

router = APIRouter(prefix="/reports", tags=["reports"])


def _person_label(person: Optional[models.Person]) -> Optional[str]:
    if person is None:
        return None
    parts = [person.last_name, person.first_name, person.middle_name]
    return " ".join([part for part in parts if part]) or f"ID {person.person_id}"


def _camera_label(camera: Optional[models.Camera], camera_id: Optional[int]) -> str:
    if camera and camera.name:
        return camera.name
    if camera_id is not None:
        return f"Камера {camera_id}"
    return "-"


def _format_period(date_from: Optional[str], date_to: Optional[str]) -> str:
    if date_from and date_to:
        return f"{date_from} - {date_to}"
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
        return datetime.fromisoformat(normalized).strftime("%d.%m.%Y %H:%M:%S")
    except Exception:
        return value


def _resolve_font_path() -> Optional[str]:
    bundled = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Roboto-Regular.ttf"
    if bundled.exists():
        return str(bundled)
    for candidate in (
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ):
        if candidate.exists():
            return str(candidate)
    return None


async def _load_appearance_items(
    date_from: Optional[str],
    date_to: Optional[str],
    person_id: Optional[int],
    session: AsyncSession,
) -> Tuple[list[AppearanceItem], Optional[str], Optional[str], Optional[str]]:
    stmt = (
        select(models.Event, models.Person, models.Camera, models.Group)
        .join(models.EventType, models.Event.event_type_id == models.EventType.event_type_id)
        .outerjoin(models.Person, models.Event.person_id == models.Person.person_id)
        .outerjoin(models.Camera, models.Event.camera_id == models.Camera.camera_id)
        .outerjoin(models.Group, models.Camera.group_id == models.Group.group_id)
        .where(models.EventType.name == "face_recognized")
        .order_by(models.Event.event_ts.asc())
    )

    if person_id is not None:
        stmt = stmt.where(models.Event.person_id == person_id)

    if date_from:
        try:
            stmt = stmt.where(models.Event.event_ts >= datetime.fromisoformat(date_from))
        except ValueError:
            pass

    if date_to:
        try:
            stmt = stmt.where(models.Event.event_ts <= datetime.fromisoformat(date_to))
        except ValueError:
            pass

    rows = (await session.execute(stmt)).all()
    items: list[AppearanceItem] = []
    for event, person, camera, group in rows:
        items.append(
            AppearanceItem(
                event_id=event.event_id,
                event_ts=event.event_ts.isoformat(),
                camera_id=event.camera_id,
                camera_name=camera.name if camera else None,
                camera_location=camera.location if camera else None,
                group_name=group.name if group else None,
                person_id=event.person_id,
                person_label=_person_label(person),
                confidence=float(event.confidence) if event.confidence is not None else None,
            )
        )

    person_label = None
    if person_id is not None:
        person = await session.get(models.Person, person_id)
        person_label = _person_label(person) if person else f"ID {person_id}"

    return items, person_label, date_from, date_to


def _appearance_row(index: int, item: AppearanceItem) -> list[str]:
    return [
        str(index),
        _format_ts(item.event_ts),
        item.camera_name or f"Камера {item.camera_id}",
        item.camera_location or "-",
        item.group_name or "-",
        item.person_label or (f"ID {item.person_id}" if item.person_id else "-"),
        f"{item.confidence:.2f}" if item.confidence is not None else "-",
    ]


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

    items, person_label, date_from_value, date_to_value = await _load_appearance_items(
        date_from=date_from,
        date_to=date_to,
        person_id=person_id,
        session=session,
    )

    period = _format_period(date_from_value, date_to_value)
    subject = person_label or "Все персоны"
    generated_at = datetime.now().strftime("%d.%m.%Y %H:%M:%S")
    filename = f"appearance-report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.{fmt}"
    headers = ["№", "Время", "Камера", "Локация", "Группа", "Персона", "Уверенность"]

    if fmt == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Отчет"

        sheet["A1"] = "Отчет по появлениям"
        sheet.merge_cells("A1:G1")
        sheet["A1"].font = Font(size=14, bold=True)
        sheet["A1"].alignment = Alignment(horizontal="center")

        sheet["A2"] = f"Период: {period}"
        sheet.merge_cells("A2:G2")
        sheet["A3"] = f"Персона: {subject}"
        sheet.merge_cells("A3:G3")
        sheet["A4"] = f"Сформировано: {generated_at}"
        sheet.merge_cells("A4:G4")

        sheet.append(headers)
        header_fill = PatternFill("solid", fgColor="1E3A8A")
        header_font = Font(color="FFFFFF", bold=True)
        for column in range(1, 8):
            cell = sheet.cell(row=5, column=column)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        for index, item in enumerate(items, start=1):
            sheet.append(_appearance_row(index, item))

        widths = {
            "A": 6,
            "B": 22,
            "C": 20,
            "D": 24,
            "E": 18,
            "F": 28,
            "G": 14,
        }
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width

        buffer = BytesIO()
        workbook.save(buffer)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if fmt == "docx":
        from docx import Document
        from docx.enum.text import WD_ALIGN_PARAGRAPH

        document = Document()
        title = document.add_heading("Отчет по появлениям", level=1)
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        document.add_paragraph(f"Период: {period}")
        document.add_paragraph(f"Персона: {subject}")
        document.add_paragraph(f"Сформировано: {generated_at}")

        table = document.add_table(rows=1, cols=len(headers))
        table.style = "Table Grid"
        for index, header in enumerate(headers):
            run = table.rows[0].cells[index].paragraphs[0].add_run(header)
            run.bold = True

        for index, item in enumerate(items, start=1):
            row = table.add_row().cells
            values = _appearance_row(index, item)
            for column, value in enumerate(values):
                row[column].text = value

        buffer = BytesIO()
        document.save(buffer)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_name = "Helvetica"
    font_path = _resolve_font_path()
    if font_path:
        try:
            pdfmetrics.registerFont(TTFont("CustomFont", font_path))
            font_name = "CustomFont"
        except Exception:
            pass

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontName=font_name,
        fontSize=16,
        alignment=1,
        spaceAfter=6,
    )
    text_style = ParagraphStyle(
        "text",
        parent=styles["Normal"],
        fontName=font_name,
        fontSize=9,
        leading=11,
    )
    header_style = ParagraphStyle(
        "header",
        parent=text_style,
        alignment=1,
        textColor=colors.white,
    )
    cell_style = ParagraphStyle(
        "cell",
        parent=text_style,
        fontSize=8,
        leading=10,
    )

    table_data = [[Paragraph(header, header_style) for header in headers]]
    for index, item in enumerate(items, start=1):
        table_data.append([Paragraph(value, cell_style) for value in _appearance_row(index, item)])

    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    elements = [
        Paragraph("Отчет по появлениям", title_style),
        Paragraph(f"Период: {period}", text_style),
        Paragraph(f"Персона: {subject}", text_style),
        Paragraph(f"Сформировано: {generated_at}", text_style),
        Spacer(1, 8),
    ]

    table = Table(
        table_data,
        colWidths=[12 * mm, 34 * mm, 30 * mm, 42 * mm, 32 * mm, 68 * mm, 22 * mm],
        repeatRows=1,
    )
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
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.HexColor("#F3F4F6")]),
            ]
        )
    )

    elements.append(table)
    document.build(elements)
    buffer.seek(0)
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

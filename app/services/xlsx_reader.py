"""Minimal .xlsx reader (stdlib only — no openpyxl required)."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    index = 0
    for ch in letters:
        index = index * 26 + (ord(ch.upper()) - 64)
    return index - 1


def _workbook_sheet_targets(archive: ZipFile) -> list[tuple[str, str]]:
    """Return [(sheet_title, worksheet_xml_path), ...] in workbook order."""
    rels_ns = {
        "pr": "http://schemas.openxmlformats.org/package/2006/relationships"
    }
    wb = ET.fromstring(archive.read("xl/workbook.xml"))
    rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rid_to_target = {
        rel.get("Id"): rel.get("Target")
        for rel in rels_root.findall("pr:Relationship", rels_ns)
    }

    sheets: list[tuple[str, str]] = []
    for sheet in wb.findall("m:sheets/m:sheet", NS):
        title = sheet.get("name") or ""
        rid = sheet.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = rid_to_target.get(rid or "")
        if not target:
            continue
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheets.append((title, target))
    return sheets


def _resolve_sheet_path(
    archive: ZipFile,
    *,
    sheet_name: str | None = None,
    sheet_index: int | None = None,
) -> str:
    sheets = _workbook_sheet_targets(archive)
    if not sheets:
        # Fallback: first worksheet xml in the archive
        fallback = next(
            (
                name
                for name in archive.namelist()
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml")
            ),
            None,
        )
        if fallback is None:
            raise ValueError("В файле Excel нет листа с данными.")
        return fallback

    if sheet_name is not None:
        wanted = sheet_name.casefold().strip()
        for title, path in sheets:
            if title.casefold().strip() == wanted:
                return path
        known = ", ".join(title for title, _ in sheets)
        raise ValueError(f"Лист «{sheet_name}» не найден. Доступны: {known}.")

    index = 0 if sheet_index is None else sheet_index
    if index < 0 or index >= len(sheets):
        raise ValueError(
            f"Индекс листа {index} вне диапазона 0…{len(sheets) - 1}."
        )
    return sheets[index][1]


def _parse_sheet_rows(sheet: ET.Element, shared: list[str]) -> list[list[str | None]]:
    rows: list[list[str | None]] = []
    expected_row = 1

    for row in sheet.findall("m:sheetData/m:row", NS):
        row_number = int(row.get("r", expected_row))
        while expected_row < row_number:
            rows.append([])
            expected_row += 1

        cells: dict[int, str | None] = {}
        max_index = -1
        for cell in row.findall("m:c", NS):
            ref = cell.get("r", "A1")
            index = _col_index(ref)
            max_index = max(max_index, index)
            cell_type = cell.get("t")
            value_node = cell.find("m:v", NS)
            inline = cell.find("m:is", NS)

            if cell_type == "inlineStr" and inline is not None:
                texts = [node.text or "" for node in inline.findall(".//m:t", NS)]
                cells[index] = "".join(texts)
            elif value_node is None:
                cells[index] = None
            elif cell_type == "s":
                cells[index] = shared[int(value_node.text)]
            else:
                cells[index] = value_node.text

        rows.append(
            [cells.get(i) for i in range(max_index + 1)] if max_index >= 0 else []
        )
        expected_row = row_number + 1

    return rows


def read_xlsx_rows(
    path: Path | str,
    *,
    sheet_name: str | None = None,
    sheet_index: int | None = None,
) -> list[list[str | None]]:
    """Read worksheet rows. By default uses the first sheet in workbook order."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Файл не найден: {path.name}")

    with ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", NS):
                texts = [node.text or "" for node in si.findall(".//m:t", NS)]
                shared.append("".join(texts))

        sheet_path = _resolve_sheet_path(
            archive, sheet_name=sheet_name, sheet_index=sheet_index
        )
        sheet = ET.fromstring(archive.read(sheet_path))
        return _parse_sheet_rows(sheet, shared)


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def parse_groups_rows(rows: list[list]) -> list[dict]:
    """Parse Группы.xlsx: title row, header row, then data."""
    if len(rows) < 2:
        raise ValueError("Файл групп пуст или повреждён.")

    header_index = None
    for index, row in enumerate(rows[:5]):
        cells = [_cell_text(value).lower() for value in row]
        if any(cell == "название" for cell in cells):
            header_index = index
            break

    if header_index is None:
        raise ValueError(
            "Не найдена строка заголовков. Ожидается колонка «Название»."
        )

    header = [_cell_text(value).lower() for value in rows[header_index]]

    def find_col(*aliases: str) -> int | None:
        for alias in aliases:
            if alias in header:
                return header.index(alias)
        return None

    name_col = find_col("название", "группа", "name")
    course_col = find_col("курс", "course")
    speciality_col = find_col(
        "направление подготовки (специальность)",
        "специальность",
        "направление подготовки",
        "speciality",
    )

    if name_col is None:
        raise ValueError("В файле нет колонки «Название».")

    items: list[dict] = []
    seen: set[str] = set()

    for row in rows[header_index + 1 :]:
        if name_col >= len(row):
            continue
        name = _cell_text(row[name_col])
        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)

        course = 1
        if course_col is not None and course_col < len(row):
            raw = _cell_text(row[course_col])
            if raw:
                try:
                    course = int(float(raw.replace(",", ".")))
                except ValueError as exc:
                    raise ValueError(
                        f"Некорректный курс у группы «{name}»: {raw}"
                    ) from exc
                if course not in range(1, 7):
                    raise ValueError(
                        f"Курс группы «{name}» должен быть от 1 до 6 (сейчас {course})."
                    )

        speciality = ""
        if speciality_col is not None and speciality_col < len(row):
            speciality = _cell_text(row[speciality_col])

        items.append({"name": name, "course": course, "speciality": speciality})

    if not items:
        raise ValueError("В файле не найдено ни одной группы.")

    return items


def parse_teachers_rows(rows: list[list]) -> list[dict]:
    """Parse Сотрудники.xlsx: header ФИО / Должность / Состояние."""
    if not rows:
        raise ValueError("Файл сотрудников пуст или повреждён.")

    header_index = None
    for index, row in enumerate(rows[:5]):
        cells = [_cell_text(value).lower() for value in row]
        if any(cell in {"фио", "ф.и.о.", "полное имя"} for cell in cells):
            header_index = index
            break

    if header_index is None:
        raise ValueError("Не найдена строка заголовков. Ожидается колонка «ФИО».")

    header = [_cell_text(value).lower() for value in rows[header_index]]

    def find_col(*aliases: str) -> int | None:
        for alias in aliases:
            if alias in header:
                return header.index(alias)
        return None

    name_col = find_col("фио", "ф.и.о.", "полное имя", "full_name")
    status_col = find_col("состояние", "статус", "status")

    if name_col is None:
        raise ValueError("В файле нет колонки «ФИО».")

    items: list[dict] = []
    seen: set[str] = set()

    for row in rows[header_index + 1 :]:
        if name_col >= len(row):
            continue
        full_name = _cell_text(row[name_col])
        if not full_name:
            continue

        if status_col is not None and status_col < len(row):
            status = _cell_text(row[status_col]).casefold()
            if status and status not in {"активный", "active", ""}:
                continue

        key = full_name.casefold()
        if key in seen:
            continue
        seen.add(key)

        items.append({"full_name": full_name})

    if not items:
        raise ValueError("В файле не найдено ни одного сотрудника.")

    return items


def _format_room_number(value) -> str:
    text = _cell_text(value)
    if not text:
        return ""
    try:
        number = float(text.replace(",", "."))
        if number.is_integer():
            return str(int(number))
        return str(number).rstrip("0").rstrip(".")
    except ValueError:
        return text


def parse_classrooms_rows(rows: list[list]) -> list[dict]:
    """Parse Перечень аудиторий.xlsx: Номер / Название / Этаж / Блок / Здание."""
    if len(rows) < 2:
        raise ValueError("Файл аудиторий пуст или повреждён.")

    header_index = None
    for index, row in enumerate(rows[:5]):
        cells = [_cell_text(value).lower() for value in row]
        if any(cell in {"номер", "аудитория", "кабинет"} for cell in cells):
            header_index = index
            break

    if header_index is None:
        raise ValueError(
            "Не найдена строка заголовков. Ожидается колонка «Номер»."
        )

    header = [_cell_text(value).lower() for value in rows[header_index]]

    def find_col(*aliases: str) -> int | None:
        for alias in aliases:
            if alias in header:
                return header.index(alias)
        return None

    number_col = find_col("номер", "аудитория", "кабинет", "name")
    title_col = find_col("название", "тип", "room_type")

    if number_col is None:
        raise ValueError("В файле нет колонки «Номер».")

    items: list[dict] = []
    seen: set[str] = set()

    for row in rows[header_index + 1 :]:
        if number_col >= len(row):
            continue
        name = _format_room_number(row[number_col])
        if not name:
            continue

        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)

        room_type = ""
        if title_col is not None and title_col < len(row):
            room_type = _cell_text(row[title_col])

        items.append({"name": name, "room_type": room_type, "seats": None})

    if not items:
        raise ValueError("В файле не найдено ни одной аудитории.")

    return items

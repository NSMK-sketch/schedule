"""Minimal .xlsx writer (stdlib only — no openpyxl required)."""

from __future__ import annotations

from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {sheet_overrides}
</Types>
"""

RELS_ROOT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>
"""

RELS_WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  {sheet_rels}
  <Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  <Relationship Id="rIdShared" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>
</Relationships>
"""

WORKBOOK = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    {sheets}
  </sheets>
</workbook>
"""

# Style indexes:
# 0 default
# 1 wrap top (lesson / plain multiline)
# 2 header bold center
# 3 period number center bold
# 4 day label bold
STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="4">
    <font><sz val="11"/><name val="Calibri"/></font>
    <font><b/><sz val="12"/><name val="Calibri"/></font>
    <font><b/><sz val="14"/><name val="Calibri"/></font>
    <font><b/><sz val="11"/><name val="Calibri"/></font>
  </fonts>
  <fills count="2">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
  </fills>
  <borders count="2">
    <border/>
    <border>
      <left style="thin"/><right style="thin"/><top style="thin"/><bottom style="thin"/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="5">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0"/>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1">
      <alignment wrapText="1" vertical="top"/>
    </xf>
    <xf numFmtId="0" fontId="1" fillId="0" borderId="1" xfId="0" applyFont="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center" wrapText="1"/>
    </xf>
    <xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyAlignment="1">
      <alignment horizontal="center" vertical="center"/>
    </xf>
    <xf numFmtId="0" fontId="3" fillId="0" borderId="1" xfId="0" applyFont="1" applyAlignment="1">
      <alignment vertical="center"/>
    </xf>
  </cellXfs>
</styleSheet>
"""

STYLE_DEFAULT = 0
STYLE_WRAP = 1
STYLE_HEADER = 2
STYLE_PERIOD = 3
STYLE_DAY = 4


def _col_letter(index: int) -> str:
    """0-based column index → Excel letters."""
    result = []
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        result.append(chr(65 + rem))
    return "".join(reversed(result))


def _xml_text(value: str) -> str:
    return escape(value, {"'": "&apos;", '"': "&quot;"})


def cell(value, style: int = STYLE_DEFAULT):
    """Plain cell helper."""
    if value is None or value == "":
        return None
    return {"text": str(value), "style": style}


def rich_cell(runs: list[dict], style: int = STYLE_WRAP):
    """Rich-text cell: runs = [{text, bold?, size?}]."""
    cleaned = [run for run in runs if run.get("text")]
    if not cleaned:
        return None
    return {"rich": cleaned, "style": style}


def _normalize_cell(raw):
    if raw is None or raw == "":
        return None
    if isinstance(raw, dict):
        return raw
    text = str(raw)
    style = STYLE_WRAP if "\n" in text else STYLE_DEFAULT
    return {"text": text, "style": style}


def _shared_plain_xml(value: str) -> str:
    if value != value.strip() or "\n" in value or "\t" in value:
        return f'<si><t xml:space="preserve">{_xml_text(value)}</t></si>'
    return f"<si><t>{_xml_text(value)}</t></si>"


def _shared_rich_xml(runs: list[dict]) -> str:
    parts = []
    for index, run in enumerate(runs):
        text = str(run.get("text") or "")
        if index > 0 and not text.startswith("\n"):
            # ensure line breaks between subject / teacher / room
            pass
        bold = "<b/>" if run.get("bold") else ""
        size = float(run.get("size") or 11)
        preserve = text != text.strip() or "\n" in text or text.startswith(" ")
        space = ' xml:space="preserve"' if preserve else ""
        parts.append(
            "<r>"
            f"<rPr>{bold}<sz val=\"{size}\"/><rFont val=\"Calibri\"/><family val=\"2\"/></rPr>"
            f"<t{space}>{_xml_text(text)}</t>"
            "</r>"
        )
    return f"<si>{''.join(parts)}</si>"


def build_xlsx(
    sheets: list[tuple[str, list[list]]],
    *,
    column_widths: list[float] | None = None,
    row_height: float | None = None,
) -> bytes:
    """Build an .xlsx workbook.

    Cell values may be plain strings or dicts from cell()/rich_cell().
    """
    if not sheets:
        raise ValueError("Нужен хотя бы один лист.")

    shared_entries: list[str] = []
    shared_index: dict[str, int] = {}

    def share_plain(value: str) -> int:
        key = f"p:{value}"
        if key in shared_index:
            return shared_index[key]
        index = len(shared_entries)
        shared_entries.append(_shared_plain_xml(value))
        shared_index[key] = index
        return index

    def share_rich(runs: list[dict]) -> int:
        key = "r:" + repr(
            [(run.get("text"), run.get("bold"), run.get("size")) for run in runs]
        )
        if key in shared_index:
            return shared_index[key]
        index = len(shared_entries)
        shared_entries.append(_shared_rich_xml(runs))
        shared_index[key] = index
        return index

    sheet_xmls: list[str] = []
    for _title, rows in sheets:
        max_col = max((len(row) for row in rows), default=1)
        row_xml = []
        for row_number, row in enumerate(rows, start=1):
            cells = []
            for col_index in range(max_col):
                raw = row[col_index] if col_index < len(row) else None
                normalized = _normalize_cell(raw)
                if normalized is None:
                    continue

                style = int(normalized.get("style", STYLE_DEFAULT))
                if "rich" in normalized:
                    sid = share_rich(normalized["rich"])
                else:
                    sid = share_plain(str(normalized.get("text") or ""))

                ref = f"{_col_letter(col_index)}{row_number}"
                cells.append(f'<c r="{ref}" t="s" s="{style}"><v>{sid}</v></c>')

            if cells:
                height_attr = (
                    f' ht="{row_height}" customHeight="1"'
                    if row_height and row_number > 1
                    else ""
                )
                # header row a bit taller too
                if row_number == 1:
                    height_attr = ' ht="22" customHeight="1"'
                row_xml.append(
                    f'<row r="{row_number}"{height_attr}>{"".join(cells)}</row>'
                )

        cols_xml = ""
        widths = column_widths
        if widths is None:
            widths = [12.0] + [18.0] * max(max_col - 1, 0)
        col_parts = []
        for index in range(max_col):
            width = widths[index] if index < len(widths) else 18.0
            col_parts.append(
                f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
            )
        cols_xml = f"<cols>{''.join(col_parts)}</cols>"

        dimension = f"A1:{_col_letter(max(max_col - 1, 0))}{max(len(rows), 1)}"
        sheet_xmls.append(
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<dimension ref="{dimension}"/>'
            f"{cols_xml}"
            "<sheetData>"
            f'{"".join(row_xml)}'
            "</sheetData>"
            "</worksheet>"
        )

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_entries)}" uniqueCount="{len(shared_entries)}">'
        f'{"".join(shared_entries)}'
        "</sst>"
    )

    sheet_overrides = []
    sheet_rels = []
    workbook_sheets = []
    for index, (title, _rows) in enumerate(sheets, start=1):
        safe_title = title.replace("/", "-").replace("\\", "-")[:31] or f"Лист{index}"
        sheet_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
        sheet_rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        workbook_sheets.append(
            f'<sheet name="{_xml_text(safe_title)}" sheetId="{index}" r:id="rId{index}"/>'
        )

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            "[Content_Types].xml",
            CONTENT_TYPES.format(sheet_overrides="\n  ".join(sheet_overrides)),
        )
        archive.writestr("_rels/.rels", RELS_ROOT)
        archive.writestr(
            "xl/_rels/workbook.xml.rels",
            RELS_WORKBOOK.format(sheet_rels="\n  ".join(sheet_rels)),
        )
        archive.writestr(
            "xl/workbook.xml",
            WORKBOOK.format(sheets="\n    ".join(workbook_sheets)),
        )
        archive.writestr("xl/styles.xml", STYLES)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        for index, xml in enumerate(sheet_xmls, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", xml)

    return buffer.getvalue()

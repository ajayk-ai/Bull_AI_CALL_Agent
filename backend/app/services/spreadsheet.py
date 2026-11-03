"""Reading uploaded CSV and Excel files into a header row and data rows. No database access."""

import csv
import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

from app.schemas.imports import ColumnMapping


class FileError(ValueError):
    pass


@dataclass
class Sheet:
    headers: list[str]
    # (spreadsheet row number, {header: text value}); the header row is the first non-empty row.
    rows: list[tuple[int, dict[str, str]]]


def cell_text(value: Any) -> str:
    """A cell as the text a person sees, so Excel's typed values do not leak through.

    450001.0 -> "450001", a date-time at midnight -> "2026-11-05", None -> "".
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time(0) else value.isoformat(timespec="minutes")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FileError("The CSV file is not UTF-8 or Windows-1252 text")


def _csv_rows(data: bytes) -> list[list[Any]]:
    text = _decode(data)
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return list(csv.reader(io.StringIO(text), dialect))


def _xlsx_rows(data: bytes, max_rows: int) -> list[list[Any]]:
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except (InvalidFileException, zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise FileError(f"Cannot read the Excel file: {exc}")
    try:
        sheet = workbook.worksheets[0]
        rows = []
        for row in sheet.iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > max_rows + 50:  # header and blank rows, plus enough to detect "too many rows"
                break
        return rows
    finally:
        workbook.close()


def read_sheet(file_name: str, data: bytes, max_rows: int) -> Sheet:
    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if extension == "csv":
        raw = _csv_rows(data)
    elif extension in ("xlsx", "xlsm"):
        raw = _xlsx_rows(data, max_rows)
    elif extension == "xls":
        raise FileError("Old .xls files are not supported. Save the file as .xlsx or .csv and upload again")
    else:
        raise FileError("Upload a .csv or .xlsx file")

    numbered = [(i, [cell_text(c) for c in row]) for i, row in enumerate(raw, start=1)]
    numbered = [(i, cells) for i, cells in numbered if any(cells)]
    if not numbered:
        raise FileError("The file is empty")

    _, header_cells = numbered[0]
    while header_cells and not header_cells[-1]:
        header_cells.pop()
    headers = [h or f"Column {n}" for n, h in enumerate(header_cells, start=1)]
    duplicates = sorted({h for h in headers if headers.count(h) > 1})
    if duplicates:
        raise FileError(f"Column headers must be unique; repeated: {', '.join(duplicates)}")

    rows = []
    for number, cells in numbered[1:]:
        extra = [c for c in cells[len(headers) :] if c]
        if extra:
            raise FileError(f"Row {number} has values beyond the last header column")
        rows.append((number, {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(headers)}))
    if len(rows) > max_rows:
        raise FileError(f"The file has more than {max_rows} data rows; split it into smaller files")
    return Sheet(headers=headers, rows=rows)


# Header words that identify the standard fields, checked in order.
_SUGGEST = {
    "phone": ("phone", "mobile", "contact no", "contact number", "cell", "whatsapp"),
    "language": ("language", "lang"),
    "company": ("company", "vendor name", "supplier name", "firm", "organisation", "organization"),
    "name": ("contact name", "contact person", "person", "name"),
}


def field_key(header: str) -> str:
    """'PO Number' -> 'po_number'."""
    key = re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")
    if not key or not key[0].isalpha():
        key = f"field_{key}" if key else "field"
    return key[:64]


def suggest_mapping(headers: list[str]) -> ColumnMapping | None:
    """A starting point for the user to correct; never applied without confirmation."""
    chosen: dict[str, str] = {}
    for target, words in _SUGGEST.items():
        for header in headers:
            normal = header.lower().strip()
            if header not in chosen.values() and any(w in normal for w in words):
                chosen[target] = header
                break
    if "name" not in chosen and "company" in chosen:
        chosen["name"] = chosen.pop("company")
    if "name" not in chosen or "phone" not in chosen:
        return None
    others = [h for h in headers if h not in chosen.values()]
    return ColumnMapping(**chosen, contact_fields={field_key(h): h for h in others})

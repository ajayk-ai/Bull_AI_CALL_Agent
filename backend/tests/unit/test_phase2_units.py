import copy
import io
from datetime import date, datetime

import pytest
from openpyxl import Workbook
from pydantic import ValidationError

from app.core.storage import LocalStorage, check_key
from app.schemas.campaigns import CallingWindow
from app.schemas.scripts import ScriptVersionBody
from app.seeds import scm_delivery
from app.services.scripts import context_problems
from app.services.spreadsheet import FileError, cell_text, field_key, read_sheet, suggest_mapping


def xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ---- spreadsheet reading ----


def test_cell_text_undoes_excel_typing():
    assert cell_text(450001.0) == "450001"
    assert cell_text(12.5) == "12.5"
    assert cell_text(datetime(2026, 11, 5)) == "2026-11-05"
    assert cell_text(date(2026, 11, 5)) == "2026-11-05"
    assert cell_text(None) == ""
    assert cell_text("  ABC  ") == "ABC"


def test_read_xlsx_with_blank_rows_and_typed_cells():
    data = xlsx(
        [
            [],
            ["Supplier Name", "Phone Number", "PO Number", "Original Delivery Date"],
            ["ABC Industries", 9876543210, 450001, datetime(2026, 11, 5)],
            [None, None, None, None],
            ["XYZ Castings", "+91 91234 56780", "450002", "2026-11-10"],
        ]
    )
    sheet = read_sheet("suppliers.xlsx", data, max_rows=100)
    assert sheet.headers == ["Supplier Name", "Phone Number", "PO Number", "Original Delivery Date"]
    assert [n for n, _ in sheet.rows] == [3, 5]  # spreadsheet row numbers, blank rows skipped
    assert sheet.rows[0][1] == {
        "Supplier Name": "ABC Industries",
        "Phone Number": "9876543210",
        "PO Number": "450001",
        "Original Delivery Date": "2026-11-05",
    }


def test_read_csv_semicolon_and_windows_encoding():
    data = "Name;Phone;City\nRavi Kumar;9876543210;Coimbatore\nSéan;9123456780;Chennai\n".encode("cp1252")
    sheet = read_sheet("list.csv", data, max_rows=100)
    assert sheet.headers == ["Name", "Phone", "City"]
    assert sheet.rows[1][1]["Name"] == "Séan"


@pytest.mark.parametrize(
    "name,data,message",
    [
        ("a.xls", b"x", "Old .xls"),
        ("a.pdf", b"x", ".csv or .xlsx"),
        ("a.csv", b"", "empty"),
        ("a.csv", b"Name,Name\nA,B\n", "unique"),
        ("a.csv", b"Name,Phone\nA,1,extra\n", "beyond the last header"),
        ("a.csv", b"Name\n" + b"A\n" * 6, "more than 5"),
        ("a.xlsx", b"not a zip", "Cannot read"),
    ],
)
def test_bad_files_rejected(name, data, message):
    with pytest.raises(FileError, match=message):
        read_sheet(name, data, max_rows=5)


def test_suggest_mapping():
    mapping = suggest_mapping(["Supplier Name", "Mobile No", "PO Number", "Material Description", "Language"])
    assert mapping.name == "Supplier Name" and mapping.phone == "Mobile No" and mapping.language == "Language"
    assert mapping.contact_fields == {"po_number": "PO Number", "material_description": "Material Description"}
    assert suggest_mapping(["Foo", "Bar"]) is None
    assert field_key("1st Contact #") == "field_1st_contact"


# ---- storage ----


@pytest.mark.parametrize("key", ["../etc/passwd", "/abs/path", "a/../b", "a//b", "", "a/.hidden"])
def test_storage_rejects_unsafe_keys(key):
    with pytest.raises(ValueError):
        check_key(key)


async def test_local_storage_round_trip(tmp_path):
    storage = LocalStorage(tmp_path)
    await storage.put("imports/x/file.enc", b"data")
    assert await storage.get("imports/x/file.enc") == b"data"
    await storage.delete("imports/x/file.enc")
    await storage.delete("imports/x/file.enc")  # deleting a missing key is not an error
    assert not (tmp_path / "imports/x/file.enc").exists()


# ---- script configuration ----


def scm_body(**config_changes) -> dict:
    config = copy.deepcopy(scm_delivery.CONFIG)
    config.update(config_changes)
    return {"config": config, "extraction_schema": copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA)}


def test_scm_seed_script_is_valid():
    body = ScriptVersionBody(**scm_body())
    assert [q.id for q in body.config.questions if q.condition] == ["delay_reason", "revised_date", "support_details"]


@pytest.mark.parametrize(
    "change,message",
    [
        ({"languages": {"default": "fr-FR", "allowed": ["fr-FR"]}}, "unsupported languages"),
        ({"languages": {"default": "hi-IN", "allowed": ["ta-IN"]}}, "default language"),
        ({"closing": {"statement": "Bye {contact.phone}"}}, "unknown placeholder"),
        ({"closing": {"statement": "PO {context.invoice_no}"}}, "unknown placeholder"),
        (
            {"questions": [{"id": "a", "prompt": "x", "type": "text", "condition": {"question_id": "b", "equals": 1}}]},
            "earlier question",
        ),
        ({"questions": [{"id": "a", "prompt": "x", "type": "choice"}]}, "need choices"),
        (
            {"questions": [{"id": "a", "prompt": "x", "type": "text"}, {"id": "a", "prompt": "y", "type": "text"}]},
            "twice",
        ),
        ({"questions": []}, "at least 1"),
        (
            {"questions": [{"id": "a", "prompt": "x", "type": "text", "validation": {"pattern": "("}}]},
            "regular expression",
        ),
    ],
)
def test_invalid_script_configs(change, message):
    with pytest.raises(ValidationError, match=message):
        ScriptVersionBody(**scm_body(**change))


def test_extraction_schema_must_be_valid_object_schema():
    with pytest.raises(ValidationError, match="not a valid JSON Schema"):
        ScriptVersionBody(config=scm_delivery.CONFIG, extraction_schema={"type": "objekt"})
    with pytest.raises(ValidationError, match="object with properties"):
        ScriptVersionBody(config=scm_delivery.CONFIG, extraction_schema={"type": "array"})


def test_context_problems():
    config = scm_delivery.CONFIG
    good = {"po_number": "450001", "material_description": "Hose", "original_delivery_date": "2026-11-05"}
    assert context_problems(config, {"items": [good]}) == []
    assert context_problems(config, {}) == ["no campaign data (items) for this contact"]
    problems = context_problems(config, {"items": [good, {**good, "po_number": "", "original_delivery_date": "5/11"}]})
    assert problems == [
        "item 2: PO Number is missing",
        "item 2: Original Delivery Date is not a date (YYYY-MM-DD): '5/11'",
    ]
    assert context_problems({"context_fields": []}, {}) == []


# ---- calling window ----


def test_calling_window_defaults_and_validation():
    window = CallingWindow()
    assert window.timezone == "Asia/Kolkata" and window.days == [0, 1, 2, 3, 4, 5]
    for bad in [{"timezone": "Mars/Base"}, {"days": [7]}, {"days": [1, 1]}, {"start": "18:00", "end": "09:00"}]:
        with pytest.raises(ValidationError):
            CallingWindow(**bad)

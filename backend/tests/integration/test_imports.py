import copy
import io

import pytest
from openpyxl import Workbook

from app.core.config import get_settings
from app.models.enums import Role
from app.seeds import scm_delivery

API = "/api/v1"
HEADERS = ["Supplier Name", "Phone Number", "PO Number", "Material Description", "Original Delivery Date", "Language"]
MAPPING = {
    "name": "Supplier Name",
    "phone": "Phone Number",
    "company": "Supplier Name",
    "language": "Language",
    "campaign_fields": {
        "po_number": "PO Number",
        "material_description": "Material Description",
        "original_delivery_date": "Original Delivery Date",
    },
}


def xlsx(rows: list[list]) -> bytes:
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


async def upload(client, actor, data: bytes, name: str = "suppliers.xlsx"):
    return await client.post(f"{API}/imports", headers=actor.headers, files={"file": (name, data)})


@pytest.fixture
async def manager(make_user, scm):
    return await make_user(Role.CAMPAIGN_MANAGER, scm)


@pytest.fixture
async def campaign(client, manager, make_user, scm) -> dict:
    """A draft SCM campaign using the published SCM script."""
    hod = await make_user(Role.HOD, scm)
    body = {
        "name": "SCM",
        "config": copy.deepcopy(scm_delivery.CONFIG),
        "extraction_schema": copy.deepcopy(scm_delivery.EXTRACTION_SCHEMA),
    }
    version_id = (await client.post(f"{API}/scripts", headers=manager.headers, json=body)).json()["versions"][0]["id"]
    await client.post(f"{API}/script-versions/{version_id}/submit", headers=manager.headers)
    await client.post(f"{API}/script-versions/{version_id}/approve", headers=hod.headers, json={})
    return (
        await client.post(
            f"{API}/campaigns", headers=manager.headers, json={"name": "Nov", "script_version_id": version_id}
        )
    ).json()


async def test_upload_returns_headers_preview_and_suggestion(client, manager):
    response = await upload(
        client,
        manager,
        xlsx([HEADERS, ["ABC Industries", 9876543210, 450001, "Hydraulic hose", "2026-11-05", "Tamil"]]),
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["headers"] == HEADERS and body["total_rows"] == 1
    assert body["preview"][0]["PO Number"] == "450001"
    assert body["suggested_mapping"]["phone"] == "Phone Number"
    assert body["suggested_mapping"]["name"] == "Supplier Name"


async def test_plain_contact_import_all_or_nothing(client, manager):
    rows = [
        ["Name", "Mobile", "Company", "Vendor Code"],
        ["Ravi", "9876543210", "ABC", "V001"],
        ["Meena", "12345", "XYZ", "V002"],  # bad phone
        ["Ravi again", "+91 98765 43210", "ABC", "V003"],  # repeated number
        ["", "9123456780", "PQR", "V004"],  # no name
    ]
    record = (await upload(client, manager, xlsx(rows))).json()
    mapping = {
        "name": "Name",
        "phone": "Mobile",
        "company": "Company",
        "contact_fields": {"vendor_code": "Vendor Code"},
    }

    dry = (
        await client.post(
            f"{API}/imports/{record['id']}/process", headers=manager.headers, json={"mapping": mapping, "dry_run": True}
        )
    ).json()
    assert dry["dry_run"] and dry["status"] == "uploaded"
    assert dry["error_rows"] == 3 and dry["valid_rows"] == 1
    assert {(e["row"], e["field"]) for e in dry["errors"]} == {(3, "Mobile"), (4, "Mobile"), (5, "Name")}
    assert "Same phone number as row 2" in next(e["message"] for e in dry["errors"] if e["row"] == 4)
    assert (await client.get(f"{API}/contacts", headers=manager.headers)).json()["total"] == 0

    # Real run with errors and default settings: nothing saved.
    failed = (
        await client.post(f"{API}/imports/{record['id']}/process", headers=manager.headers, json={"mapping": mapping})
    ).json()
    assert failed["status"] == "failed" and failed["new_contacts"] == 0
    assert (await client.get(f"{API}/contacts", headers=manager.headers)).json()["total"] == 0
    # A processed import cannot be processed again.
    again = await client.post(
        f"{API}/imports/{record['id']}/process", headers=manager.headers, json={"mapping": mapping}
    )
    assert again.status_code == 409

    report = await client.get(f"{API}/imports/{record['id']}/errors.csv", headers=manager.headers)
    assert report.status_code == 200 and "Invalid phone number: 12345" in report.text
    assert report.headers["content-disposition"] == 'attachment; filename="suppliers_errors.csv"'


async def test_skip_invalid_rows_and_duplicate_policies(client, manager):
    existing = await client.post(
        f"{API}/contacts",
        headers=manager.headers,
        json={"name": "Old Name", "phone": "9876543210", "custom_fields": {"keep": "yes"}},
    )
    rows = [
        ["Name", "Mobile", "Code"],
        ["New Name", "9876543210", "V1"],
        ["Fresh", "9123456780", "V2"],
        ["Bad", "1", "V3"],
    ]
    mapping = {"name": "Name", "phone": "Mobile", "contact_fields": {"code": "Code"}}

    first = (await upload(client, manager, xlsx(rows))).json()
    skipped = (
        await client.post(
            f"{API}/imports/{first['id']}/process",
            headers=manager.headers,
            json={"mapping": mapping, "skip_invalid_rows": True},
        )
    ).json()
    assert skipped["status"] == "completed"
    assert (skipped["new_contacts"], skipped["duplicate_rows"], skipped["updated_contacts"], skipped["error_rows"]) == (
        1,
        1,
        0,
        1,
    )
    old = (await client.get(f"{API}/contacts/{existing.json()['id']}", headers=manager.headers)).json()
    assert old["name"] == "Old Name"

    second = (await upload(client, manager, xlsx(rows[:2]))).json()
    updated = (
        await client.post(
            f"{API}/imports/{second['id']}/process",
            headers=manager.headers,
            json={"mapping": mapping, "duplicate_policy": "update"},
        )
    ).json()
    assert updated["updated_contacts"] == 1
    old = (await client.get(f"{API}/contacts/{existing.json()['id']}", headers=manager.headers)).json()
    assert old["name"] == "New Name" and old["custom_fields"] == {"keep": "yes", "code": "V1"}

    history = (await client.get(f"{API}/imports", headers=manager.headers)).json()
    assert history["total"] == 2


async def test_campaign_import_groups_po_lines_per_supplier(client, manager, campaign):
    rows = [
        HEADERS,
        ["ABC Industries", 9876543210, 450001, "Hydraulic hose", "2026-11-05", "Tamil"],
        ["ABC Industries", "+91 98765 43210", 450002, "Seal kit", "2026-11-08", "ta-IN"],
        ["XYZ Castings", 9123456780, 450010, "Bucket tooth", "2026-11-12", "Hindi"],
    ]
    record = (await upload(client, manager, xlsx(rows))).json()
    report = (
        await client.post(
            f"{API}/imports/{record['id']}/process",
            headers=manager.headers,
            json={"mapping": MAPPING, "campaign_id": campaign["id"]},
        )
    ).json()
    assert report["status"] == "completed", report
    assert (report["new_contacts"], report["campaign_contacts"], report["error_rows"]) == (2, 2, 0)

    members = (await client.get(f"{API}/campaigns/{campaign['id']}/contacts", headers=manager.headers)).json()["items"]
    abc = next(m for m in members if m["contact_name"] == "ABC Industries")
    assert [i["po_number"] for i in abc["context"]["items"]] == ["450001", "450002"]
    contacts = (await client.get(f"{API}/contacts", headers=manager.headers)).json()["items"]
    assert {c["name"]: c["language"] for c in contacts} == {"ABC Industries": "ta-IN", "XYZ Castings": "hi-IN"}
    # PO data belongs to the campaign, not the contact.
    assert all(c["custom_fields"] == {} for c in contacts)

    # The campaign is now complete enough to submit.
    submitted = await client.post(f"{API}/campaigns/{campaign['id']}/submit", headers=manager.headers)
    assert submitted.status_code == 200, submitted.text


async def test_campaign_import_checks_script_fields_and_dnc(client, manager, campaign):
    await client.post(f"{API}/dnc", headers=manager.headers, json={"phone": "9123456780", "reason": "Opted out"})
    rows = [
        HEADERS,
        ["ABC Industries", 9876543210, "", "Hydraulic hose", "2026-11-05", ""],  # no PO number
        ["XYZ Castings", 9123456780, 450010, "Bucket tooth", "12/11/2026", "Kannada"],  # bad date and language
        ["PQR Forge", 9000012345, 450020, "Pin", "2026-11-20", ""],
    ]
    record = (await upload(client, manager, xlsx(rows))).json()
    report = (
        await client.post(
            f"{API}/imports/{record['id']}/process",
            headers=manager.headers,
            json={"mapping": MAPPING, "campaign_id": campaign["id"], "dry_run": True},
        )
    ).json()
    messages = {(e["row"], e["message"]) for e in report["errors"]}
    assert (2, "PO Number is missing") in messages
    assert any(row == 3 and "unsupported language 'Kannada'" in msg for row, msg in messages)
    assert report["error_rows"] == 2 and report["valid_rows"] == 1

    # With row 3 (XYZ) corrected, its do-not-call status is reported as a warning, not an error.
    rows[2][5] = ""
    rows[2][4] = "2026-11-12"
    record = (await upload(client, manager, xlsx(rows))).json()
    report = (
        await client.post(
            f"{API}/imports/{record['id']}/process",
            headers=manager.headers,
            json={"mapping": MAPPING, "campaign_id": campaign["id"], "dry_run": True},
        )
    ).json()
    assert [w["row"] for w in report["warnings"]] == [3]
    assert "do-not-call" in report["warnings"][0]["message"]


async def test_import_mapping_and_permission_checks(client, manager, make_user, scm, campaign):
    record = (await upload(client, manager, xlsx([HEADERS, ["A", 9876543210, 1, "Pin", "2026-11-05", ""]]))).json()
    url = f"{API}/imports/{record['id']}/process"
    unknown = await client.post(
        url, headers=manager.headers, json={"mapping": {**MAPPING, "phone": "Telephone"}, "campaign_id": campaign["id"]}
    )
    assert unknown.status_code == 422 and unknown.json()["error"]["details"]["columns"] == ["Telephone"]
    no_campaign = await client.post(url, headers=manager.headers, json={"mapping": MAPPING})
    assert no_campaign.status_code == 422  # campaign fields without a campaign

    operator = await make_user(Role.OPERATOR, scm)
    assert (await upload(client, operator, xlsx([HEADERS]))).status_code == 403
    assert (await client.get(f"{API}/imports/{record['id']}", headers=operator.headers)).status_code == 200


async def test_upload_limits(client, manager, monkeypatch):
    monkeypatch.setattr(get_settings(), "import_max_bytes", 100)
    big = await upload(client, manager, b"Name,Phone\n" + b"A,9876543210\n" * 20, "big.csv")
    assert big.status_code == 422 and "larger than" in big.json()["error"]["message"]
    monkeypatch.setattr(get_settings(), "import_max_bytes", 10_000)
    wrong_type = await upload(client, manager, b"%PDF", "list.pdf")
    assert wrong_type.status_code == 422


async def test_stored_upload_is_encrypted(client, manager):
    from app.core.storage import get_storage
    from app.db.session import get_sessionmaker
    from app.models.campaigns import CampaignImport

    record = (await upload(client, manager, b"Name,Phone\nRavi,9876543210\n", "plain.csv")).json()
    async with get_sessionmaker()() as session:
        stored = await session.get(CampaignImport, record["id"])
    raw = await get_storage().get(stored.object_key)
    assert b"9876543210" not in raw and b"Ravi" not in raw

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Self

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.models.enums import ImportStatus
from app.schemas.common import ORMModel

Header = Annotated[str, StringConstraints(min_length=1, max_length=200)]
FieldKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,63}$")]


class ColumnMapping(BaseModel):
    """Which file column feeds which field. Values are column headers exactly as they appear in the file."""

    name: Header
    phone: Header
    company: Header | None = None
    language: Header | None = None
    # Stored on the contact, e.g. {"vendor_code": "Vendor Code"}.
    contact_fields: dict[FieldKey, Header] = Field(default_factory=dict)
    # Per-call campaign data, one item per row, e.g. {"po_number": "PO Number"}. Needs a campaign.
    campaign_fields: dict[FieldKey, Header] = Field(default_factory=dict)

    def headers_used(self) -> list[str]:
        fixed = [h for h in (self.name, self.phone, self.company, self.language) if h]
        return fixed + list(self.contact_fields.values()) + list(self.campaign_fields.values())


class DuplicatePolicy(StrEnum):
    SKIP = "skip"  # keep the existing contact unchanged
    UPDATE = "update"  # overwrite name, company and language; merge custom fields


class ImportProcess(BaseModel):
    mapping: ColumnMapping
    campaign_id: uuid.UUID | None = None
    duplicate_policy: DuplicatePolicy = DuplicatePolicy.SKIP
    # False (default): if any row has an error, nothing is saved. True: valid rows are saved, invalid ones listed.
    skip_invalid_rows: bool = False
    dry_run: bool = False

    @model_validator(mode="after")
    def _campaign_fields_need_campaign(self) -> Self:
        if self.mapping.campaign_fields and self.campaign_id is None:
            raise ValueError("campaign_fields can only be mapped when importing into a campaign")
        return self


class RowIssue(BaseModel):
    row: int
    field: str | None = None
    message: str
    level: str = "error"


class ImportUploadOut(BaseModel):
    id: uuid.UUID
    file_name: str
    headers: list[str]
    total_rows: int
    preview: list[dict[str, Any]]
    suggested_mapping: ColumnMapping | None


class ImportReport(BaseModel):
    id: uuid.UUID
    status: ImportStatus
    dry_run: bool
    total_rows: int
    valid_rows: int
    error_rows: int
    duplicate_rows: int
    new_contacts: int
    updated_contacts: int
    campaign_contacts: int
    errors: list[RowIssue]
    warnings: list[RowIssue]


class ImportOut(ORMModel):
    id: uuid.UUID
    department_id: uuid.UUID
    campaign_id: uuid.UUID | None
    file_name: str
    file_size_bytes: int | None
    status: ImportStatus
    headers: list
    column_mapping: dict | None
    options: dict
    total_rows: int
    valid_rows: int
    error_rows: int
    duplicate_rows: int
    new_contacts: int
    updated_contacts: int
    campaign_contacts: int
    uploaded_by_id: uuid.UUID | None
    created_at: datetime
    completed_at: datetime | None

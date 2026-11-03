import uuid
from datetime import datetime

from app.schemas.common import ORMModel


class AuditLogOut(ORMModel):
    id: uuid.UUID
    occurred_at: datetime
    actor_id: uuid.UUID | None
    actor_email: str | None
    department_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: uuid.UUID | None
    changes: dict
    ip_address: str | None
    request_id: str | None

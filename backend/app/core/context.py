"""Who made a request and from where; passed from the API layer into services for auditing."""

from dataclasses import dataclass


@dataclass
class RequestContext:
    ip_address: str | None
    user_agent: str | None
    request_id: str | None

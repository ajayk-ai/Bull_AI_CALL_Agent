"""Simulated telephony for development and tests. No network access, no phone rings.

Every call placed through it is stored with is_simulated = true. Settings refuse mock mode in production.
"""

import uuid

from app.providers.telephony.base import CallUrls


class MockTelephony:
    name = "mock"
    simulated = True

    def __init__(self) -> None:
        self.placed: list[tuple[str, CallUrls]] = []
        self.hung_up: list[str] = []

    async def place_call(self, to_e164: str, urls: CallUrls) -> str:
        self.placed.append((to_e164, urls))
        return f"mock-{uuid.uuid4().hex[:12]}"

    async def hangup(self, provider_call_id: str) -> None:
        self.hung_up.append(provider_call_id)

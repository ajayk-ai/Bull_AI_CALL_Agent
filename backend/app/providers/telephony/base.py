"""Provider-independent telephony interface.

A provider places a call and hangs it up. Everything provider-specific about the audio stream and webhooks
(message formats, sample rates) lives next to the adapter, in its own module, never in the call logic.
"""

from dataclasses import dataclass
from typing import Protocol


class TelephonyError(Exception):
    """The provider refused or failed a request. The message is safe to show to users."""


@dataclass(frozen=True)
class CallUrls:
    """Where the provider reaches us for this call; each URL carries the call's signed token."""

    flow_url: str
    status_url: str


class TelephonyProvider(Protocol):
    name: str
    # Calls placed through this provider are simulations, never real phone calls.
    simulated: bool

    async def place_call(self, to_e164: str, urls: CallUrls) -> str:
        """Start an outbound call. Returns the provider's call id."""
        ...

    async def hangup(self, provider_call_id: str) -> None:
        """End a call. Must not raise if the call has already ended."""
        ...

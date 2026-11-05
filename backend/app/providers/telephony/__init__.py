"""The telephony provider for the configured TELEPHONY_MODE."""

from functools import lru_cache

from app.core.config import get_settings
from app.providers.telephony.base import CallUrls, TelephonyError, TelephonyProvider
from app.providers.telephony.frejun import FreJunTelephony
from app.providers.telephony.mock import MockTelephony

__all__ = ["CallUrls", "TelephonyError", "TelephonyProvider", "get_telephony"]


@lru_cache
def get_telephony() -> TelephonyProvider:
    mode = get_settings().telephony_mode
    if mode == "live":
        return FreJunTelephony()
    if mode == "mock":
        return MockTelephony()
    raise TelephonyError("Calling is disabled on this server (TELEPHONY_MODE=disabled)")

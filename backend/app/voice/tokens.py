"""Signed tokens on the URLs we give the telephony provider.

FreJun does not sign its webhooks, so each URL carries a token naming the call, what the URL may be used for
and until when. A token for one call or purpose cannot be used for another, and the media token is accepted
only once (the call controller refuses a second media connection for a call).
"""

import base64
import hashlib
import hmac
import time
import uuid
from typing import Literal

from app.core.config import get_settings

Purpose = Literal["flow", "status", "media"]

LIFETIME_SECONDS: dict[str, int] = {
    "flow": 60 * 60,  # the call must be answered within this time
    "status": 24 * 60 * 60,  # late events such as recording-ready
    "media": 5 * 60,  # the provider connects right after the flow response
}


def _key() -> bytes:
    return hashlib.sha256(b"voice-url|" + get_settings().jwt_secret.get_secret_value().encode()).digest()


def _sig(call_id: uuid.UUID, purpose: str, expires: int) -> str:
    mac = hmac.new(_key(), f"{call_id}|{purpose}|{expires}".encode(), hashlib.sha256).digest()[:18]
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def make(call_id: uuid.UUID, purpose: Purpose, now: float | None = None) -> str:
    expires = int((now or time.time()) + LIFETIME_SECONDS[purpose])
    return f"{call_id}.{expires}.{_sig(call_id, purpose, expires)}"


def check(token: str | None, purpose: Purpose, now: float | None = None) -> uuid.UUID | None:
    """The call id if the token is genuine, for this purpose and unexpired; otherwise None."""
    if not token or len(token) > 120 or token.count(".") != 2:
        return None
    call_part, expires_part, sig = token.split(".")
    try:
        call_id = uuid.UUID(call_part)
        expires = int(expires_part)
    except ValueError:
        return None
    if not hmac.compare_digest(sig, _sig(call_id, purpose, expires)):
        return None
    if (now or time.time()) > expires:
        return None
    return call_id

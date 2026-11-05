"""FreJun (Teler) adapter.

Call flow, as used in production by PO Agent on this server:
1. place_call asks Teler to ring the number, giving our flow and status URLs.
2. When the call is answered, Teler POSTs to the flow URL; we answer with a "stream" action pointing at our
   media WebSocket (flow_response below).
3. Teler opens the WebSocket. Caller audio arrives as {"type": "audio", "data": {"audio_b64": ...}}, PCM16 at
   16 kHz. We send {"type": "audio", "audio_b64": ..., "chunk_id": n}, PCM16 at 8 kHz, and {"type": "clear"} to
   drop audio already queued (barge-in).
4. Status changes are POSTed to the status URL.
"""

import base64
import binascii
import json
import logging
from contextlib import suppress

from fastapi import WebSocketDisconnect
from teler import AsyncClient

from app.core.config import get_settings
from app.providers.telephony.base import CallUrls, TelephonyError

log = logging.getLogger(__name__)

NAME = "frejun"
CALLER_SAMPLE_RATE = 16000  # audio we receive
PHONE_SAMPLE_RATE = 8000  # audio we send
# The phone plays audio in 20 ms packets (320 bytes at 8 kHz). Every message must hold whole packets: a partial
# packet is padded with silence, which the caller hears as a click.
FRAME_BYTES = 320


def flow_response(media_ws_url: str) -> dict:
    return {
        "action": "stream",
        "ws_url": media_ws_url,
        "sample_rate": "16k",
        "chunk_size": 500,
        "record": True,
    }


HANGUP_RESPONSE = {"action": "hangup"}


def audio_message(pcm8k: bytes, chunk_id: int) -> dict:
    return {"type": "audio", "audio_b64": base64.b64encode(pcm8k).decode(), "chunk_id": chunk_id}


CLEAR_MESSAGE = {"type": "clear"}

# Status-callback values, mapped to our call statuses. FreJun's payload shapes differ by event, so the status is
# looked for under several keys; anything unrecognised is stored and otherwise ignored.
STATUS_KEYS = ("status", "event", "type", "call_status", "state")
CALL_ID_KEYS = ("call_id", "callId", "id", "call_sid", "CallSid")
RECORDING_KEYS = ("recording_url", "recordingUrl", "recording", "record_url", "audio_url")
STATUS_MAP = {
    "initiated": "dialing",
    "queued": "dialing",
    "ringing": "ringing",
    "answered": "in_progress",
    "in-progress": "in_progress",
    "in_progress": "in_progress",
    "completed": "completed",
    "hangup": "completed",
    "ended": "completed",
    "no-answer": "no_answer",
    "no_answer": "no_answer",
    "noanswer": "no_answer",
    "busy": "busy",
    "failed": "failed",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}


def find(payload: dict, keys: tuple[str, ...]) -> str | None:
    """First non-empty string value under any of `keys`, at the top level or one level down."""
    for scope in (payload, *(v for v in payload.values() if isinstance(v, dict))):
        for key in keys:
            value = scope.get(key)
            if isinstance(value, str | int) and str(value).strip():
                return str(value).strip()
    return None


def mapped_status(payload: dict) -> str | None:
    raw = find(payload, STATUS_KEYS)
    return STATUS_MAP.get(raw.lower()) if raw else None


class FreJunTelephony:
    name = NAME
    simulated = False

    def _client(self) -> AsyncClient:
        settings = get_settings()
        if not settings.teler_api_key:
            raise TelephonyError("FreJun is not configured (TELER_API_KEY)")
        return AsyncClient(api_key=settings.teler_api_key.get_secret_value(), timeout=settings.teler_timeout_seconds)

    async def place_call(self, to_e164: str, urls: CallUrls) -> str:
        settings = get_settings()
        try:
            async with self._client() as client:
                call = await client.voice.calls.create(
                    from_number=settings.frejun_phone_number,
                    to_number=to_e164,
                    flow_url=urls.flow_url,
                    status_callback_url=urls.status_url,
                    record=True,
                )
        except TelephonyError:
            raise
        except Exception as exc:
            log.exception("FreJun refused the call")
            raise TelephonyError(f"FreJun could not place the call: {type(exc).__name__}")
        return str(call.id)

    async def hangup(self, provider_call_id: str) -> None:
        try:
            async with self._client() as client:
                await client.voice.mutations.hangup(provider_call_id)
        except Exception as exc:  # the call may already have ended
            log.info("FreJun hangup of %s: %r", provider_call_id, exc)


class FreJunMediaStream:
    """The call's audio WebSocket, in the shape the call session expects (see voice.session.PhoneStream)."""

    frame_bytes = FRAME_BYTES

    def __init__(self, websocket) -> None:
        self.ws = websocket
        self.chunk_id = 0
        self.malformed = 0
        self.events: list[str] = []

    async def receive_audio(self) -> bytes | None:
        """Next chunk of caller audio (16 kHz PCM16), or None when the call's stream has closed."""
        while True:
            try:
                text = await self.ws.receive_text()
            except WebSocketDisconnect, RuntimeError:
                return None
            try:
                message = json.loads(text)
                if message.get("type") != "audio":
                    self.events.append(str(message.get("type")))
                    continue
                return base64.b64decode(message["data"]["audio_b64"], validate=True)
            except ValueError, KeyError, TypeError, AttributeError, binascii.Error:
                self.malformed += 1
                if self.malformed <= 3:
                    log.warning("Skipped malformed FreJun media message: %.120s", text)

    async def send_audio(self, pcm8k: bytes) -> None:
        await self.ws.send_text(json.dumps(audio_message(pcm8k, self.chunk_id)))
        self.chunk_id += 1

    async def clear(self) -> None:
        await self.ws.send_text(json.dumps(CLEAR_MESSAGE))

    async def close(self) -> None:
        with suppress(Exception):  # already closed
            await self.ws.close()

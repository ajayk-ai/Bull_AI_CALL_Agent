"""Scripted stand-ins for the voice engine and the phone line."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from app.voice import engine as ev

# 100 ms of 24 kHz PCM16 silence-ish audio (a small ramp so it is not all zeros)
AGENT_AUDIO = bytes(range(256)) * 18 + bytes(192)


def agent_says(text: str) -> list[ev.EngineEvent]:
    return [ev.AgentText(text), ev.AudioOut(AGENT_AUDIO), ev.AudioOut(AGENT_AUDIO), ev.TurnComplete()]


class FakeEngineSession:
    def __init__(self, on_text: Callable, on_audio: Callable) -> None:
        self.queue: asyncio.Queue = asyncio.Queue()
        self.texts: list[str] = []
        self.audio_chunks = 0
        self.tool_results: list[tuple[str, dict]] = []
        self._on_text = on_text
        self._on_audio = on_audio

    def emit(self, *events: ev.EngineEvent | None) -> None:
        for event in events:
            self.queue.put_nowait(event)

    async def send_audio(self, pcm16k: bytes) -> None:
        self.audio_chunks += 1
        self._on_audio(self, self.audio_chunks)

    async def send_text(self, text: str) -> None:
        self.texts.append(text)
        self._on_text(self, text)

    async def send_tool_result(self, call: ev.ToolCall, result: dict[str, Any]) -> None:
        self.tool_results.append((call.name, result))

    async def events(self) -> AsyncIterator[ev.EngineEvent]:
        while True:
            event = await self.queue.get()
            if event is None:
                return
            if isinstance(event, Exception):
                raise event
            yield event


class FakeEngine:
    """on_text(session, text) and on_audio(session, n) script the conversation by emitting events."""

    name = "fake"

    def __init__(self, on_text: Callable = lambda s, t: None, on_audio: Callable = lambda s, n: None) -> None:
        self.on_text = on_text
        self.on_audio = on_audio
        self.sessions: list[FakeEngineSession] = []
        self.configs: list[ev.EngineConfig] = []

    def describe(self, config: ev.EngineConfig) -> dict:
        return {
            "engine": "fake",
            "voice": config.voice_name,
            "language_hint": config.language,
            "tools": [t["name"] for t in config.tools],
        }

    @asynccontextmanager
    async def connect(self, config: ev.EngineConfig):
        self.configs.append(config)
        session = FakeEngineSession(self.on_text, self.on_audio)
        self.sessions.append(session)
        yield session


def supplier_conversation(outcome: str = "completed"):
    """Agent greets; after the caller's first audio the caller 'speaks'; the agent closes and ends the call."""

    def on_text(session: FakeEngineSession, text: str) -> None:
        if text.startswith("The call has just been answered"):
            session.emit(*agent_says("Hello, this is the Bull Machines calling assistant. Am I speaking with Ravi?"))

    def on_audio(session: FakeEngineSession, n: int) -> None:
        if n == 3:
            session.emit(ev.CallerText("Yes, the material will come on time."))
            session.emit(*agent_says("Thank you for confirming. Have a good day."))
            session.emit(ev.ToolCall(id="t1", name="end_call", args={"outcome": outcome, "note": "on time"}))

    return FakeEngine(on_text, on_audio)


class FakePhone:
    frame_bytes = 320

    def __init__(self) -> None:
        self.incoming: asyncio.Queue = asyncio.Queue()
        self.sent: list[bytes] = []
        self.clears = 0
        self.closed = False

    def caller_audio(self, chunks: int, size: int = 1600) -> None:
        for _ in range(chunks):
            self.incoming.put_nowait(b"\x01\x00" * (size // 2))

    def hang_up(self) -> None:
        self.incoming.put_nowait(None)

    async def receive_audio(self) -> bytes | None:
        return await self.incoming.get()

    async def send_audio(self, pcm8k: bytes) -> None:
        self.sent.append(pcm8k)

    async def clear(self) -> None:
        self.clears += 1

    async def close(self) -> None:
        self.closed = True

"""Voice engines: speech in, speech out, with transcripts and tool calls.

The call session talks to an engine only through EngineSession and the events below, so engines are
interchangeable (D1: Gemini Live first; a cascaded ASR/LLM/TTS engine can be added behind the same interface)
and the session can be tested with a scripted fake engine.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Protocol

from google import genai
from google.genai import types

from app.core.config import get_settings

log = logging.getLogger(__name__)


# ---- events ----


@dataclass
class AudioOut:
    pcm24k: bytes


@dataclass
class CallerText:
    text: str


@dataclass
class AgentText:
    text: str


@dataclass
class Interrupted:
    """The caller started speaking over the agent: audio already queued must be dropped."""


@dataclass
class TurnComplete:
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict[str, Any] = field(default_factory=dict)


EngineEvent = AudioOut | CallerText | AgentText | Interrupted | TurnComplete | ToolCall


@dataclass(frozen=True)
class EngineConfig:
    system_instruction: str
    voice_name: str
    language: str | None
    tools: list[dict]  # provider-neutral declarations: {"name", "description", "parameters" (JSON Schema)}
    silence_ms: int


class EngineSession(Protocol):
    async def send_audio(self, pcm16k: bytes) -> None: ...
    async def send_text(self, text: str) -> None: ...
    async def send_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None: ...
    def events(self) -> AsyncIterator[EngineEvent]: ...


class VoiceEngine(Protocol):
    name: str

    def describe(self, config: EngineConfig) -> dict[str, Any]:
        """The configuration recorded on the call (model, voice, voice-activity settings)."""
        ...

    def connect(self, config: EngineConfig) -> AbstractAsyncContextManager[EngineSession]: ...


# ---- Gemini Live ----


@cache
def _gemini_client() -> genai.Client:
    key = get_settings().gemini_api_key
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return genai.Client(api_key=key.get_secret_value())


class _GeminiSession:
    def __init__(self, session: Any):
        self._session = session

    async def send_audio(self, pcm16k: bytes) -> None:
        await self._session.send_realtime_input(audio=types.Blob(data=pcm16k, mime_type="audio/pcm;rate=16000"))

    async def send_text(self, text: str) -> None:
        await self._session.send_realtime_input(text=text)

    async def send_tool_result(self, call: ToolCall, result: dict[str, Any]) -> None:
        await self._session.send_tool_response(
            function_responses=[types.FunctionResponse(id=call.id, name=call.name, response=result)]
        )

    async def events(self) -> AsyncIterator[EngineEvent]:
        # session.receive() ends after each model turn, so it is called again. A pass that yields nothing means
        # the connection has closed.
        while True:
            got_any = False
            async for message in self._session.receive():
                got_any = True
                for event in _translate(message):
                    yield event
            if not got_any:
                return


def _translate(message: Any) -> list[EngineEvent]:
    events: list[EngineEvent] = []
    if message.data:
        events.append(AudioOut(message.data))
    if message.tool_call and message.tool_call.function_calls:
        for fc in message.tool_call.function_calls:
            events.append(ToolCall(id=fc.id or "", name=fc.name or "", args=dict(fc.args or {})))
    content = message.server_content
    if content:
        if content.input_transcription and content.input_transcription.text:
            events.append(CallerText(content.input_transcription.text))
        if content.output_transcription and content.output_transcription.text:
            events.append(AgentText(content.output_transcription.text))
        if content.interrupted:
            events.append(Interrupted())
        if content.turn_complete:
            events.append(TurnComplete())
    if message.go_away:
        log.warning("Gemini Live asked to close the session: %s", message.go_away)
    return events


class GeminiLiveEngine:
    name = "gemini_live"

    def describe(self, config: EngineConfig) -> dict[str, Any]:
        return {
            "engine": self.name,
            "model": get_settings().gemini_live_model,
            "voice": config.voice_name,
            "language_hint": config.language,
            "vad": {
                "start_sensitivity": "low",
                "end_sensitivity": "high",
                "prefix_padding_ms": 150,
                "silence_ms": config.silence_ms,
            },
            "tools": [t["name"] for t in config.tools],
        }

    def _live_config(self, config: EngineConfig) -> types.LiveConnectConfig:
        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=config.system_instruction,
            speech_config=types.SpeechConfig(
                language_code=config.language,
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=config.voice_name)
                ),
            ),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                automatic_activity_detection=types.AutomaticActivityDetection(
                    start_of_speech_sensitivity=types.StartSensitivity.START_SENSITIVITY_LOW,
                    end_of_speech_sensitivity=types.EndSensitivity.END_SENSITIVITY_HIGH,
                    prefix_padding_ms=150,
                    silence_duration_ms=config.silence_ms,
                )
            ),
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t["name"], description=t["description"], parameters_json_schema=t["parameters"]
                        )
                        for t in config.tools
                    ]
                )
            ]
            if config.tools
            else None,
        )

    @asynccontextmanager
    async def connect(self, config: EngineConfig) -> AsyncIterator[EngineSession]:
        model = get_settings().gemini_live_model
        async with _gemini_client().aio.live.connect(model=model, config=self._live_config(config)) as session:
            yield _GeminiSession(session)


@cache
def get_voice_engine() -> VoiceEngine:
    return GeminiLiveEngine()

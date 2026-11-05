import asyncio
import math
import struct
import time
import uuid
from datetime import UTC, datetime

import numpy as np
import pytest

from app.models.enums import CallStatus
from app.providers.telephony import frejun
from app.seeds import scm_delivery
from app.services.windows import in_window
from app.voice import engine as ev
from app.voice import tokens
from app.voice.audio import Downsampler
from app.voice.fsm import ConversationGuard, GuardAction, after_provider_end, can_move
from app.voice.prompt import TOOLS, build_instructions
from app.voice.session import CallSession
from tests.fakes import FakeEngine, FakePhone, agent_says, supplier_conversation

# ---- tokens ----


def test_tokens_are_bound_to_call_purpose_and_time():
    call_id = uuid.uuid4()
    token = tokens.make(call_id, "media", now=1000)
    assert tokens.check(token, "media", now=1100) == call_id
    assert tokens.check(token, "flow", now=1100) is None  # wrong purpose
    assert tokens.check(token, "media", now=1000 + 5 * 60 + 1) is None  # expired
    forged = token[:-2] + ("AA" if not token.endswith("AA") else "BB")
    assert tokens.check(forged, "media", now=1100) is None
    other = tokens.make(uuid.uuid4(), "media", now=1000)
    assert tokens.check(f"{call_id}.{other.split('.', 1)[1]}", "media", now=1100) is None  # signature of another call
    for junk in (None, "", "a.b.c", "x" * 200):
        assert tokens.check(junk, "media") is None


# ---- lifecycle ----


def test_call_lifecycle_rules():
    assert can_move(CallStatus.DIALING, CallStatus.RINGING)
    assert can_move(CallStatus.RINGING, CallStatus.IN_PROGRESS)
    assert not can_move(CallStatus.IN_PROGRESS, CallStatus.RINGING)  # late "ringing" is ignored
    assert not can_move(CallStatus.COMPLETED, CallStatus.FAILED)  # terminal stays terminal
    assert not can_move(CallStatus.IN_PROGRESS, CallStatus.NO_ANSWER)
    assert after_provider_end(CallStatus.IN_PROGRESS) == CallStatus.COMPLETED
    assert after_provider_end(CallStatus.RINGING) == CallStatus.NO_ANSWER


def guard(**overrides) -> ConversationGuard:
    values = dict(
        max_call_seconds=300,
        hard_max_seconds=900,
        silence_timeout_seconds=8,
        max_silence_prompts=2,
        max_turns=40,
        started_at=0.0,
    )
    return ConversationGuard(**{**values, **overrides})


def test_guard_silence_prompts_then_hangs_up():
    g = guard()
    assert g.check(5) is None
    assert g.check(8) == GuardAction.NUDGE_SILENCE
    assert g.check(16) == GuardAction.NUDGE_SILENCE
    assert g.check(24) == GuardAction.HANG_UP and g.end_reason == "silence"


def test_guard_counts_silence_from_end_of_agent_speech_and_resets_on_caller_speech():
    g = guard()
    g.agent_audio_until(20)  # the agent talks until t=20
    assert g.check(25) is None
    assert g.check(28) == GuardAction.NUDGE_SILENCE
    g.caller_spoke(30)
    assert g.silence_prompts == 0 and g.check(37) is None


def test_guard_wraps_up_then_cuts_off():
    g = guard(max_call_seconds=60)
    g.caller_spoke(59)
    assert g.check(60) == GuardAction.WRAP_UP and g.end_reason == "time_limit"
    assert g.check(80) is None  # grace period
    assert g.check(90) == GuardAction.HANG_UP


def test_guard_turn_limit_and_hard_limit():
    g = guard(max_turns=2)
    g.turn_completed()
    g.turn_completed()
    g.caller_spoke(1)
    assert g.check(2) == GuardAction.WRAP_UP and g.end_reason == "turn_limit"
    hard = guard(hard_max_seconds=100)
    hard.caller_spoke(99)
    assert hard.check(100) == GuardAction.HANG_UP and hard.end_reason == "hard_time_limit"


# ---- audio ----


def tone(freq: float, seconds: float = 0.5, rate: int = 24000) -> bytes:
    n = int(seconds * rate)
    return b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * freq * i / rate))) for i in range(n))


def rms(pcm: bytes) -> float:
    x = np.frombuffer(pcm, dtype=np.int16).astype(float)
    return float(np.sqrt(np.mean(x[200:] ** 2)))


def test_downsampler_keeps_speech_band_and_removes_aliasing():
    voice = Downsampler().process(tone(800))
    assert len(voice) == len(tone(800)) // 3  # 24 kHz -> 8 kHz
    assert 0.8 < rms(voice) / rms(tone(800)) < 1.2
    hiss = Downsampler().process(tone(6000))  # above 4 kHz would fold back into the phone band
    assert rms(hiss) < rms(tone(6000)) * 0.01


def test_downsampler_is_continuous_across_chunks():
    signal = tone(500, 0.3)
    whole = Downsampler().process(signal)
    d = Downsampler()
    parts = b"".join(d.process(signal[i : i + 962]) for i in range(0, len(signal), 962))
    assert parts == whole


# ---- provider payloads ----


def test_frejun_status_mapping():
    assert frejun.mapped_status({"status": "Ringing"}) == "ringing"
    assert frejun.mapped_status({"event": "no-answer"}) == "no_answer"
    assert frejun.mapped_status({"data": {"call_status": "completed"}}) == "completed"
    assert frejun.mapped_status({"status": "something-new"}) is None
    assert frejun.find({"data": {"recording_url": "https://r/1.mp3"}}, frejun.RECORDING_KEYS) == "https://r/1.mp3"


# ---- calling window ----


def test_calling_window():
    assert in_window({}, datetime(2026, 11, 5, 5, 0, tzinfo=UTC))  # Thu 10:30 IST
    assert not in_window({}, datetime(2026, 11, 5, 3, 0, tzinfo=UTC))  # 08:30 IST
    assert not in_window({}, datetime(2026, 11, 8, 6, 0, tzinfo=UTC))  # Sunday


# ---- prompt ----


def test_prompt_uses_script_contact_and_items():
    text = build_instructions(
        scm_delivery.CONFIG,
        {"name": "Ravi", "company": "ABC Industries"},
        [
            {"po_number": "450001", "material_description": "Hose", "original_delivery_date": "2026-11-20"},
            {"po_number": "450002", "material_description": "Seal", "original_delivery_date": "2026-11-22"},
        ],
        "en-IN",
    )
    assert "Am I speaking with Ravi from ABC Industries?" in text
    assert "1. PO Number (po_number): 450001" in text and "2. PO Number (po_number): 450002" in text
    assert "Ask only if the answer to [on_time] was no." in text
    assert "Start in English (India)." in text
    assert "{contact." not in text  # all contact placeholders filled
    assert 'end_call with outcome "opted_out"' in text
    assert TOOLS[0]["name"] == "end_call"


# ---- the call session ----


def make_session(phone: FakePhone, engine: FakeEngine, **guard_overrides) -> CallSession:
    config = ev.EngineConfig(system_instruction="x", voice_name="v", language=None, tools=TOOLS, silence_ms=300)
    return CallSession(phone, engine, config, guard(started_at=time.monotonic(), **guard_overrides))


async def test_session_conversation_ends_when_agent_ends_call():
    phone, engine = FakePhone(), supplier_conversation()
    phone.caller_audio(5)
    result = await make_session(phone, engine).run()

    assert result.end_reason == "agent_end_call" and result.we_hung_up
    assert result.outcome == "completed" and result.note == "on time"
    assert [(t["speaker"], t["text"].split(",")[0].split(".")[0]) for t in result.turns] == [
        ("agent", "Hello"),
        ("caller", "Yes"),
        ("agent", "Thank you for confirming"),
    ]
    session = engine.sessions[0]
    assert session.texts[0].startswith("The call has just been answered")
    assert session.tool_results == [("end_call", {"ok": True})]
    assert phone.sent and all(len(chunk) % 320 == 0 for chunk in phone.sent)  # whole 20 ms packets only
    assert phone.closed
    assert result.metrics["first_audio_ms"] is not None and result.metrics["reply_ms"]


async def test_session_caller_hangs_up():
    phone, engine = FakePhone(), supplier_conversation()
    phone.caller_audio(2)
    phone.hang_up()
    result = await make_session(phone, engine).run()
    assert result.end_reason == "caller_hangup" and not result.we_hung_up
    assert result.outcome is None


async def test_session_barge_in_clears_queued_audio():
    def on_text(session, text):
        if text.startswith("The call"):
            session.emit(ev.AgentText("Hello, I am calling about"), ev.AudioOut(b"\x00" * 4800), ev.Interrupted())
            session.emit(ev.CallerText("Who is this?"), *agent_says("I am the Bull Machines assistant."))
            session.emit(ev.ToolCall(id="t", name="end_call", args={"outcome": "refused"}))

    phone = FakePhone()
    result = await make_session(phone, FakeEngine(on_text)).run()
    assert phone.clears == 1
    assert result.turns[0] == {**result.turns[0], "speaker": "agent", "interrupted": True}
    assert result.metrics["interruptions"] == 1 and result.outcome == "refused"


async def test_session_unknown_tool_and_bad_outcome():
    def on_text(session, text):
        if text.startswith("The call"):
            session.emit(ev.ToolCall(id="a", name="transfer_money", args={}))
            session.emit(ev.ToolCall(id="b", name="end_call", args={"outcome": "made-up"}))

    phone = FakePhone()
    engine = FakeEngine(on_text)
    result = await make_session(phone, engine).run()
    assert engine.sessions[0].tool_results[0] == ("transfer_money", {"error": "unknown tool transfer_money"})
    assert result.outcome == "other"


async def test_session_silence_guard_nudges_then_hangs_up():
    phone, engine = FakePhone(), FakeEngine()
    result = await make_session(phone, engine, silence_timeout_seconds=1, max_silence_prompts=1).run()
    assert result.end_reason == "silence"
    assert any("silent" in t for t in engine.sessions[0].texts)


async def test_session_engine_failure_is_reported():
    def on_text(session, text):
        session.emit(RuntimeError("engine connection lost"))

    phone = FakePhone()
    result = await make_session(phone, FakeEngine(on_text)).run()
    assert result.end_reason == "error" and "engine connection lost" in result.error
    assert phone.closed


async def test_session_engine_closing_ends_call():
    def on_text(session, text):
        session.emit(*agent_says("Hello"), None)

    result = await make_session(FakePhone(), FakeEngine(on_text)).run()
    assert result.end_reason == "engine_closed"
    await asyncio.sleep(0)


# ---- Gemini Live engine, against the real SDK types (no network) ----


def test_gemini_session_config_builds_with_tool():
    from google.genai import types

    config = ev.EngineConfig(
        system_instruction="Be polite.", voice_name="Sulafat", language="ta-IN", tools=TOOLS, silence_ms=300
    )
    live = ev.GeminiLiveEngine()._live_config(config)
    assert live.response_modalities == [types.Modality.AUDIO]
    assert live.speech_config.voice_config.prebuilt_voice_config.voice_name == "Sulafat"
    assert live.speech_config.language_code == "ta-IN"
    declaration = live.tools[0].function_declarations[0]
    assert declaration.name == "end_call" and "outcome" in declaration.parameters_json_schema["properties"]
    assert live.realtime_input_config.automatic_activity_detection.silence_duration_ms == 300
    described = ev.GeminiLiveEngine().describe(config)
    assert described["model"] == "gemini-3.8-live" and described["tools"] == ["end_call"]


def test_gemini_messages_translate_to_events():
    from google.genai import types

    audio = types.LiveServerMessage(
        server_content=types.LiveServerContent(
            model_turn=types.Content(
                parts=[types.Part(inline_data=types.Blob(data=b"\x01\x02", mime_type="audio/pcm"))]
            ),
            output_transcription=types.Transcription(text="Hello"),
        )
    )
    assert ev._translate(audio) == [ev.AudioOut(b"\x01\x02"), ev.AgentText("Hello")]

    heard = types.LiveServerMessage(
        server_content=types.LiveServerContent(input_transcription=types.Transcription(text="ஆமாம்"), interrupted=True)
    )
    assert ev._translate(heard) == [ev.CallerText("ஆமாம்"), ev.Interrupted()]

    done = types.LiveServerMessage(server_content=types.LiveServerContent(turn_complete=True))
    assert ev._translate(done) == [ev.TurnComplete()]

    tool = types.LiveServerMessage(
        tool_call=types.LiveServerToolCall(
            function_calls=[types.FunctionCall(id="c1", name="end_call", args={"outcome": "completed"})]
        )
    )
    assert ev._translate(tool) == [ev.ToolCall(id="c1", name="end_call", args={"outcome": "completed"})]


# ---- calling mode settings ----


def test_calling_mode_rules():
    from pydantic import ValidationError

    from app.core.config import Settings

    base = {
        "database_url": "postgresql+psycopg://x/y",
        "jwt_secret": "j" * 40,
        "data_encryption_key": "k",
        "phone_hash_key": "p" * 40,
    }
    with pytest.raises(ValidationError, match="not allowed when APP_ENV=production"):
        Settings(**base, app_env="production", telephony_mode="mock")
    with pytest.raises(ValidationError, match="TELER_API_KEY, FREJUN_PHONE_NUMBER, GEMINI_API_KEY"):
        Settings(**base, telephony_mode="live", public_url="https://x.example.com", teler_api_key="", gemini_api_key="")
    with pytest.raises(ValidationError, match="must start with https://"):
        Settings(
            **base,
            telephony_mode="live",
            public_url="http://x",
            teler_api_key="t",
            frejun_phone_number="1",
            gemini_api_key="g",
        )
    live = Settings(
        **base,
        app_env="production",
        telephony_mode="live",
        public_url="https://x.example.com",
        teler_api_key="t",
        frejun_phone_number="+914400000000",
        gemini_api_key="g",
    )
    assert live.telephony_mode == "live"

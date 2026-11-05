"""One live call: phone audio <-> voice engine, under the conversation guards.

Three tasks run until one finishes: caller audio to the engine, engine output to the phone, and a watchdog
applying the guards. The session never touches the database; it returns a SessionResult for the call service to
store.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.voice import engine as ev
from app.voice.audio import Downsampler
from app.voice.fsm import ConversationGuard, GuardAction
from app.voice.prompt import GREETING_TRIGGER, OUTCOMES, SILENCE_NUDGE, WRAP_UP_NUDGE

log = logging.getLogger(__name__)

# 1600 bytes = 100 ms of 8 kHz PCM16. Agent audio is sent in chunks this size, except the first audio of each
# reply, which goes out at once so buffering never delays the start of a reply.
SEND_CHUNK_BYTES = 1600
PHONE_BYTES_PER_SECOND = 16000  # 8 kHz PCM16
WATCHDOG_INTERVAL = 0.5
# After end_call: wait until the agent has produced no audio for this long, then until it has played out.
END_QUIET_SECONDS = 1.0
MAX_DRAIN_SECONDS = 15.0


class PhoneStream(Protocol):
    frame_bytes: int

    async def receive_audio(self) -> bytes | None: ...
    async def send_audio(self, pcm8k: bytes) -> None: ...
    async def clear(self) -> None: ...
    async def close(self) -> None: ...


@dataclass
class SessionResult:
    end_reason: str  # agent_end_call | caller_hangup | silence | time_limit | turn_limit | hard_time_limit | error
    outcome: str | None = None  # reported by the agent through end_call
    note: str | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    @property
    def we_hung_up(self) -> bool:
        return self.end_reason not in ("caller_hangup",)


class CallSession:
    def __init__(
        self,
        phone: PhoneStream,
        engine: ev.VoiceEngine,
        config: ev.EngineConfig,
        guard: ConversationGuard,
        clock=time.monotonic,
    ) -> None:
        self.phone = phone
        self.engine = engine
        self.config = config
        self.guard = guard
        self.clock = clock
        self.t0 = clock()

        self.turns: list[dict[str, Any]] = []
        self.heard = ""
        self.said = ""
        self.end_reason: str | None = None
        self.outcome: str | None = None
        self.note: str | None = None
        self.finished = asyncio.Event()

        self.downsampler = Downsampler()
        self.buffer = b""
        self.replying = False
        self.play_until = 0.0  # when the audio already sent to the phone will have finished playing
        self.last_audio_out = 0.0
        self.metrics: dict[str, Any] = {
            "interruptions": 0,
            "reply_ms": [],
            "first_audio_ms": None,
            "caller_audio_seconds": 0.0,
            "agent_audio_seconds": 0.0,
        }
        self._caller_spoke_at: float | None = None
        self._end_task: asyncio.Task | None = None

    def _ms(self) -> int:
        return round((self.clock() - self.t0) * 1000)

    # ---- transcript ----

    def _flush_turn(self, interrupted: bool = False) -> None:
        for speaker, text in (("caller", self.heard.strip()), ("agent", self.said.strip())):
            if text:
                turn = {"turn_id": len(self.turns) + 1, "speaker": speaker, "text": text, "at_ms": self._ms()}
                if speaker == "agent" and interrupted:
                    turn["interrupted"] = True
                self.turns.append(turn)
        self.heard = self.said = ""

    def _finish(self, reason: str) -> None:
        if self.end_reason is None:
            self.end_reason = reason
        self.finished.set()

    # ---- phone -> engine ----

    async def _caller_to_engine(self, session: ev.EngineSession) -> None:
        while True:
            audio = await self.phone.receive_audio()
            if audio is None:
                self._finish("caller_hangup")
                return
            self.metrics["caller_audio_seconds"] += len(audio) / 32000
            await session.send_audio(audio)

    # ---- engine -> phone ----

    async def _send(self, end_of_reply: bool = False) -> bool:
        frame = self.phone.frame_bytes
        if end_of_reply and len(self.buffer) % frame:
            self.buffer += b"\0" * (frame - len(self.buffer) % frame)
        whole = len(self.buffer) - len(self.buffer) % frame
        if not whole:
            return False
        out, self.buffer = self.buffer[:whole], self.buffer[whole:]
        await self.phone.send_audio(out)
        now = self.clock()
        seconds = len(out) / PHONE_BYTES_PER_SECOND
        self.play_until = max(self.play_until, now) + seconds
        self.metrics["agent_audio_seconds"] += seconds
        self.guard.agent_audio_until(self.play_until)
        return True

    async def _engine_to_caller(self, session: ev.EngineSession) -> None:
        async for event in session.events():
            now = self.clock()
            match event:
                case ev.AudioOut(pcm24k=pcm):
                    self.last_audio_out = now
                    if self.metrics["first_audio_ms"] is None:
                        self.metrics["first_audio_ms"] = self._ms()
                    if self._caller_spoke_at is not None:
                        self.metrics["reply_ms"].append(round((now - self._caller_spoke_at) * 1000))
                        self._caller_spoke_at = None
                    self.buffer += self.downsampler.process(pcm)
                    if (not self.replying or len(self.buffer) >= SEND_CHUNK_BYTES) and await self._send():
                        self.replying = True
                case ev.CallerText(text=text):
                    self.heard += text
                    self._caller_spoke_at = now
                    self.guard.caller_spoke(now)
                case ev.AgentText(text=text):
                    self.said += text
                case ev.Interrupted():
                    # Barge-in: drop what is queued, here and on the phone.
                    self.metrics["interruptions"] += 1
                    self.buffer = b""
                    self.replying = False
                    self.downsampler.reset()
                    self.play_until = now
                    await self.phone.clear()
                    self._flush_turn(interrupted=True)
                case ev.TurnComplete():
                    await self._send(end_of_reply=True)
                    self.replying = False
                    self._flush_turn()
                    self.guard.turn_completed()
                case ev.ToolCall() as call:
                    await self._handle_tool(session, call)
        # The engine closed its side.
        self._finish(self.end_reason or "engine_closed")

    async def _handle_tool(self, session: ev.EngineSession, call: ev.ToolCall) -> None:
        if call.name != "end_call":
            log.warning("Agent called unknown tool %r", call.name)
            await session.send_tool_result(call, {"error": f"unknown tool {call.name}"})
            return
        outcome = call.args.get("outcome")
        self.outcome = outcome if outcome in OUTCOMES else "other"
        self.note = str(call.args.get("note") or "")[:500] or None
        await session.send_tool_result(call, {"ok": True})
        if self._end_task is None:
            self._end_task = asyncio.create_task(self._end_after_playback())

    async def _end_after_playback(self) -> None:
        """Let the agent's closing words finish: no new audio for END_QUIET_SECONDS, then the queue plays out."""
        deadline = self.clock() + MAX_DRAIN_SECONDS
        # Polls: "no audio for a while" is a quiet period, not an event that could be signalled.
        while self.clock() < deadline and self.clock() - self.last_audio_out < END_QUIET_SECONDS:  # noqa: ASYNC110
            await asyncio.sleep(0.1)
        await self._send(end_of_reply=True)
        remaining = min(max(0.0, self.play_until - self.clock()), max(0.0, deadline - self.clock()))
        await asyncio.sleep(remaining + 0.3)
        self._finish("agent_end_call")

    # ---- guards ----

    async def _watchdog(self, session: ev.EngineSession) -> None:
        while not self.finished.is_set():
            await asyncio.sleep(WATCHDOG_INTERVAL)
            action = self.guard.check(self.clock())
            if action == GuardAction.NUDGE_SILENCE:
                await session.send_text(SILENCE_NUDGE)
            elif action == GuardAction.WRAP_UP:
                await session.send_text(WRAP_UP_NUDGE)
            elif action == GuardAction.HANG_UP:
                self._finish(self.guard.end_reason or "time_limit")
                return

    # ---- run ----

    async def run(self) -> SessionResult:
        error = None
        try:
            async with self.engine.connect(self.config) as session:
                await session.send_text(GREETING_TRIGGER)
                tasks = [
                    asyncio.create_task(self._caller_to_engine(session)),
                    asyncio.create_task(self._engine_to_caller(session)),
                    asyncio.create_task(self._watchdog(session)),
                ]
                finished = asyncio.create_task(self.finished.wait())
                try:
                    done, _ = await asyncio.wait([*tasks, finished], return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        if task is not finished and not task.cancelled() and task.exception():
                            raise task.exception()
                finally:
                    for task in (*tasks, finished):
                        task.cancel()
                    await asyncio.gather(*tasks, finished, return_exceptions=True)
        except Exception as exc:
            log.exception("Call session failed")
            error = f"{type(exc).__name__}: {exc}"[:500]
            self.end_reason = "error"
        finally:
            if self._end_task:
                self._end_task.cancel()
            await self.phone.close()

        self._flush_turn()
        self.metrics["duration_seconds"] = round(self.clock() - self.t0, 1)
        self.metrics["turns"] = self.guard.turns
        self.metrics["silence_prompts"] = self.guard.silence_prompts
        self.metrics["caller_audio_seconds"] = round(self.metrics["caller_audio_seconds"], 1)
        self.metrics["agent_audio_seconds"] = round(self.metrics["agent_audio_seconds"], 1)
        return SessionResult(
            end_reason=self.end_reason or "engine_closed",
            outcome=self.outcome,
            note=self.note,
            turns=self.turns,
            metrics=self.metrics,
            error=error,
        )

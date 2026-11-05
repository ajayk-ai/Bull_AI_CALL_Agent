"""Call lifecycle state machine and conversation guards.

The lifecycle decides which status changes are allowed; provider callbacks often arrive late or out of order
("ringing" after the call is already connected), and those are recorded but do not move the call backwards.

The guards end or steer a conversation on deterministic rules (silence, turn and time limits). The AI agent
can only ask to end the call; it never decides whether a call is placed or what is written afterwards.
"""

from dataclasses import dataclass, field
from enum import StrEnum

from app.models.enums import CallStatus

TERMINAL = frozenset(
    {CallStatus.COMPLETED, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED, CallStatus.CANCELLED}
)
ACTIVE = frozenset(CallStatus) - TERMINAL

_ALLOWED: dict[CallStatus, frozenset[CallStatus]] = {
    CallStatus.QUEUED: frozenset({CallStatus.DIALING, CallStatus.FAILED, CallStatus.CANCELLED}),
    CallStatus.DIALING: frozenset(
        {
            CallStatus.RINGING,
            CallStatus.IN_PROGRESS,
            CallStatus.NO_ANSWER,
            CallStatus.BUSY,
            CallStatus.FAILED,
            CallStatus.CANCELLED,
        }
    ),
    CallStatus.RINGING: frozenset(
        {CallStatus.IN_PROGRESS, CallStatus.NO_ANSWER, CallStatus.BUSY, CallStatus.FAILED, CallStatus.CANCELLED}
    ),
    CallStatus.IN_PROGRESS: frozenset({CallStatus.COMPLETED, CallStatus.FAILED}),
}


def can_move(current: CallStatus, new: CallStatus) -> bool:
    return new in _ALLOWED.get(current, frozenset())


def after_provider_end(current: CallStatus) -> CallStatus:
    """Status when the provider reports the call over without saying why: answered calls completed, others
    were not answered."""
    return CallStatus.COMPLETED if current == CallStatus.IN_PROGRESS else CallStatus.NO_ANSWER


class GuardAction(StrEnum):
    NUDGE_SILENCE = "nudge_silence"  # ask the agent to check the caller is still there
    WRAP_UP = "wrap_up"  # ask the agent to close the call now
    HANG_UP = "hang_up"  # end the call without waiting for the agent


@dataclass
class ConversationGuard:
    """Feed it what happens on the call; `check(now)` says what the controller must do, if anything."""

    max_call_seconds: int
    hard_max_seconds: int
    silence_timeout_seconds: int
    max_silence_prompts: int
    max_turns: int
    started_at: float
    # Grace after a wrap-up request before the line is cut regardless.
    wrap_up_grace_seconds: int = 30

    turns: int = 0
    silence_prompts: int = 0
    last_activity: float = field(init=False)
    wrap_up_sent_at: float | None = None
    end_reason: str | None = None

    def __post_init__(self) -> None:
        self.last_activity = self.started_at

    def caller_spoke(self, now: float) -> None:
        self.last_activity = max(self.last_activity, now)
        self.silence_prompts = 0

    def agent_audio_until(self, playback_end: float) -> None:
        """The agent is talking until `playback_end`; silence is counted from then."""
        self.last_activity = max(self.last_activity, playback_end)

    def turn_completed(self) -> None:
        self.turns += 1

    def check(self, now: float) -> GuardAction | None:
        elapsed = now - self.started_at
        if elapsed >= self.hard_max_seconds:
            self.end_reason = "hard_time_limit"
            return GuardAction.HANG_UP
        if self.wrap_up_sent_at is not None:
            if now - self.wrap_up_sent_at >= self.wrap_up_grace_seconds:
                self.end_reason = self.end_reason or "time_limit"
                return GuardAction.HANG_UP
            return None
        if elapsed >= self.max_call_seconds or self.turns >= self.max_turns:
            self.wrap_up_sent_at = now
            self.end_reason = "time_limit" if elapsed >= self.max_call_seconds else "turn_limit"
            return GuardAction.WRAP_UP
        if now - self.last_activity >= self.silence_timeout_seconds:
            if self.silence_prompts >= self.max_silence_prompts:
                self.end_reason = "silence"
                return GuardAction.HANG_UP
            self.silence_prompts += 1
            self.last_activity = now
            return GuardAction.NUDGE_SILENCE
        return None

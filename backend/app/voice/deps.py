"""Dependencies for the telephony provider and voice engine, so tests can substitute fakes."""

from typing import Annotated

from fastapi import Depends

from app.core.errors import AppError
from app.providers.telephony import TelephonyError, TelephonyProvider, get_telephony
from app.voice.engine import VoiceEngine, get_voice_engine


class CallingDisabled(AppError):
    status_code = 503
    code = "calling_unavailable"


def telephony_dep() -> TelephonyProvider:
    try:
        return get_telephony()
    except TelephonyError as exc:
        raise CallingDisabled(str(exc))


def engine_dep() -> VoiceEngine:
    return get_voice_engine()


TelephonyDep = Annotated[TelephonyProvider, Depends(telephony_dep)]
EngineDep = Annotated[VoiceEngine, Depends(engine_dep)]

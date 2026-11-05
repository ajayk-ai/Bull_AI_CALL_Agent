"""Calling-window checks, shared by individual calls and campaigns."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.schemas.campaigns import CallingWindow


def in_window(window: CallingWindow | dict, at: datetime) -> bool:
    """Is `at` (timezone-aware) inside the window, in the window's own time zone?"""
    if isinstance(window, dict):
        window = CallingWindow.model_validate(window)
    local = at.astimezone(ZoneInfo(window.timezone))
    return local.weekday() in window.days and window.start <= local.time() < window.end


def describe(window: CallingWindow | dict) -> str:
    if isinstance(window, dict):
        window = CallingWindow.model_validate(window)
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return f"{', '.join(days[d] for d in window.days)} {window.start:%H:%M}-{window.end:%H:%M} ({window.timezone})"

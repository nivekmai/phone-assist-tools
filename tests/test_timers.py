"""Tests for local timer event forwarding."""

import asyncio
from types import SimpleNamespace

import pytest

from custom_components.phone_assist_tools import timers
from custom_components.phone_assist_tools.const import COMMAND_TIMER


class _FakeHass:
    """Minimal Home Assistant task host."""

    def __init__(self) -> None:
        """Initialize task tracking."""
        self.tasks: list[asyncio.Task] = []

    def async_create_task(self, coroutine, _name: str) -> None:
        """Schedule and retain a task."""
        self.tasks.append(asyncio.create_task(coroutine))


@pytest.mark.asyncio
async def test_local_timer_is_forwarded_and_notification_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capable phone receives the native timer instead of a finish notification."""
    hass = _FakeHass()
    previous_events: list[object] = []
    dispatches: list[dict] = []

    monkeypatch.setattr(timers, "supports_phone_command", lambda *_args, **_kwargs: True)

    async def _dispatch(*_args, **kwargs) -> None:
        dispatches.append(kwargs)

    monkeypatch.setattr(timers, "async_dispatch_and_wait", _dispatch)
    handler = timers._create_timer_handler(
        hass,
        lambda event_type, _timer_info: previous_events.append(event_type),
        SimpleNamespace(user_id="user-1"),
    )
    timer_info = SimpleNamespace(
        id="timer-1",
        name="tea",
        created_seconds=300,
        device_id="device-1",
    )

    handler(timers.TimerEventType.STARTED, timer_info)
    await asyncio.gather(*hass.tasks)
    handler(timers.TimerEventType.FINISHED, timer_info)

    assert dispatches[0]["device_id"] == "device-1"
    assert dispatches[0]["command"] == COMMAND_TIMER
    assert dispatches[0]["command_data"] == {
        "timer_seconds": 300,
        "timer_skip_ui": True,
        "timer_message": "tea",
    }
    assert previous_events == []


def test_incapable_phone_keeps_core_timer_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal mobile registration retains Core's timer callback."""
    hass = _FakeHass()
    previous_events: list[object] = []
    monkeypatch.setattr(
        timers, "supports_phone_command", lambda *_args, **_kwargs: False
    )
    handler = timers._create_timer_handler(
        hass,
        lambda event_type, _timer_info: previous_events.append(event_type),
        SimpleNamespace(user_id="user-1"),
    )
    timer_info = SimpleNamespace(id="timer-1", device_id="device-1")

    handler(timers.TimerEventType.STARTED, timer_info)

    assert previous_events == [timers.TimerEventType.STARTED]
    assert hass.tasks == []

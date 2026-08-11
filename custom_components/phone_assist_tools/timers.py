"""Forward local Assist timer events to capable mobile apps."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError

try:
    from homeassistant.components.intent import TimerEventType, TimerInfo
    from homeassistant.components.intent.const import TIMER_DATA
except ImportError:  # Home Assistant 2026.7 and earlier
    from homeassistant.helpers.intent import TIMER_DATA, TimerEventType, TimerInfo

from .const import COMMAND_TIMER, TIMER_MESSAGE, TIMER_SECONDS, TIMER_SKIP_UI
from .coordinator import async_dispatch_and_wait, supports_phone_command

_LOGGER = logging.getLogger(__name__)

_MOBILE_APP_DOMAIN = "mobile_app"
_MOBILE_APP_CONFIG_ENTRIES = "config_entries"
_MOBILE_APP_DEVICES = "devices"
_MOBILE_APP_USER_ID = "user_id"

type TimerHandler = Callable[[TimerEventType, TimerInfo], None]


async def _async_start_native_timer(
    hass: HomeAssistant,
    timer_info: TimerInfo,
    context: Context,
    native_timer_ids: set[str],
) -> None:
    """Start a native timer and remember successful forwarding."""
    command_data: dict[str, int | str | bool] = {
        TIMER_SECONDS: timer_info.created_seconds,
        TIMER_SKIP_UI: True,
    }
    if timer_info.name:
        command_data[TIMER_MESSAGE] = timer_info.name

    try:
        await async_dispatch_and_wait(
            hass,
            device_id=timer_info.device_id,
            command=COMMAND_TIMER,
            command_data=command_data,
            action_name="timer",
            context=context,
        )
    except HomeAssistantError:
        _LOGGER.warning("Unable to start native timer on mobile device", exc_info=True)
        return

    native_timer_ids.add(timer_info.id)


@callback
def _create_timer_handler(
    hass: HomeAssistant,
    previous_handler: TimerHandler,
    context: Context,
) -> TimerHandler:
    """Wrap Core's mobile timer handler with native timer forwarding."""
    native_timer_ids: set[str] = set()

    @callback
    def async_handle_timer_event(
        event_type: TimerEventType, timer_info: TimerInfo
    ) -> None:
        if event_type == TimerEventType.STARTED and supports_phone_command(
            hass,
            device_id=timer_info.device_id,
            command=COMMAND_TIMER,
            context=context,
        ):
            hass.async_create_task(
                _async_start_native_timer(hass, timer_info, context, native_timer_ids),
                "phone_assist_tools_native_timer",
            )
            return

        if event_type == TimerEventType.CANCELLED:
            native_timer_ids.discard(timer_info.id)
        elif event_type == TimerEventType.FINISHED and timer_info.id in native_timer_ids:
            native_timer_ids.discard(timer_info.id)
            return

        previous_handler(event_type, timer_info)

    return async_handle_timer_event


@callback
def async_setup_timer_bridge(hass: HomeAssistant) -> int:
    """Install native forwarding around existing mobile-app timer handlers."""
    timer_manager = hass.data.get(TIMER_DATA)
    mobile_app_data: dict[str, Any] | None = hass.data.get(_MOBILE_APP_DOMAIN)
    if timer_manager is None or mobile_app_data is None:
        return 0

    config_entries = mobile_app_data.get(_MOBILE_APP_CONFIG_ENTRIES, {})
    devices = mobile_app_data.get(_MOBILE_APP_DEVICES, {})
    handlers = timer_manager.handlers
    installed = 0

    for webhook_id, device in devices.items():
        entry = config_entries.get(webhook_id)
        previous_handler = handlers.get(device.id)
        if entry is None or previous_handler is None:
            continue

        user_id = entry.data.get(_MOBILE_APP_USER_ID)
        if not isinstance(user_id, str):
            continue

        handlers[device.id] = _create_timer_handler(
            hass, previous_handler, Context(user_id=user_id)
        )
        installed += 1

    return installed

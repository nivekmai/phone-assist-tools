"""Phone Assist Tools integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import intent
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ERROR,
    ATTR_REQUEST_ID,
    ATTR_SUCCESS,
    COMMAND_ALARM,
    COMMAND_PLAY_MEDIA,
    COMMAND_TIMER,
    DOMAIN,
    MAX_ERROR_LENGTH,
    MAX_REQUEST_ID_LENGTH,
    SERVICE_ACKNOWLEDGE,
)
from .coordinator import (
    DATA_RUNTIME,
    PhoneAssistToolsRuntime,
    native_mobile_app_commands,
)
from .intents import (
    PlayPhoneMediaIntentHandler,
    SetPhoneAlarmIntentHandler,
    SetPhoneTimerIntentHandler,
)
from .timers import async_setup_timer_bridge

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)

ACKNOWLEDGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_REQUEST_ID): vol.All(
            cv.string, vol.Length(min=1, max=MAX_REQUEST_ID_LENGTH)
        ),
        vol.Required(ATTR_SUCCESS): cv.boolean,
        vol.Optional(ATTR_ERROR): vol.All(cv.string, vol.Length(max=MAX_ERROR_LENGTH)),
    }
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up YAML-loaded phone tools, acknowledgement service, and 2026.7 intents."""
    runtime = PhoneAssistToolsRuntime()
    hass.data[DATA_RUNTIME] = runtime

    @callback
    def async_handle_acknowledgement(call: ServiceCall) -> None:
        """Resolve the matching pending tool call."""
        if runtime.async_acknowledge(
            call.data[ATTR_REQUEST_ID],
            call.data[ATTR_SUCCESS],
            call.data.get(ATTR_ERROR),
            call.context.user_id,
        ):
            return
        _LOGGER.debug(
            "Ignoring late or unknown phone tool acknowledgement %s",
            call.data[ATTR_REQUEST_ID],
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_ACKNOWLEDGE,
        async_handle_acknowledgement,
        schema=ACKNOWLEDGE_SCHEMA,
    )

    native_commands = native_mobile_app_commands()
    if COMMAND_ALARM not in native_commands:
        intent.async_register(hass, SetPhoneAlarmIntentHandler())
    if COMMAND_TIMER not in native_commands:
        intent.async_register(hass, SetPhoneTimerIntentHandler())
    if COMMAND_PLAY_MEDIA not in native_commands:
        intent.async_register(hass, PlayPhoneMediaIntentHandler())
    if COMMAND_TIMER not in native_commands:
        installed_timer_bridges = async_setup_timer_bridge(hass)
        _LOGGER.info(
            "Installed native timer forwarding for %s mobile app registrations",
            installed_timer_bridges,
        )
    if native_commands:
        _LOGGER.info(
            "Native mobile_app phone tools detected; compatibility handlers "
            "disabled for: %s",
            ", ".join(sorted(native_commands)),
        )

    @callback
    def async_handle_stop(event: Event) -> None:
        """Cancel waiters when Home Assistant stops."""
        runtime.async_cancel_all()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_handle_stop)
    return True

"""Phone Assist Tools integration."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import config_entry_oauth2_flow, intent
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .assist_pipeline import async_setup_push_to_talk_websocket
from .authorization import (
    DATA_AUTHORIZER,
    PersonalDataAuthorizer,
    async_setup_websocket_api,
)
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
from .google_api import DATA_GOOGLE_CLIENT, GoogleWorkspaceClient
from .intents import (
    CreateGmailDraftIntentHandler,
    CreateGoogleCalendarEventIntentHandler,
    CreateGoogleDocumentIntentHandler,
    DeleteGoogleCalendarEventIntentHandler,
    ListGoogleCalendarsIntentHandler,
    ModifyGmailMessageIntentHandler,
    PlayPhoneMediaIntentHandler,
    ReadGmailMessageIntentHandler,
    ReadGoogleCalendarEventIntentHandler,
    ReadGoogleDriveFileIntentHandler,
    SearchGmailIntentHandler,
    SearchGoogleCalendarEventsIntentHandler,
    SearchGoogleDriveIntentHandler,
    SendGmailMessageIntentHandler,
    SetPhoneAlarmIntentHandler,
    SetPhoneTimerIntentHandler,
    UpdateGoogleCalendarEventIntentHandler,
    UpdateGoogleDocumentIntentHandler,
    UpdateGoogleDriveFileIntentHandler,
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
    authorizer = PersonalDataAuthorizer()
    hass.data[DATA_AUTHORIZER] = authorizer
    async_setup_websocket_api(hass, authorizer)
    async_setup_push_to_talk_websocket(hass)

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
    for personal_handler in (
        SearchGmailIntentHandler(),
        ReadGmailMessageIntentHandler(),
        CreateGmailDraftIntentHandler(),
        SendGmailMessageIntentHandler(),
        ModifyGmailMessageIntentHandler(),
        SearchGoogleDriveIntentHandler(),
        ReadGoogleDriveFileIntentHandler(),
        CreateGoogleDocumentIntentHandler(),
        UpdateGoogleDocumentIntentHandler(),
        UpdateGoogleDriveFileIntentHandler(),
        ListGoogleCalendarsIntentHandler(),
        SearchGoogleCalendarEventsIntentHandler(),
        ReadGoogleCalendarEventIntentHandler(),
        CreateGoogleCalendarEventIntentHandler(),
        UpdateGoogleCalendarEventIntentHandler(),
        DeleteGoogleCalendarEventIntentHandler(),
    ):
        intent.async_register(hass, personal_handler)
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
        authorizer.clear()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_handle_stop)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one gated Google Workspace account from a config entry."""
    try:
        implementation = (
            await config_entry_oauth2_flow.async_get_config_entry_implementation(
                hass, entry
            )
        )
    except config_entry_oauth2_flow.ImplementationUnavailableError as err:
        raise ConfigEntryNotReady("Google OAuth implementation is unavailable") from err
    session = config_entry_oauth2_flow.OAuth2Session(hass, entry, implementation)
    await session.async_ensure_token_valid()
    hass.data[DATA_GOOGLE_CLIENT] = GoogleWorkspaceClient(hass, session)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Google Workspace access."""
    hass.data.pop(DATA_GOOGLE_CLIENT, None)
    return True

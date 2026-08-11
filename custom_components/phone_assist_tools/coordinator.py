"""Route phone commands and correlate Companion app acknowledgements."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.device_automation import InvalidDeviceAutomationConfig
from homeassistant.components.mobile_app import const as mobile_app_const
from homeassistant.components.mobile_app.device_action import (
    ACTION_SCHEMA,
    async_call_action_from_config,
)
from homeassistant.components.mobile_app.util import webhook_id_from_device_id
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util.hass_dict import HassKey
from homeassistant.util.json import JsonObjectType
from homeassistant.util.ulid import ulid_now

from .const import (
    ACK_TIMEOUT_SECONDS,
    ATTR_REQUEST_ID,
    ATTR_SUCCESS,
    COMMAND_ALARM,
    COMMAND_PLAY_MEDIA,
    COMMAND_TIMER,
    DOMAIN,
    PHONE_TOOL_REQUEST_ID,
    SUPPORTED_DEVICE_COMMANDS,
)

try:
    from homeassistant.components.mobile_app import llm as mobile_app_llm
except ImportError:
    mobile_app_llm = None

_LOGGER = logging.getLogger(__name__)

DATA_RUNTIME: HassKey[PhoneAssistToolsRuntime] = HassKey(DOMAIN)

_MOBILE_APP_DOMAIN = "mobile_app"
_MOBILE_APP_CONFIG_ENTRIES = "config_entries"
_MOBILE_APP_DEVICES = "devices"
_MOBILE_APP_APP_DATA = "app_data"
_MOBILE_APP_USER_ID = "user_id"
_PUSH_TOKEN = "push_token"
_PUSH_URL = "push_url"
_PUSH_WEBSOCKET_CHANNEL = "push_websocket_channel"
_PHYSICAL_DEVICE_FIELDS = ("app_id", "device_name", "manufacturer", "model", "os_name")

_NATIVE_TOOL_MARKERS = {
    COMMAND_ALARM: ("COMMAND_ALARM", "SetPhoneAlarmTool", "mobile_app_set_alarm"),
    COMMAND_TIMER: ("COMMAND_TIMER", "SetPhoneTimerTool", "mobile_app_set_timer"),
    COMMAND_PLAY_MEDIA: (
        "COMMAND_PLAY_MEDIA",
        "PlayPhoneMediaTool",
        "mobile_app_play_media",
    ),
}


@dataclass(frozen=True, slots=True)
class PhoneAcknowledgement:
    """Result returned asynchronously by the Companion app."""

    success: bool
    error: str | None = None


@dataclass(slots=True)
class PendingRequest:
    """One command waiting for an acknowledgement."""

    device_id: str
    user_id: str | None
    future: asyncio.Future[PhoneAcknowledgement]


@dataclass(slots=True)
class PhoneAssistToolsRuntime:
    """Runtime state for concurrent phone tool requests."""

    pending: dict[str, PendingRequest] = field(default_factory=dict)

    @callback
    def async_reserve(
        self, hass: HomeAssistant
    ) -> tuple[str, asyncio.Future[PhoneAcknowledgement]]:
        """Reserve an opaque request ID before dispatch.

        Reserving it before the notification call avoids acknowledgement races.
        """
        request_id = ulid_now()
        while request_id in self.pending:
            request_id = ulid_now()

        future: asyncio.Future[PhoneAcknowledgement] = hass.loop.create_future()
        return request_id, future

    @callback
    def async_acknowledge(
        self,
        request_id: str,
        success: bool,
        error: str | None,
        user_id: str | None,
    ) -> bool:
        """Resolve a request, returning false for a late or unknown acknowledgement."""
        pending = self.pending.get(request_id)
        if pending is None or pending.future.done():
            return False

        if pending.user_id is not None and pending.user_id != user_id:
            _LOGGER.warning(
                "Ignoring phone tool acknowledgement from a different "
                "Home Assistant user"
            )
            return False

        pending.future.set_result(
            PhoneAcknowledgement(success=success, error=error or None)
        )
        return True

    @callback
    def async_cancel_all(self) -> None:
        """Cancel all requests during Home Assistant shutdown."""
        for pending in self.pending.values():
            if not pending.future.done():
                pending.future.cancel()
        self.pending.clear()


def get_runtime(hass: HomeAssistant) -> PhoneAssistToolsRuntime:
    """Return initialized runtime state."""
    try:
        return hass.data[DATA_RUNTIME]
    except KeyError as err:
        raise HomeAssistantError("Phone Assist Tools is not loaded") from err


@callback
def native_mobile_app_commands() -> frozenset[str]:
    """Return phone commands implemented by Home Assistant Core itself.

    Checking both the Core constants and concrete tool classes avoids disabling this
    compatibility integration merely because a future or downstream Core happens to
    use one of the same notification command strings.
    """
    if getattr(
        mobile_app_const, "ATTR_SUPPORTED_DEVICE_COMMANDS", None
    ) != SUPPORTED_DEVICE_COMMANDS or not hasattr(
        mobile_app_const, "DATA_DEVICE_COMMAND_MANAGER"
    ):
        return frozenset()

    native_commands: set[str] = set()
    for command, (constant_name, class_name, tool_name) in _NATIVE_TOOL_MARKERS.items():
        tool_class = getattr(mobile_app_llm, class_name, None)
        if (
            getattr(mobile_app_const, constant_name, None) == command
            and getattr(tool_class, "name", None) == tool_name
        ):
            native_commands.add(command)
    return frozenset(native_commands)


@callback
def _entry_supports_phone_command(
    config_entry: Any, command: str, user_id: str
) -> bool:
    """Return whether one registration is authorized and able to receive a command."""
    entry_data = config_entry.data
    if entry_data.get(_MOBILE_APP_USER_ID) != user_id:
        return False

    app_data = entry_data.get(_MOBILE_APP_APP_DATA)
    if not isinstance(app_data, Mapping):
        return False

    commands = app_data.get(SUPPORTED_DEVICE_COMMANDS)
    if not isinstance(commands, list) or command not in commands:
        return False

    return bool(
        app_data.get(_PUSH_WEBSOCKET_CHANNEL)
        or (app_data.get(_PUSH_TOKEN) and app_data.get(_PUSH_URL))
    )


@callback
def resolve_phone_command_device_id(
    hass: HomeAssistant,
    *,
    device_id: str | None,
    command: str,
    context: Context | None,
) -> str | None:
    """Resolve the capable registration for the phone that originated Assist.

    Reinstalling or running another Companion build can leave two mobile_app device
    records for the same physical phone. Prefer the exact origin. If it is stale,
    route only when exactly one same-user registration has matching physical-device
    metadata and explicitly advertises the requested command.
    """
    if not device_id or context is None or context.user_id is None:
        return None

    webhook_id = webhook_id_from_device_id(hass, device_id)
    if webhook_id is None:
        return None

    try:
        mobile_app_data = hass.data[_MOBILE_APP_DOMAIN]
        config_entries = mobile_app_data[_MOBILE_APP_CONFIG_ENTRIES]
        config_entry = config_entries[webhook_id]
    except KeyError:
        return None

    if _entry_supports_phone_command(config_entry, command, context.user_id):
        return device_id

    fingerprint = tuple(
        config_entry.data.get(field) for field in _PHYSICAL_DEVICE_FIELDS
    )
    if not all(isinstance(value, str) and value for value in fingerprint):
        return None

    candidates: list[str] = []
    devices = mobile_app_data.get(_MOBILE_APP_DEVICES, {})
    for candidate_webhook_id, candidate_entry in config_entries.items():
        if (
            candidate_webhook_id == webhook_id
            or tuple(
                candidate_entry.data.get(field) for field in _PHYSICAL_DEVICE_FIELDS
            )
            != fingerprint
        ):
            continue
        if not _entry_supports_phone_command(candidate_entry, command, context.user_id):
            continue
        candidate_device_id = getattr(devices.get(candidate_webhook_id), "id", None)
        if isinstance(candidate_device_id, str):
            candidates.append(candidate_device_id)

    return candidates[0] if len(candidates) == 1 else None


@callback
def supports_phone_command(
    hass: HomeAssistant,
    *,
    device_id: str | None,
    command: str,
    context: Context | None,
) -> bool:
    """Return whether the originating physical phone opted into a command."""
    return (
        resolve_phone_command_device_id(
            hass,
            device_id=device_id,
            command=command,
            context=context,
        )
        is not None
    )


async def async_dispatch_and_wait(
    hass: HomeAssistant,
    *,
    device_id: str | None,
    command: str,
    command_data: dict[str, Any],
    action_name: str,
    context: Context | None,
    timeout: float = ACK_TIMEOUT_SECONDS,
) -> JsonObjectType:
    """Send one mobile-app device action and wait for the matching phone result."""
    if not device_id:
        raise HomeAssistantError(
            f"Cannot set the phone {action_name}: the Assist request has no "
            "originating device ID"
        )

    target_device_id = resolve_phone_command_device_id(
        hass,
        device_id=device_id,
        command=command,
        context=context,
    )
    if target_device_id is None:
        raise HomeAssistantError(
            f"Cannot set the phone {action_name}: that command is not enabled "
            "for the requesting mobile app"
        )

    runtime = get_runtime(hass)
    request_id, future = runtime.async_reserve(hass)
    runtime.pending[request_id] = PendingRequest(
        device_id=target_device_id,
        user_id=context.user_id if context else None,
        future=future,
    )

    payload = {
        **command_data,
        PHONE_TOOL_REQUEST_ID: request_id,
    }
    config = ACTION_SCHEMA(
        {
            CONF_DEVICE_ID: target_device_id,
            CONF_DOMAIN: "mobile_app",
            CONF_TYPE: "notify",
            "message": command,
            "data": payload,
        }
    )

    try:
        try:
            await async_call_action_from_config(
                hass,
                config,
                variables={},
                context=context,
            )
        except InvalidDeviceAutomationConfig as err:
            raise HomeAssistantError(
                f"Could not route the {action_name} command to the requesting "
                f"phone: {err}"
            ) from err

        try:
            acknowledgement = await asyncio.wait_for(
                asyncio.shield(future), timeout=timeout
            )
        except TimeoutError as err:
            raise HomeAssistantError(
                f"The requesting phone did not acknowledge the {action_name} "
                f"command within {timeout:g} seconds"
            ) from err

        if not acknowledgement.success:
            detail = acknowledgement.error or "the phone reported an unknown error"
            raise HomeAssistantError(
                f"The requesting phone could not set the {action_name}: {detail}"
            )

        return {
            ATTR_SUCCESS: True,
            "action": action_name,
            "device_id": target_device_id,
            ATTR_REQUEST_ID: request_id,
        }
    finally:
        current = runtime.pending.get(request_id)
        if current is not None and current.future is future:
            runtime.pending.pop(request_id, None)
        if not future.done():
            future.cancel()

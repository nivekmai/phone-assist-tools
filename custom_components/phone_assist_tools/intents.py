"""2026.7-compatible Assist LLM tools implemented as intent handlers."""

from __future__ import annotations

from typing import override

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import intent

from .const import (
    ALARM_HOUR,
    ALARM_MESSAGE,
    ALARM_MINUTE,
    ALARM_SKIP_UI,
    COMMAND_ALARM,
    COMMAND_PLAY_MEDIA,
    COMMAND_TIMER,
    MEDIA_QUERY,
    MEDIA_TYPE,
    TIMER_MESSAGE,
    TIMER_SECONDS,
    TIMER_SKIP_UI,
)
from .coordinator import async_dispatch_and_wait
from .schema import (
    alarm_parameters,
    media_parameters,
    normalize_media_query,
    timer_parameters,
)

INTENT_SET_PHONE_ALARM = "SetPhoneAlarm"
INTENT_SET_PHONE_TIMER = "SetPhoneTimer"
INTENT_PLAY_PHONE_MEDIA = "PlayPhoneMedia"


class SetPhoneAlarmIntentHandler(intent.IntentHandler):
    """Expose an absolute local-phone alarm to the 2026.7 Assist LLM API."""

    intent_type = INTENT_SET_PHONE_ALARM
    description = (
        "Set an alarm at a specific local clock time on the Android phone that "
        "started this Assist request. Use this for 'at 7:30' requests; do not "
        "substitute a Home Assistant timer."
    )
    slot_schema = alarm_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Set an alarm on the originating phone."""
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        command_data: dict = {
            ALARM_HOUR: args["hour"],
            ALARM_MINUTE: args["minute"],
            ALARM_SKIP_UI: True,
        }
        if label := args.get("label"):
            command_data[ALARM_MESSAGE] = label

        try:
            await async_dispatch_and_wait(
                intent_obj.hass,
                device_id=intent_obj.device_id,
                command=COMMAND_ALARM,
                command_data=command_data,
                action_name="alarm",
                context=intent_obj.context,
            )
        except HomeAssistantError as err:
            raise intent.IntentHandleError(str(err)) from err

        response = intent_obj.create_response()
        response.async_set_speech(
            f"Alarm set on this phone for {args['hour']:02d}:{args['minute']:02d}."
        )
        return response


class SetPhoneTimerIntentHandler(intent.IntentHandler):
    """Expose a local-phone duration timer to the 2026.7 Assist LLM API."""

    intent_type = INTENT_SET_PHONE_TIMER
    description = (
        "Set a countdown timer on the Android phone that started this Assist "
        "request. Use only for a duration such as 'five minutes'; do not use it "
        "for an alarm at a specific clock time."
    )
    slot_schema = timer_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Set a timer on the originating phone."""
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        command_data: dict = {
            TIMER_SECONDS: args["duration_seconds"],
            TIMER_SKIP_UI: True,
        }
        if label := args.get("label"):
            command_data[TIMER_MESSAGE] = label

        try:
            await async_dispatch_and_wait(
                intent_obj.hass,
                device_id=intent_obj.device_id,
                command=COMMAND_TIMER,
                command_data=command_data,
                action_name="timer",
                context=intent_obj.context,
            )
        except HomeAssistantError as err:
            raise intent.IntentHandleError(str(err)) from err

        response = intent_obj.create_response()
        response.async_set_speech(
            f"Timer set on this phone for {args['duration_seconds']} seconds."
        )
        return response


class PlayPhoneMediaIntentHandler(intent.IntentHandler):
    """Expose phone-local media playback to the 2026.7 Assist LLM API."""

    intent_type = INTENT_PLAY_PHONE_MEDIA
    description = (
        "Resume an audiobook or play music on the Android phone that started this "
        "Assist request. Always omit query for an audiobook; omit it for usual music."
    )
    slot_schema = media_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Start media on the originating phone."""
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        command_data = {MEDIA_TYPE: args["media_type"]}
        if query := normalize_media_query(args["media_type"], args.get("query")):
            command_data[MEDIA_QUERY] = query

        try:
            await async_dispatch_and_wait(
                intent_obj.hass,
                device_id=intent_obj.device_id,
                command=COMMAND_PLAY_MEDIA,
                command_data=command_data,
                action_name="media playback",
                context=intent_obj.context,
            )
        except HomeAssistantError as err:
            raise intent.IntentHandleError(str(err)) from err

        response = intent_obj.create_response()
        response.async_set_speech("Playing on this phone.")
        return response

"""2026.7-compatible Assist LLM tools implemented as intent handlers."""

from __future__ import annotations

import json
from typing import override

from aiohttp import ClientResponseError
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
    PERSONAL_DATA_SCOPE_DRIVE,
    PERSONAL_DATA_SCOPE_GMAIL,
    TIMER_MESSAGE,
    TIMER_SECONDS,
    TIMER_SKIP_UI,
)
from .coordinator import async_dispatch_and_wait
from .google_api import google_api_error_message, google_client_for_context
from .schema import (
    alarm_parameters,
    id_parameters,
    media_parameters,
    normalize_media_query,
    search_parameters,
    timer_parameters,
)

INTENT_SET_PHONE_ALARM = "SetPhoneAlarm"
INTENT_SET_PHONE_TIMER = "SetPhoneTimer"
INTENT_PLAY_PHONE_MEDIA = "PlayPhoneMedia"
INTENT_SEARCH_GMAIL = "SearchGmail"
INTENT_READ_GMAIL_MESSAGE = "ReadGmailMessage"
INTENT_SEARCH_GOOGLE_DRIVE = "SearchGoogleDrive"
INTENT_READ_GOOGLE_DRIVE_FILE = "ReadGoogleDriveFile"


def _personal_client(intent_obj: intent.Intent, scope: str):
    try:
        return google_client_for_context(
            intent_obj.hass,
            device_id=intent_obj.device_id,
            context=intent_obj.context,
            required_scope=scope,
        )
    except HomeAssistantError as err:
        raise intent.IntentHandleError(str(err)) from err


def _json_response(intent_obj: intent.Intent, value: object) -> intent.IntentResponse:
    response = intent_obj.create_response()
    response.async_set_speech(json.dumps(value, ensure_ascii=False))
    return response


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


class SearchGmailIntentHandler(intent.IntentHandler):
    """Compatibility Gmail search tool for pre-platform LLM APIs."""

    intent_type = INTENT_SEARCH_GMAIL
    description = (
        "Search Gmail only when this Assist request was authorized by its "
        "originating phone. This is read-only."
    )
    slot_schema = search_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_GMAIL)
        try:
            messages = await client.search_gmail(args["query"], args["max_results"])
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, {"messages": messages, "count": len(messages)})


class ReadGmailMessageIntentHandler(intent.IntentHandler):
    """Compatibility Gmail read tool for pre-platform LLM APIs."""

    intent_type = INTENT_READ_GMAIL_MESSAGE
    description = "Read one Gmail message by an ID returned from SearchGmail."
    slot_schema = id_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_GMAIL)
        try:
            value = await client.read_gmail_message(slots["id"]["value"])
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)


class SearchGoogleDriveIntentHandler(intent.IntentHandler):
    """Compatibility Drive search tool for pre-platform LLM APIs."""

    intent_type = INTENT_SEARCH_GOOGLE_DRIVE
    description = (
        "Search Google Drive only when this Assist request was authorized by "
        "its originating phone. This is read-only."
    )
    slot_schema = search_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_DRIVE)
        try:
            files = await client.search_drive(args["query"], args["max_results"])
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, {"files": files, "count": len(files)})


class ReadGoogleDriveFileIntentHandler(intent.IntentHandler):
    """Compatibility Drive read tool for pre-platform LLM APIs."""

    intent_type = INTENT_READ_GOOGLE_DRIVE_FILE
    description = "Read bounded text from a Drive file ID returned by SearchGoogleDrive."
    slot_schema = id_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_DRIVE)
        try:
            value = await client.read_drive_file(slots["id"]["value"])
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)

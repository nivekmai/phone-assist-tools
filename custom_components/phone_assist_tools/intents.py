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
    PERSONAL_DATA_SCOPE_CALENDAR,
    PERSONAL_DATA_SCOPE_DRIVE,
    PERSONAL_DATA_SCOPE_GMAIL,
    TIMER_MESSAGE,
    TIMER_SECONDS,
    TIMER_SKIP_UI,
)
from .coordinator import async_dispatch_and_wait
from .google_api import google_api_error_message, google_client_for_context
from .schema import (
    CALENDAR_CREATE_PARAMETERS,
    CALENDAR_SEARCH_PARAMETERS,
    CALENDAR_UPDATE_PARAMETERS,
    alarm_parameters,
    calendar_create_parameters,
    calendar_event_id_parameters,
    calendar_list_parameters,
    calendar_search_parameters,
    calendar_update_parameters,
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
INTENT_LIST_GOOGLE_CALENDARS = "ListGoogleCalendars"
INTENT_SEARCH_GOOGLE_CALENDAR_EVENTS = "SearchGoogleCalendarEvents"
INTENT_READ_GOOGLE_CALENDAR_EVENT = "ReadGoogleCalendarEvent"
INTENT_CREATE_GOOGLE_CALENDAR_EVENT = "CreateGoogleCalendarEvent"
INTENT_UPDATE_GOOGLE_CALENDAR_EVENT = "UpdateGoogleCalendarEvent"
INTENT_DELETE_GOOGLE_CALENDAR_EVENT = "DeleteGoogleCalendarEvent"


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
        return _json_response(
            intent_obj, {"messages": messages, "count": len(messages)}
        )


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
    description = (
        "Read bounded text from a Drive file ID returned by SearchGoogleDrive."
    )
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


class ListGoogleCalendarsIntentHandler(intent.IntentHandler):
    """Compatibility calendar-list tool for pre-platform LLM APIs."""

    intent_type = INTENT_LIST_GOOGLE_CALENDARS
    description = "List Google calendars after authorization by the originating phone."
    slot_schema = calendar_list_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            calendars = await client.list_calendars(slots["max_results"]["value"])
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(
            intent_obj, {"calendars": calendars, "count": len(calendars)}
        )


class SearchGoogleCalendarEventsIntentHandler(intent.IntentHandler):
    """Compatibility calendar-event search tool for pre-platform LLM APIs."""

    intent_type = INTENT_SEARCH_GOOGLE_CALENDAR_EVENTS
    description = (
        "Search Google Calendar in an explicit bounded time window after "
        "authorization by the originating phone."
    )
    slot_schema = calendar_search_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = CALENDAR_SEARCH_PARAMETERS(
            {key: value["value"] for key, value in slots.items()}
        )
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            events = await client.search_calendar_events(
                calendar_id=args["calendar_id"],
                time_min=args["time_min"],
                time_max=args["time_max"],
                query=args.get("query"),
                max_results=args["max_results"],
            )
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, {"events": events, "count": len(events)})


class ReadGoogleCalendarEventIntentHandler(intent.IntentHandler):
    """Compatibility single-event read tool for pre-platform LLM APIs."""

    intent_type = INTENT_READ_GOOGLE_CALENDAR_EVENT
    description = "Read one Google Calendar event returned by calendar search."
    slot_schema = calendar_event_id_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            value = await client.read_calendar_event(
                calendar_id=args["calendar_id"], event_id=args["event_id"]
            )
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)


class CreateGoogleCalendarEventIntentHandler(intent.IntentHandler):
    """Compatibility explicit event-creation tool for pre-platform LLM APIs."""

    intent_type = INTENT_CREATE_GOOGLE_CALENDAR_EVENT
    description = (
        "Create a Google Calendar event only when the user explicitly requests it. "
        "Never adds attendees or sends invitations."
    )
    slot_schema = calendar_create_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = CALENDAR_CREATE_PARAMETERS(
            {key: value["value"] for key, value in slots.items()}
        )
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            value = await client.create_calendar_event(
                calendar_id=args["calendar_id"],
                title=args["title"],
                start=args["start"],
                end=args["end"],
                timezone=args.get("timezone"),
                description=args.get("description"),
                location=args.get("location"),
            )
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)


class UpdateGoogleCalendarEventIntentHandler(intent.IntentHandler):
    """Compatibility explicit event-update tool for pre-platform LLM APIs."""

    intent_type = INTENT_UPDATE_GOOGLE_CALENDAR_EVENT
    description = (
        "Update an identified Google Calendar event only when the user explicitly "
        "requests that exact change."
    )
    slot_schema = calendar_update_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = CALENDAR_UPDATE_PARAMETERS(
            {key: value["value"] for key, value in slots.items()}
        )
        changes = {
            key: args[key]
            for key in ("title", "start", "end", "timezone", "description", "location")
            if key in args
        }
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            value = await client.update_calendar_event(
                calendar_id=args["calendar_id"],
                event_id=args["event_id"],
                changes=changes,
            )
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)


class DeleteGoogleCalendarEventIntentHandler(intent.IntentHandler):
    """Compatibility explicit event-deletion tool for pre-platform LLM APIs."""

    intent_type = INTENT_DELETE_GOOGLE_CALENDAR_EVENT
    description = (
        "Permanently delete one identified Google Calendar event only when the user "
        "clearly requests deletion of that specific event. Never infer deletion."
    )
    slot_schema = calendar_event_id_parameters()

    @override
    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        slots = self.async_validate_slots(intent_obj.slots)
        args = {key: value["value"] for key, value in slots.items()}
        client = _personal_client(intent_obj, PERSONAL_DATA_SCOPE_CALENDAR)
        try:
            value = await client.delete_calendar_event(
                calendar_id=args["calendar_id"], event_id=args["event_id"]
            )
        except ClientResponseError as err:
            raise intent.IntentHandleError(google_api_error_message(err)) from err
        return _json_response(intent_obj, value)

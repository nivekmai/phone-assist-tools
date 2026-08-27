"""Shared schemas for Phone Assist Tools."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import MAX_LABEL_LENGTH, MAX_TIMER_SECONDS
from .google_api import MAX_RESULTS

_GENERIC_MUSIC_QUERIES = frozenset(
    {"music", "my music", "usual music", "my usual music"}
)


def validate_label(value: Any) -> str:
    """Validate and normalize an optional Clock label."""
    label = cv.string(value).strip()
    if not label:
        raise vol.Invalid("label must not be empty")
    if len(label) > MAX_LABEL_LENGTH:
        raise vol.Invalid(f"label must be at most {MAX_LABEL_LENGTH} characters")
    return label


def alarm_parameters() -> dict:
    """Return the SetPhoneAlarm parameter schema."""
    return {
        vol.Required(
            "hour",
            description="Hour on the requesting phone's local clock, from 0 to 23.",
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=23)),
        vol.Required(
            "minute",
            description="Minute on the requesting phone's local clock, from 0 to 59.",
        ): vol.All(vol.Coerce(int), vol.Range(min=0, max=59)),
        vol.Optional(
            "label",
            description="Optional label shown by the Android Clock app.",
        ): validate_label,
    }


def timer_parameters() -> dict:
    """Return the SetPhoneTimer parameter schema."""
    return {
        vol.Required(
            "duration_seconds",
            description=(
                "Timer duration in whole seconds. Use this only for a duration, "
                "not for a specific clock time."
            ),
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_TIMER_SECONDS)),
        vol.Optional(
            "label",
            description="Optional label shown by the Android Clock app.",
        ): validate_label,
    }


def media_parameters() -> dict:
    """Return the PlayPhoneMedia parameter schema."""
    return {
        vol.Required("media_type"): vol.In(("audiobook", "music")),
        vol.Optional("query"): vol.All(cv.string, vol.Length(min=1, max=256)),
    }


def normalize_media_query(media_type: str, query: str | None) -> str | None:
    """Discard model-generated placeholders that should resume default media."""
    if media_type == "audiobook" or query is None:
        return None
    normalized = query.strip()
    if normalized.casefold() in _GENERIC_MUSIC_QUERIES:
        return None
    return normalized or None


def search_parameters() -> dict:
    """Return the bounded personal-data search parameter schema."""
    return {
        vol.Required("query"): vol.All(
            cv.string, vol.Strip, vol.Length(min=1, max=500)
        ),
        vol.Optional("max_results", default=5): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_RESULTS)
        ),
    }


def id_parameters() -> dict:
    """Return a bounded opaque Google resource-ID schema."""
    return {
        vol.Required("id"): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=256))
    }


def gmail_compose_parameters() -> dict:
    """Return a bounded schema for a new Gmail draft or sent message."""
    recipients = vol.All(cv.ensure_list, [vol.Email()], vol.Length(min=1, max=10))
    optional_recipients = vol.All(cv.ensure_list, [vol.Email()], vol.Length(max=10))
    return {
        vol.Required("to"): recipients,
        vol.Optional("cc"): optional_recipients,
        vol.Optional("bcc"): optional_recipients,
        vol.Required("subject"): vol.All(
            _bounded_string(998, allow_empty=True), _single_line
        ),
        vol.Required("body"): _bounded_content(20000),
    }


def gmail_modify_parameters() -> dict:
    """Return a schema for a reversible mailbox action."""
    return {
        **id_parameters(),
        vol.Required("action"): vol.In(
            ("archive", "mark_read", "mark_unread", "trash")
        ),
    }


def drive_document_create_parameters() -> dict:
    """Return a bounded Google Docs create schema."""
    return {
        vol.Required("title"): _bounded_string(250),
        vol.Required("content"): _bounded_content(20000),
        vol.Optional("parent_id"): _bounded_string(256),
    }


def drive_document_update_parameters() -> dict:
    """Return a bounded Google Docs content update schema."""
    return {
        vol.Required("id"): _bounded_string(256),
        vol.Required("content"): _bounded_content(20000),
        vol.Required("mode"): vol.In(("append", "replace")),
    }


def drive_metadata_update_parameters() -> dict:
    """Return a constrained Drive metadata/move/trash schema."""
    return vol.All(
        {
            vol.Required("id"): _bounded_string(256),
            vol.Optional("name"): _bounded_string(250),
            vol.Optional("parent_id"): _bounded_string(256),
            vol.Optional("trash"): vol.In((True,)),
        },
        _require_drive_metadata_change,
    )


def _require_drive_metadata_change(value: dict[str, Any]) -> dict[str, Any]:
    if not any(key in value for key in ("name", "parent_id", "trash")):
        raise vol.Invalid("at least one Drive change is required")
    return value


def _bounded_string(max_length: int, *, allow_empty: bool = False):
    minimum = 0 if allow_empty else 1
    return vol.All(cv.string, vol.Strip, vol.Length(min=minimum, max=max_length))


def _bounded_content(max_length: int):
    """Bound user-authored content without changing whitespace."""
    return vol.All(cv.string, vol.Length(min=0, max=max_length))


def _single_line(value: str) -> str:
    """Reject header injection in mail subjects."""
    if "\r" in value or "\n" in value:
        raise vol.Invalid("must be a single line")
    return value


def validate_rfc3339_datetime(value: Any) -> str:
    """Require an RFC3339 timestamp with an explicit UTC offset."""
    timestamp = _bounded_string(64)(value)
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError as err:
        raise vol.Invalid("must be an ISO-8601/RFC3339 date-time") from err
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise vol.Invalid("date-time must include a UTC offset")
    return timestamp


def validate_event_time(value: Any) -> str:
    """Accept either an all-day date or an offset-aware RFC3339 date-time."""
    event_time = _bounded_string(64)(value)
    if len(event_time) == 10:
        try:
            date.fromisoformat(event_time)
        except ValueError as err:
            raise vol.Invalid("must be an ISO-8601 date") from err
        return event_time
    return validate_rfc3339_datetime(event_time)


def validate_timezone(value: Any) -> str:
    """Require an IANA time zone name understood by the server."""
    timezone = _bounded_string(100)(value)
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as err:
        raise vol.Invalid("must be a valid IANA time zone") from err
    return timezone


def _validate_range(
    value: dict[str, Any], start_key: str, end_key: str
) -> dict[str, Any]:
    start = value[start_key]
    end = value[end_key]
    if (len(start) == 10) != (len(end) == 10):
        raise vol.Invalid("start and end must both be dates or both be date-times")
    parser = date.fromisoformat if len(start) == 10 else datetime.fromisoformat
    if parser(end) <= parser(start):
        raise vol.Invalid("end must be after start")
    return value


def calendar_list_parameters() -> dict:
    """Return the bounded calendar-list schema."""
    return {
        vol.Optional("max_results", default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_RESULTS)
        )
    }


def calendar_search_parameters() -> dict:
    """Return the bounded calendar-event search schema."""
    return {
        vol.Optional("calendar_id", default="primary"): _bounded_string(256),
        vol.Required(
            "time_min",
            description="Inclusive RFC3339 window start with UTC offset.",
        ): validate_rfc3339_datetime,
        vol.Required(
            "time_max",
            description="Exclusive RFC3339 window end with UTC offset.",
        ): validate_rfc3339_datetime,
        vol.Optional("query"): _bounded_string(500),
        vol.Optional("max_results", default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_RESULTS)
        ),
    }


def calendar_event_id_parameters() -> dict:
    """Return a calendar/event ID pair schema."""
    return {
        vol.Optional("calendar_id", default="primary"): _bounded_string(256),
        vol.Required("event_id"): _bounded_string(256),
    }


def calendar_create_parameters() -> dict:
    """Return the create-event schema; attendees are intentionally unsupported."""
    return {
        vol.Optional("calendar_id", default="primary"): _bounded_string(256),
        vol.Required("title"): _bounded_string(500),
        vol.Required(
            "start",
            description="RFC3339 date-time with UTC offset, or YYYY-MM-DD for all-day.",
        ): validate_event_time,
        vol.Required(
            "end",
            description=(
                "RFC3339 date-time with UTC offset, or exclusive YYYY-MM-DD "
                "for an all-day event."
            ),
        ): validate_event_time,
        vol.Optional("timezone"): validate_timezone,
        vol.Optional("description"): _bounded_string(2000, allow_empty=True),
        vol.Optional("location"): _bounded_string(500, allow_empty=True),
    }


def calendar_update_parameters() -> dict:
    """Return the patch-event schema."""
    return {
        **calendar_event_id_parameters(),
        vol.Optional("title"): _bounded_string(500),
        vol.Optional("start"): validate_event_time,
        vol.Optional("end"): validate_event_time,
        vol.Optional("timezone"): validate_timezone,
        vol.Optional("description"): _bounded_string(2000, allow_empty=True),
        vol.Optional("location"): _bounded_string(500, allow_empty=True),
    }


def validate_calendar_search(value: dict[str, Any]) -> dict[str, Any]:
    """Validate the event-search window."""
    return _validate_range(value, "time_min", "time_max")


def validate_calendar_create(value: dict[str, Any]) -> dict[str, Any]:
    """Validate an event creation payload."""
    if len(value["start"]) == 10 and "timezone" in value:
        raise vol.Invalid("timezone is not used for all-day events")
    return _validate_range(value, "start", "end")


def validate_calendar_update(value: dict[str, Any]) -> dict[str, Any]:
    """Require at least one coherent field change."""
    changed = {"title", "start", "end", "description", "location"} & value.keys()
    if not changed:
        raise vol.Invalid("at least one event field must be changed")
    if ("start" in value) != ("end" in value):
        raise vol.Invalid("start and end must be updated together")
    if "timezone" in value and "start" not in value:
        raise vol.Invalid("timezone requires start and end")
    if "start" in value:
        if len(value["start"]) == 10 and "timezone" in value:
            raise vol.Invalid("timezone is not used for all-day events")
        _validate_range(value, "start", "end")
    return value


ALARM_PARAMETERS = vol.Schema(alarm_parameters())
TIMER_PARAMETERS = vol.Schema(timer_parameters())
MEDIA_PARAMETERS = vol.Schema(media_parameters())
SEARCH_PARAMETERS = vol.Schema(search_parameters())
ID_PARAMETERS = vol.Schema(id_parameters())
GMAIL_COMPOSE_PARAMETERS = vol.Schema(gmail_compose_parameters())
GMAIL_MODIFY_PARAMETERS = vol.Schema(gmail_modify_parameters())
DRIVE_DOCUMENT_CREATE_PARAMETERS = vol.Schema(drive_document_create_parameters())
DRIVE_DOCUMENT_UPDATE_PARAMETERS = vol.Schema(drive_document_update_parameters())
DRIVE_METADATA_UPDATE_PARAMETERS = vol.Schema(drive_metadata_update_parameters())
CALENDAR_LIST_PARAMETERS = vol.Schema(calendar_list_parameters())
CALENDAR_SEARCH_PARAMETERS = vol.All(
    vol.Schema(calendar_search_parameters()), validate_calendar_search
)
CALENDAR_EVENT_ID_PARAMETERS = vol.Schema(calendar_event_id_parameters())
CALENDAR_CREATE_PARAMETERS = vol.All(
    vol.Schema(calendar_create_parameters()), validate_calendar_create
)
CALENDAR_UPDATE_PARAMETERS = vol.All(
    vol.Schema(calendar_update_parameters()), validate_calendar_update
)

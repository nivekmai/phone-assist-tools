"""Bounded Google Workspace client for phone-authorized Assist tools."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from email.header import decode_header, make_header
from typing import Any
from urllib.parse import quote

from aiohttp import ClientResponseError
from homeassistant.components.mobile_app.util import webhook_id_from_device_id
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import OAuth2Session
from homeassistant.util.hass_dict import HassKey

GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
DRIVE_API = "https://www.googleapis.com/drive/v3"
CALENDAR_API = "https://www.googleapis.com/calendar/v3"
MAX_RESULTS = 10
MAX_CONTENT_CHARS = 12000

DATA_GOOGLE_CLIENT: HassKey[GoogleWorkspaceClient]


class GoogleWorkspaceClient:
    """Call only read endpoints and cap every result returned to an LLM."""

    def __init__(self, hass: HomeAssistant, oauth_session: OAuth2Session) -> None:
        self._session = async_get_clientsession(hass)
        self._oauth_session = oauth_session

    async def _get_json(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> dict[str, Any]:
        await self._oauth_session.async_ensure_token_valid()
        headers = {
            "Authorization": f"Bearer {self._oauth_session.token[CONF_ACCESS_TOKEN]}"
        }
        async with self._session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            value = await response.json()
        return value if isinstance(value, dict) else {}

    async def _send_json(
        self,
        method: str,
        url: str,
        *,
        value: Mapping[str, Any],
        params: Mapping[str, str | int] | None = None,
    ) -> dict[str, Any]:
        await self._oauth_session.async_ensure_token_valid()
        headers = {
            "Authorization": f"Bearer {self._oauth_session.token[CONF_ACCESS_TOKEN]}"
        }
        async with self._session.request(
            method, url, headers=headers, params=params, json=value
        ) as response:
            response.raise_for_status()
            result = await response.json()
        return result if isinstance(result, dict) else {}

    async def _delete(self, url: str) -> None:
        await self._oauth_session.async_ensure_token_valid()
        headers = {
            "Authorization": f"Bearer {self._oauth_session.token[CONF_ACCESS_TOKEN]}"
        }
        async with self._session.delete(url, headers=headers) as response:
            response.raise_for_status()

    async def _get_text(
        self, url: str, *, params: Mapping[str, str | int] | None = None
    ) -> str:
        await self._oauth_session.async_ensure_token_valid()
        headers = {
            "Authorization": f"Bearer {self._oauth_session.token[CONF_ACCESS_TOKEN]}"
        }
        async with self._session.get(url, headers=headers, params=params) as response:
            response.raise_for_status()
            data = await response.content.read(MAX_CONTENT_CHARS * 4)
            return data.decode(response.charset or "utf-8", errors="replace")[
                :MAX_CONTENT_CHARS
            ]

    async def gmail_profile(self) -> str:
        """Return the authorized Gmail address."""
        return str((await self._get_json(f"{GMAIL_API}/profile"))["emailAddress"])

    async def search_gmail(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search Gmail and return bounded message metadata and snippets."""
        result = await self._get_json(
            f"{GMAIL_API}/messages",
            params={"q": query, "maxResults": min(max(max_results, 1), MAX_RESULTS)},
        )
        messages = result.get("messages")
        if not isinstance(messages, list):
            return []
        output: list[dict[str, Any]] = []
        for item in messages[:MAX_RESULTS]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                continue
            message = await self._get_json(
                f"{GMAIL_API}/messages/{item['id']}",
                params={"format": "metadata"},
            )
            output.append(_gmail_summary(message))
        return output

    async def read_gmail_message(self, message_id: str) -> dict[str, Any]:
        """Read one Gmail message, preferring its plain-text body."""
        message = await self._get_json(
            f"{GMAIL_API}/messages/{message_id}", params={"format": "full"}
        )
        summary = _gmail_summary(message)
        summary["body"] = _gmail_body(message.get("payload"))[:MAX_CONTENT_CHARS]
        return summary

    async def search_drive(self, query: str, max_results: int) -> list[dict[str, Any]]:
        """Search visible, non-trashed Drive files."""
        escaped = query.replace("\\", "\\\\").replace("'", "\\'")
        result = await self._get_json(
            f"{DRIVE_API}/files",
            params={
                "q": f"trashed = false and fullText contains '{escaped}'",
                "pageSize": min(max(max_results, 1), MAX_RESULTS),
                "orderBy": "modifiedTime desc",
                "fields": "files(id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress))",
            },
        )
        files = result.get("files")
        return files[:MAX_RESULTS] if isinstance(files, list) else []

    async def read_drive_file(self, file_id: str) -> dict[str, Any]:
        """Read metadata and textual content from one Drive file."""
        metadata = await self._get_json(
            f"{DRIVE_API}/files/{file_id}",
            params={
                "fields": "id,name,mimeType,modifiedTime,webViewLink,owners(displayName,emailAddress),size"
            },
        )
        mime_type = str(metadata.get("mimeType", ""))
        if mime_type == "application/vnd.google-apps.document":
            content = await self._get_text(
                f"{DRIVE_API}/files/{file_id}/export",
                params={"mimeType": "text/plain"},
            )
        elif mime_type == "application/vnd.google-apps.spreadsheet":
            content = await self._get_text(
                f"{DRIVE_API}/files/{file_id}/export",
                params={"mimeType": "text/csv"},
            )
        elif mime_type.startswith("text/") or mime_type in {
            "application/json",
            "application/xml",
        }:
            content = await self._get_text(
                f"{DRIVE_API}/files/{file_id}", params={"alt": "media"}
            )
        else:
            content = (
                "This file type is not returned as text in read-only Assist. "
                "Use webViewLink to open it."
            )
        return {**metadata, "content": content}

    async def list_calendars(self, max_results: int) -> list[dict[str, Any]]:
        """List a bounded set of calendars visible to the authorized account."""
        result = await self._get_json(
            f"{CALENDAR_API}/users/me/calendarList",
            params={
                "maxResults": min(max(max_results, 1), MAX_RESULTS),
                "fields": (
                    "items(id,summary,description,primary,accessRole,timeZone,"
                    "backgroundColor,foregroundColor)"
                ),
            },
        )
        calendars = result.get("items")
        return calendars[:MAX_RESULTS] if isinstance(calendars, list) else []

    async def search_calendar_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        query: str | None,
        max_results: int,
    ) -> list[dict[str, Any]]:
        """List events in one bounded time window, optionally filtering by text."""
        params: dict[str, str | int] = {
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": min(max(max_results, 1), MAX_RESULTS),
            "fields": (
                "items(id,status,summary,description,location,start,end,htmlLink,"
                "organizer(displayName,email),attendees(displayName,email,"
                "responseStatus,self),recurringEventId)"
            ),
        }
        if query:
            params["q"] = query
        result = await self._get_json(
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
            params=params,
        )
        events = result.get("items")
        return events[:MAX_RESULTS] if isinstance(events, list) else []

    async def read_calendar_event(
        self, *, calendar_id: str, event_id: str
    ) -> dict[str, Any]:
        """Read one calendar event by an ID returned from event search."""
        return await self._get_json(
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}",
            params={
                "fields": (
                    "id,status,summary,description,location,start,end,htmlLink,"
                    "creator(displayName,email),organizer(displayName,email),"
                    "attendees(displayName,email,responseStatus,self),recurrence,"
                    "recurringEventId,created,updated"
                )
            },
        )

    async def create_calendar_event(
        self,
        *,
        calendar_id: str,
        title: str,
        start: str,
        end: str,
        timezone: str | None,
        description: str | None,
        location: str | None,
    ) -> dict[str, Any]:
        """Create one event without attendees or conference side effects."""
        value: dict[str, Any] = {
            "summary": title,
            "start": _calendar_time(start, timezone),
            "end": _calendar_time(end, timezone),
        }
        if description is not None:
            value["description"] = description
        if location is not None:
            value["location"] = location
        return await self._send_json(
            "POST",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events",
            value=value,
        )

    async def update_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        changes: Mapping[str, str],
    ) -> dict[str, Any]:
        """Patch only explicitly supplied fields on one event."""
        value: dict[str, Any] = {}
        if "title" in changes:
            value["summary"] = changes["title"]
        if "description" in changes:
            value["description"] = changes["description"]
        if "location" in changes:
            value["location"] = changes["location"]
        if "start" in changes:
            timezone = changes.get("timezone")
            value["start"] = _calendar_time(changes["start"], timezone)
            value["end"] = _calendar_time(changes["end"], timezone)
        return await self._send_json(
            "PATCH",
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}",
            value=value,
        )

    async def delete_calendar_event(
        self, *, calendar_id: str, event_id: str
    ) -> dict[str, Any]:
        """Delete one explicitly identified calendar event."""
        await self._delete(
            f"{CALENDAR_API}/calendars/{quote(calendar_id, safe='')}/events/"
            f"{quote(event_id, safe='')}"
        )
        return {"deleted": True, "calendar_id": calendar_id, "event_id": event_id}


def _calendar_time(value: str, timezone: str | None) -> dict[str, str]:
    """Build a Google Calendar date or dateTime object from validated input."""
    if len(value) == 10:
        return {"date": value}
    result = {"dateTime": value}
    if timezone:
        result["timeZone"] = timezone
    return result


def _decode_header(value: str) -> str:
    try:
        return str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        return value


def _gmail_summary(message: Mapping[str, Any]) -> dict[str, Any]:
    payload = message.get("payload")
    headers: dict[str, str] = {}
    if isinstance(payload, dict) and isinstance(payload.get("headers"), list):
        for item in payload["headers"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            value = item.get("value")
            if isinstance(name, str) and isinstance(value, str):
                headers[name.lower()] = _decode_header(value)
    return {
        "id": message.get("id"),
        "thread_id": message.get("threadId"),
        "from": headers.get("from"),
        "to": headers.get("to"),
        "subject": headers.get("subject"),
        "date": headers.get("date"),
        "snippet": str(message.get("snippet", ""))[:1000],
    }


def _gmail_body(payload: object) -> str:
    if not isinstance(payload, dict):
        return ""
    body = payload.get("body")
    if payload.get("mimeType") == "text/plain" and isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, str):
            try:
                return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                    "utf-8", errors="replace"
                )
            except ValueError:
                return ""
    parts = payload.get("parts")
    if isinstance(parts, list):
        for part in parts:
            value = _gmail_body(part)
            if value:
                return value
    return ""


def google_api_error_message(err: ClientResponseError) -> str:
    """Return a safe bounded Google API failure for a tool response."""
    return f"Google API request failed with HTTP {err.status}"


def google_client_for_context(
    hass: HomeAssistant,
    *,
    device_id: str | None,
    context: Context | None,
    required_scope: str,
) -> GoogleWorkspaceClient:
    """Recheck a device-signed context grant before every Google operation."""
    from .authorization import DATA_AUTHORIZER

    webhook_id = webhook_id_from_device_id(hass, device_id) if device_id else None
    try:
        scopes = hass.data[DATA_AUTHORIZER].scopes_for_context(
            context=context,
            device_webhook_id=webhook_id,
        )
    except KeyError as err:
        raise HomeAssistantError("Phone authorization is not configured") from err
    if required_scope not in scopes:
        raise HomeAssistantError(
            "This Assist request is not authorized by the originating phone"
        )
    try:
        return hass.data[DATA_GOOGLE_CLIENT]
    except KeyError as err:
        raise HomeAssistantError("Google access is not configured") from err


DATA_GOOGLE_CLIENT = HassKey("phone_assist_tools.google_workspace_client")

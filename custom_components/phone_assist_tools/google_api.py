"""Bounded read-only Gmail and Google Drive API client."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from email.header import decode_header, make_header
from typing import Any

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
MAX_RESULTS = 10
MAX_CONTENT_CHARS = 12000

DATA_GOOGLE_CLIENT: HassKey[GoogleReadOnlyClient]


class GoogleReadOnlyClient:
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
) -> GoogleReadOnlyClient:
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
        raise HomeAssistantError("Google read-only access is not configured") from err


DATA_GOOGLE_CLIENT = HassKey("phone_assist_tools.google_readonly_client")

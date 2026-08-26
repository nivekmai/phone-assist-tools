"""Shared schemas for Phone Assist Tools."""

from __future__ import annotations

from typing import Any

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
        vol.Required("query"): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=500)),
        vol.Optional("max_results", default=5): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=MAX_RESULTS)
        ),
    }


def id_parameters() -> dict:
    """Return a bounded opaque Google resource-ID schema."""
    return {vol.Required("id"): vol.All(cv.string, vol.Strip, vol.Length(min=1, max=256))}


ALARM_PARAMETERS = vol.Schema(alarm_parameters())
TIMER_PARAMETERS = vol.Schema(timer_parameters())
MEDIA_PARAMETERS = vol.Schema(media_parameters())
SEARCH_PARAMETERS = vol.Schema(search_parameters())
ID_PARAMETERS = vol.Schema(id_parameters())

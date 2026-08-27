"""Tests for bounded, explicitly authorized Google Calendar operations."""

from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

from custom_components.phone_assist_tools.google_api import GoogleWorkspaceClient
from custom_components.phone_assist_tools.schema import (
    CALENDAR_CREATE_PARAMETERS,
    CALENDAR_SEARCH_PARAMETERS,
    CALENDAR_UPDATE_PARAMETERS,
)


def test_calendar_schemas_require_bounded_coherent_time_ranges() -> None:
    """Calendar windows need offsets and event ranges must be coherent."""
    assert (
        CALENDAR_SEARCH_PARAMETERS(
            {
                "time_min": "2026-08-27T08:00:00-04:00",
                "time_max": "2026-08-28T08:00:00-04:00",
            }
        )["calendar_id"]
        == "primary"
    )
    assert (
        CALENDAR_CREATE_PARAMETERS(
            {"title": "Dentist", "start": "2026-09-01", "end": "2026-09-02"}
        )["end"]
        == "2026-09-02"
    )

    with pytest.raises(vol.Invalid, match="UTC offset"):
        CALENDAR_SEARCH_PARAMETERS(
            {
                "time_min": "2026-08-27T08:00:00",
                "time_max": "2026-08-28T08:00:00-04:00",
            }
        )
    with pytest.raises(vol.Invalid, match="after start"):
        CALENDAR_CREATE_PARAMETERS(
            {"title": "Bad", "start": "2026-09-02", "end": "2026-09-01"}
        )
    with pytest.raises(vol.Invalid, match="both be dates"):
        CALENDAR_CREATE_PARAMETERS(
            {
                "title": "Bad",
                "start": "2026-09-01",
                "end": "2026-09-01T10:00:00-04:00",
            }
        )


def test_calendar_update_requires_explicit_coherent_changes() -> None:
    """An update cannot be empty or change only half of an event range."""
    with pytest.raises(vol.Invalid, match="at least one"):
        CALENDAR_UPDATE_PARAMETERS({"event_id": "event-1"})
    with pytest.raises(vol.Invalid, match="updated together"):
        CALENDAR_UPDATE_PARAMETERS(
            {"event_id": "event-1", "start": "2026-09-01T09:00:00-04:00"}
        )
    assert (
        CALENDAR_UPDATE_PARAMETERS({"event_id": "event-1", "title": "New title"})[
            "title"
        ]
        == "New title"
    )


@pytest.mark.asyncio
async def test_calendar_writes_send_only_explicit_event_fields() -> None:
    """Create/update omit attendees and update patches only requested fields."""
    client = object.__new__(GoogleWorkspaceClient)
    client._send_json = AsyncMock(return_value={"id": "event-1"})
    client._delete = AsyncMock(return_value=None)

    await client.create_calendar_event(
        calendar_id="primary",
        title="Lunch",
        start="2026-09-01T12:00:00-04:00",
        end="2026-09-01T13:00:00-04:00",
        timezone="America/New_York",
        description=None,
        location="Cafe",
    )
    create_value = client._send_json.await_args.kwargs["value"]
    assert create_value == {
        "summary": "Lunch",
        "start": {
            "dateTime": "2026-09-01T12:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "end": {
            "dateTime": "2026-09-01T13:00:00-04:00",
            "timeZone": "America/New_York",
        },
        "location": "Cafe",
    }
    assert "attendees" not in create_value

    await client.update_calendar_event(
        calendar_id="primary",
        event_id="event-1",
        changes={"title": "Later lunch"},
    )
    assert client._send_json.await_args.kwargs["value"] == {"summary": "Later lunch"}

    result = await client.delete_calendar_event(
        calendar_id="primary", event_id="event-1"
    )
    assert result == {
        "deleted": True,
        "calendar_id": "primary",
        "event_id": "event-1",
    }

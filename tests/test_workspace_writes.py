"""Tests for constrained Gmail and Drive/Docs write operations."""

import base64
from email import policy
from email.parser import BytesParser
from unittest.mock import AsyncMock

import pytest
import voluptuous as vol

from custom_components.phone_assist_tools.google_api import GoogleWorkspaceClient
from custom_components.phone_assist_tools.schema import (
    DRIVE_DOCUMENT_UPDATE_PARAMETERS,
    DRIVE_METADATA_UPDATE_PARAMETERS,
    GMAIL_COMPOSE_PARAMETERS,
)


def test_write_schemas_are_bounded_and_require_an_exact_change() -> None:
    """Reject empty Drive changes and malformed recipients."""
    assert GMAIL_COMPOSE_PARAMETERS(
        {"to": ["person@example.com"], "subject": "Hello", "body": "Body"}
    )["to"] == ["person@example.com"]
    with pytest.raises(vol.Invalid):
        GMAIL_COMPOSE_PARAMETERS(
            {"to": ["not an address"], "subject": "Hello", "body": "Body"}
        )
    with pytest.raises(vol.Invalid, match="single line"):
        GMAIL_COMPOSE_PARAMETERS(
            {
                "to": ["person@example.com"],
                "subject": "Hello\nBcc: attacker@example.com",
                "body": "Body",
            }
        )
    assert (
        GMAIL_COMPOSE_PARAMETERS(
            {"to": ["person@example.com"], "subject": "Hello", "body": "  Body\n"}
        )["body"]
        == "  Body\n"
    )
    with pytest.raises(vol.Invalid, match="at least one"):
        DRIVE_METADATA_UPDATE_PARAMETERS({"id": "file-1"})
    with pytest.raises(vol.Invalid):
        DRIVE_METADATA_UPDATE_PARAMETERS({"id": "file-1", "trash": False})
    assert (
        DRIVE_DOCUMENT_UPDATE_PARAMETERS(
            {"id": "doc-1", "content": "More", "mode": "append"}
        )["mode"]
        == "append"
    )


@pytest.mark.asyncio
async def test_gmail_writes_never_call_permanent_delete() -> None:
    """Draft/send encode bounded mail and mailbox actions remain reversible."""
    client = object.__new__(GoogleWorkspaceClient)
    client._send_json = AsyncMock(
        side_effect=[
            {"id": "draft-1", "message": {"id": "message-1"}},
            {"id": "message-2", "threadId": "thread-1"},
            {"id": "message-3", "threadId": "thread-2"},
            {"id": "message-4", "threadId": "thread-3"},
        ]
    )
    client._delete = AsyncMock()

    await client.create_gmail_draft(
        to=["to@example.com"],
        cc=["cc@example.com"],
        bcc=[],
        subject="Subject",
        body="Body",
    )
    raw = client._send_json.await_args_list[0].kwargs["value"]["message"]["raw"]
    decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    message = BytesParser(policy=policy.default).parsebytes(decoded)
    assert message["To"] == "to@example.com"
    assert message["Cc"] == "cc@example.com"
    assert message["Subject"] == "Subject"
    assert message.get_body(preferencelist=("plain",)).get_content() == "Body\n"

    await client.send_gmail_message(
        to=["to@example.com"], cc=[], bcc=[], subject="Send", body="Now"
    )
    await client.modify_gmail_message(message_id="message-3", action="archive")
    await client.modify_gmail_message(message_id="message-4", action="trash")

    archive_call = client._send_json.await_args_list[2]
    assert archive_call.args[0] == "POST"
    assert archive_call.kwargs["value"] == {"removeLabelIds": ["INBOX"]}
    trash_call = client._send_json.await_args_list[3]
    assert trash_call.args[1].endswith("/messages/message-4/trash")
    client._delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_docs_and_drive_writes_have_no_share_or_delete_operation() -> None:
    """Docs updates are explicit and Drive mutations only patch metadata."""
    client = object.__new__(GoogleWorkspaceClient)
    client._get_json = AsyncMock(
        side_effect=[
            {"body": {"content": [{"endIndex": 8}]}},
            {"parents": ["old-parent"]},
        ]
    )
    client._send_json = AsyncMock(
        side_effect=[{}, {"id": "file-1", "name": "Renamed", "trashed": False}]
    )
    client._delete = AsyncMock()

    await client.update_google_document(
        document_id="doc-1", content="Replacement", mode="replace"
    )
    requests = client._send_json.await_args_list[0].kwargs["value"]["requests"]
    assert requests == [
        {"deleteContentRange": {"range": {"startIndex": 1, "endIndex": 7}}},
        {"insertText": {"location": {"index": 1}, "text": "Replacement"}},
    ]

    await client.update_drive_file(
        file_id="file-1",
        name="Renamed",
        parent_id="new-parent",
        trash=False,
    )
    drive_call = client._send_json.await_args_list[1]
    assert drive_call.args[0] == "PATCH"
    assert drive_call.kwargs["value"] == {"name": "Renamed"}
    assert drive_call.kwargs["params"]["addParents"] == "new-parent"
    assert drive_call.kwargs["params"]["removeParents"] == "old-parent"
    assert "permissions" not in drive_call.kwargs["value"]
    client._delete.assert_not_awaited()

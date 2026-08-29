"""Tests for the push-to-talk Assist pipeline endpoint."""

from unittest.mock import Mock, patch

from custom_components.phone_assist_tools.assist_pipeline import (
    async_setup_push_to_talk_websocket,
)


def test_push_to_talk_forwards_with_vad_disabled() -> None:
    """The compatibility endpoint delegates to Core with no_vad forced on."""
    hass = Mock()
    connection = Mock()
    registered = []

    with (
        patch(
            "custom_components.phone_assist_tools.assist_pipeline.websocket_api.async_register_command",
            side_effect=lambda _hass, handler: registered.append(handler),
        ),
        patch(
            "custom_components.phone_assist_tools.assist_pipeline.websocket_run"
        ) as core_run,
    ):
        async_setup_push_to_talk_websocket(hass)
        registered[1](
            hass,
            connection,
            {
                "id": 7,
                "type": "phone_assist_tools/assist_pipeline/run",
                "start_stage": "stt",
                "end_stage": "intent",
                "input": {"sample_rate": 16000},
            },
        )

    forwarded = core_run.call_args.args[2]
    assert forwarded["type"] == "assist_pipeline/run"
    assert forwarded["input"] == {"sample_rate": 16000, "no_vad": True}


def test_capabilities_advertise_push_to_talk() -> None:
    """Older app/server pairs can negotiate the optional endpoint safely."""
    hass = Mock()
    connection = Mock()
    registered = []

    with patch(
        "custom_components.phone_assist_tools.assist_pipeline.websocket_api.async_register_command",
        side_effect=lambda _hass, handler: registered.append(handler),
    ):
        async_setup_push_to_talk_websocket(hass)
        registered[0](hass, connection, {"id": 9, "type": "phone_assist_tools/capabilities"})

    connection.send_result.assert_called_once_with(9, {"push_to_talk_pipeline": True})

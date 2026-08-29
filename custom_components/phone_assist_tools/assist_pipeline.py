"""Push-to-talk Assist pipeline WebSocket compatibility endpoint."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.components.assist_pipeline.websocket_api import websocket_run
from homeassistant.core import HomeAssistant, callback

from .const import WS_CAPABILITIES, WS_PUSH_TO_TALK_PIPELINE


@callback
def async_setup_push_to_talk_websocket(hass: HomeAssistant) -> None:
    """Expose Core's pipeline runner with STT VAD explicitly disabled."""

    @websocket_api.websocket_command({vol.Required("type"): WS_CAPABILITIES})
    @callback
    def websocket_capabilities(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        connection.send_result(msg["id"], {"push_to_talk_pipeline": True})

    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_PUSH_TO_TALK_PIPELINE,
            vol.Required("start_stage"): str,
            vol.Required("end_stage"): str,
            vol.Required("input"): dict,
            vol.Optional("pipeline"): str,
            vol.Optional("conversation_id"): vol.Any(str, None),
            vol.Optional("device_id"): vol.Any(str, None),
            vol.Optional("timeout"): vol.Any(float, int),
        }
    )
    @callback
    def websocket_push_to_talk_pipeline(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        forwarded = dict(msg)
        forwarded["type"] = "assist_pipeline/run"
        forwarded["input"] = {**msg["input"], "no_vad": True}
        # The Core handler has already been decorated to schedule its async work.
        websocket_run(hass, connection, forwarded)

    websocket_api.async_register_command(hass, websocket_capabilities)
    websocket_api.async_register_command(hass, websocket_push_to_talk_pipeline)

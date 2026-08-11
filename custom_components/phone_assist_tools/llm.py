"""Direct LLM tool contributions for Home Assistant versions that support them."""

from __future__ import annotations

from typing import override

from homeassistant.components import llm
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.llm import (
    LLM_API_ASSIST,
    LLMContext,
    Tool,
    ToolInput,
)
from homeassistant.util.json import JsonObjectType

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
    TIMER_MESSAGE,
    TIMER_SECONDS,
    TIMER_SKIP_UI,
)
from .coordinator import (
    async_dispatch_and_wait,
    native_mobile_app_commands,
    supports_phone_command,
)
from .schema import (
    ALARM_PARAMETERS,
    MEDIA_PARAMETERS,
    TIMER_PARAMETERS,
    normalize_media_query,
)


class SetPhoneAlarmTool(Tool):
    """Set an alarm locally on the phone that initiated Assist."""

    name = "SetPhoneAlarm"
    description = (
        "Set an alarm at a specific local clock time on the Android phone that "
        "started this Assist request. Use this for 'at 7:30' requests; do not "
        "substitute a Home Assistant timer."
    )
    parameters = ALARM_PARAMETERS

    @override
    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        """Set an alarm and return only after a positive phone acknowledgement."""
        args = self.parameters(tool_input.tool_args)
        command_data = {
            ALARM_HOUR: args["hour"],
            ALARM_MINUTE: args["minute"],
            ALARM_SKIP_UI: True,
        }
        if label := args.get("label"):
            command_data[ALARM_MESSAGE] = label

        result = await async_dispatch_and_wait(
            hass,
            device_id=llm_context.device_id,
            command=COMMAND_ALARM,
            command_data=command_data,
            action_name="alarm",
            context=llm_context.context,
        )
        return {
            **result,
            "alarm": {
                "hour": args["hour"],
                "minute": args["minute"],
                "label": args.get("label"),
            },
        }


class SetPhoneTimerTool(Tool):
    """Set a countdown timer locally on the phone that initiated Assist."""

    name = "SetPhoneTimer"
    description = (
        "Set a countdown timer on the Android phone that started this Assist "
        "request. Use only for a duration such as 'five minutes'; do not use it "
        "for an alarm at a specific clock time."
    )
    parameters = TIMER_PARAMETERS

    @override
    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        """Set a timer and return only after a positive phone acknowledgement."""
        args = self.parameters(tool_input.tool_args)
        command_data = {
            TIMER_SECONDS: args["duration_seconds"],
            TIMER_SKIP_UI: True,
        }
        if label := args.get("label"):
            command_data[TIMER_MESSAGE] = label

        result = await async_dispatch_and_wait(
            hass,
            device_id=llm_context.device_id,
            command=COMMAND_TIMER,
            command_data=command_data,
            action_name="timer",
            context=llm_context.context,
        )
        return {
            **result,
            "timer": {
                "duration_seconds": args["duration_seconds"],
                "label": args.get("label"),
            },
        }


class PlayPhoneMediaTool(Tool):
    """Resume an audiobook or play music on the originating phone."""

    name = "PlayPhoneMedia"
    description = (
        "Resume an audiobook or play music on the Android phone that started this "
        "Assist request. Always omit query for an audiobook; omit it for usual music."
    )
    parameters = MEDIA_PARAMETERS

    @override
    async def async_call(
        self,
        hass: HomeAssistant,
        tool_input: ToolInput,
        llm_context: LLMContext,
    ) -> JsonObjectType:
        """Start media and return after a positive phone acknowledgement."""
        args = self.parameters(tool_input.tool_args)
        command_data = {MEDIA_TYPE: args["media_type"]}
        if query := normalize_media_query(args["media_type"], args.get("query")):
            command_data[MEDIA_QUERY] = query
        return await async_dispatch_and_wait(
            hass,
            device_id=llm_context.device_id,
            command=COMMAND_PLAY_MEDIA,
            command_data=command_data,
            action_name="media playback",
            context=llm_context.context,
        )


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> llm.LLMTools | None:
    """Contribute phone tools only to Assist requests originating on a phone."""
    if api_id != LLM_API_ASSIST:
        return None

    native_commands = native_mobile_app_commands()
    tools: list[Tool] = []
    prompt_parts: list[str] = []
    if COMMAND_ALARM not in native_commands and supports_phone_command(
        hass,
        device_id=llm_context.device_id,
        command=COMMAND_ALARM,
        context=llm_context.context,
    ):
        tools.append(SetPhoneAlarmTool())
        prompt_parts.append(
            "For an alarm at a specific clock time, call SetPhoneAlarm."
        )
    if COMMAND_TIMER not in native_commands and supports_phone_command(
        hass,
        device_id=llm_context.device_id,
        command=COMMAND_TIMER,
        context=llm_context.context,
    ):
        tools.append(SetPhoneTimerTool())
        prompt_parts.append(
            "For a countdown duration, call SetPhoneTimer instead of a Home "
            "Assistant timer intent."
        )
    if COMMAND_PLAY_MEDIA not in native_commands and supports_phone_command(
        hass,
        device_id=llm_context.device_id,
        command=COMMAND_PLAY_MEDIA,
        context=llm_context.context,
    ):
        tools.append(PlayPhoneMediaTool())
        prompt_parts.append(
            "For 'play my book', call PlayPhoneMedia with media_type audiobook and "
            "always omit query. For music, use media_type music and include a query only "
            "when the user names an artist, song, album, or playlist."
        )

    if not tools:
        return None

    return llm.LLMTools(
        tools=tools,
        prompt=(
            " ".join(prompt_parts)
            + " These tools operate the Android phone that "
            "initiated this Assist request."
        ),
    )

"""Tests for custom-integration capability and migration guards."""

from types import SimpleNamespace

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.phone_assist_tools import coordinator, llm
from custom_components.phone_assist_tools.const import COMMAND_ALARM, COMMAND_TIMER
from custom_components.phone_assist_tools.schema import normalize_media_query


def _hass(
    *,
    commands: object,
    owner: str = "user-1",
    websocket_push: bool = True,
    cloud_push: bool = False,
) -> SimpleNamespace:
    app_data = {
        "supported_device_commands": commands,
        "push_websocket_channel": websocket_push,
    }
    if cloud_push:
        app_data.update({"push_token": "configured", "push_url": "configured"})
    entry = SimpleNamespace(data={"user_id": owner, "app_data": app_data})
    return SimpleNamespace(
        data={"mobile_app": {"config_entries": {"webhook-1": entry}}}
    )


@pytest.mark.parametrize(
    ("media_type", "query", "expected"),
    [
        ("audiobook", "current book", None),
        ("audiobook", "The Hobbit", None),
        ("music", "usual music", None),
        ("music", " My Usual Music ", None),
        ("music", "My Supermix", "My Supermix"),
    ],
)
def test_media_query_normalization(
    media_type: str, query: str, expected: str | None
) -> None:
    """Generic model placeholders resume media instead of becoming searches."""
    assert normalize_media_query(media_type, query) == expected


@pytest.mark.parametrize(
    ("commands", "command", "expected"),
    [
        ([COMMAND_ALARM], COMMAND_ALARM, True),
        ([COMMAND_ALARM], COMMAND_TIMER, False),
        ([COMMAND_TIMER], COMMAND_ALARM, False),
        ([COMMAND_TIMER], COMMAND_TIMER, True),
        ([COMMAND_ALARM, COMMAND_TIMER], COMMAND_ALARM, True),
        ([], COMMAND_ALARM, False),
        (COMMAND_ALARM, COMMAND_ALARM, False),
    ],
)
def test_commands_are_independently_opted_in(
    monkeypatch: pytest.MonkeyPatch,
    commands: object,
    command: str,
    expected: bool,
) -> None:
    """A command is allowed only when the target registration lists it."""
    monkeypatch.setattr(
        coordinator, "webhook_id_from_device_id", lambda _hass, _device_id: "webhook-1"
    )

    assert (
        coordinator.supports_phone_command(
            _hass(commands=commands),
            device_id="device-1",
            command=command,
            context=SimpleNamespace(user_id="user-1"),
        )
        is expected
    )


def test_command_requires_same_user_and_usable_push(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Capability metadata alone cannot authorize another user or offline app."""
    monkeypatch.setattr(
        coordinator, "webhook_id_from_device_id", lambda _hass, _device_id: "webhook-1"
    )
    context = SimpleNamespace(user_id="user-1")

    assert not coordinator.supports_phone_command(
        _hass(commands=[COMMAND_ALARM], owner="user-2"),
        device_id="device-1",
        command=COMMAND_ALARM,
        context=context,
    )
    assert not coordinator.supports_phone_command(
        _hass(commands=[COMMAND_ALARM], websocket_push=False),
        device_id="device-1",
        command=COMMAND_ALARM,
        context=context,
    )
    assert coordinator.supports_phone_command(
        _hass(
            commands=[COMMAND_ALARM],
            websocket_push=False,
            cloud_push=True,
        ),
        device_id="device-1",
        command=COMMAND_ALARM,
        context=context,
    )


def test_stale_duplicate_routes_to_unique_capable_same_phone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale origin record resolves to the opted-in build on the same phone."""
    physical_device = {
        "app_id": "io.homeassistant.companion.android",
        "device_name": "Pixel 9 Pro Fold",
        "manufacturer": "Google",
        "model": "Pixel 9 Pro Fold",
        "os_name": "Android",
        "user_id": "user-1",
    }
    old_entry = SimpleNamespace(
        data={
            **physical_device,
            "app_data": {"push_websocket_channel": True},
        }
    )
    capable_entry = SimpleNamespace(
        data={
            **physical_device,
            "app_data": {
                "push_websocket_channel": True,
                "supported_device_commands": [COMMAND_TIMER],
            },
        }
    )
    hass = SimpleNamespace(
        data={
            "mobile_app": {
                "config_entries": {
                    "old-webhook": old_entry,
                    "capable-webhook": capable_entry,
                },
                "devices": {"capable-webhook": SimpleNamespace(id="capable-device")},
            }
        }
    )
    monkeypatch.setattr(
        coordinator,
        "webhook_id_from_device_id",
        lambda _hass, _device_id: "old-webhook",
    )

    assert (
        coordinator.resolve_phone_command_device_id(
            hass,
            device_id="old-device",
            command=COMMAND_TIMER,
            context=SimpleNamespace(user_id="user-1"),
        )
        == "capable-device"
    )

    hass.data["mobile_app"]["config_entries"]["second-capable"] = capable_entry
    hass.data["mobile_app"]["devices"]["second-capable"] = SimpleNamespace(
        id="second-device"
    )
    assert (
        coordinator.resolve_phone_command_device_id(
            hass,
            device_id="old-device",
            command=COMMAND_TIMER,
            context=SimpleNamespace(user_id="user-1"),
        )
        is None
    )


def test_direct_tools_follow_each_capability(monkeypatch: pytest.MonkeyPatch) -> None:
    """Direct discovery exposes only locally enabled, non-native tools."""
    monkeypatch.setattr(llm, "native_mobile_app_commands", frozenset)
    monkeypatch.setattr(
        llm,
        "supports_phone_command",
        lambda _hass, *, command, **_kwargs: command == COMMAND_TIMER,
    )
    llm_context = SimpleNamespace(
        device_id="device-1", context=SimpleNamespace(user_id="user-1")
    )

    result = llm.async_get_tools(SimpleNamespace(), llm_context, "assist")

    assert result is not None
    assert [tool.name for tool in result.tools] == ["SetPhoneTimer"]
    assert "SetPhoneTimer" in result.prompt
    assert "SetPhoneAlarm" not in result.prompt


def test_native_tools_suppress_compatibility_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Core-native command is not contributed a second time by the shim."""
    monkeypatch.setattr(
        llm, "native_mobile_app_commands", lambda: frozenset({COMMAND_ALARM})
    )
    monkeypatch.setattr(llm, "supports_phone_command", lambda *_args, **_kwargs: True)
    llm_context = SimpleNamespace(
        device_id="device-1", context=SimpleNamespace(user_id="user-1")
    )

    result = llm.async_get_tools(SimpleNamespace(), llm_context, "assist")

    assert result is not None
    assert [tool.name for tool in result.tools] == ["SetPhoneTimer", "PlayPhoneMedia"]


def test_native_command_detection_is_concrete_and_independent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detection requires Core's capability contract and concrete tool class."""
    native_const = SimpleNamespace(
        ATTR_SUPPORTED_DEVICE_COMMANDS="supported_device_commands",
        DATA_DEVICE_COMMAND_MANAGER="device_command_manager",
        COMMAND_ALARM=COMMAND_ALARM,
        COMMAND_TIMER=COMMAND_TIMER,
    )
    native_llm = SimpleNamespace(
        SetPhoneAlarmTool=SimpleNamespace(name="mobile_app_set_alarm")
    )

    monkeypatch.setattr(coordinator, "mobile_app_const", native_const)
    monkeypatch.setattr(coordinator, "mobile_app_llm", native_llm)

    assert coordinator.native_mobile_app_commands() == frozenset({COMMAND_ALARM})


def test_old_core_has_no_native_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Core without the capability contract has no native commands."""
    monkeypatch.setattr(coordinator, "mobile_app_const", SimpleNamespace())
    monkeypatch.setattr(coordinator, "mobile_app_llm", SimpleNamespace())

    assert coordinator.native_mobile_app_commands() == frozenset()


@pytest.mark.asyncio
async def test_dispatch_rechecks_capability_before_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale LLM tool cannot dispatch after its local permission is disabled."""
    monkeypatch.setattr(
        coordinator,
        "resolve_phone_command_device_id",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(HomeAssistantError, match="command is not enabled"):
        await coordinator.async_dispatch_and_wait(
            SimpleNamespace(),
            device_id="device-1",
            command=COMMAND_ALARM,
            command_data={},
            action_name="alarm",
            context=SimpleNamespace(user_id="user-1"),
        )

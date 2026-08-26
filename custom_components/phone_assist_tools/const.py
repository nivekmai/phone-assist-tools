"""Constants for Phone Assist Tools."""

from typing import Final

DOMAIN: Final = "phone_assist_tools"

SERVICE_ACKNOWLEDGE: Final = "acknowledge"

APP_DATA_PERSONAL_DATA_PUBLIC_KEY: Final = "assist_personal_data_public_key"
APP_DATA_PERSONAL_DATA_SCOPES: Final = "assist_personal_data_scopes"
PERSONAL_DATA_SCOPE_GMAIL: Final = "gmail_readonly"
PERSONAL_DATA_SCOPE_DRIVE: Final = "drive_readonly"
SUPPORTED_PERSONAL_DATA_SCOPES: Final = frozenset(
    {PERSONAL_DATA_SCOPE_GMAIL, PERSONAL_DATA_SCOPE_DRIVE}
)

WS_CHALLENGE: Final = "phone_assist_tools/personal_data/challenge"
WS_AUTHORIZE: Final = "phone_assist_tools/personal_data/authorize"
CHALLENGE_TTL_SECONDS: Final = 30.0
PENDING_GRANT_TTL_SECONDS: Final = 20.0
ACTIVE_GRANT_TTL_SECONDS: Final = 300.0
MAX_PUBLIC_KEY_LENGTH: Final = 1024
MAX_SIGNATURE_LENGTH: Final = 1024

ATTR_REQUEST_ID: Final = "request_id"
ATTR_SUCCESS: Final = "success"
ATTR_ERROR: Final = "error"

COMMAND_ALARM: Final = "command_alarm"
COMMAND_PLAY_MEDIA: Final = "command_play_media"
COMMAND_TIMER: Final = "command_timer"

ALARM_HOUR: Final = "alarm_hour"
ALARM_MINUTE: Final = "alarm_minute"
ALARM_MESSAGE: Final = "alarm_message"
ALARM_SKIP_UI: Final = "alarm_skip_ui"

TIMER_SECONDS: Final = "timer_seconds"
TIMER_MESSAGE: Final = "timer_message"
TIMER_SKIP_UI: Final = "timer_skip_ui"

MEDIA_TYPE: Final = "media_type"
MEDIA_QUERY: Final = "media_query"
MEDIA_TYPE_AUDIOBOOK: Final = "audiobook"
MEDIA_TYPE_MUSIC: Final = "music"

PHONE_TOOL_REQUEST_ID: Final = "phone_tool_request_id"
SUPPORTED_DEVICE_COMMANDS: Final = "supported_device_commands"

ACK_TIMEOUT_SECONDS: Final = 12.0
MAX_TIMER_SECONDS: Final = 24 * 60 * 60
MAX_LABEL_LENGTH: Final = 200
MAX_ERROR_LENGTH: Final = 1000
MAX_REQUEST_ID_LENGTH: Final = 128

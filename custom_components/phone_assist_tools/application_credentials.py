"""Application credentials platform for Phone Assist Tools Google access."""

from homeassistant.components.application_credentials import AuthorizationServer
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import (
    AUTH_CALLBACK_PATH,
    MY_AUTH_CALLBACK_PATH,
)


async def async_get_authorization_server(hass: HomeAssistant) -> AuthorizationServer:
    """Return Google's OAuth authorization server."""
    return AuthorizationServer(
        "https://accounts.google.com/o/oauth2/v2/auth",
        "https://oauth2.googleapis.com/token",
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Return help links and the redirect URL needed in Google Cloud."""
    redirect_url = (
        MY_AUTH_CALLBACK_PATH
        if "my" in hass.config.components
        else f"{hass.config.external_url or 'https://YOUR_DOMAIN:PORT'}{AUTH_CALLBACK_PATH}"
    )
    return {
        "oauth_consent_url": "https://console.cloud.google.com/apis/credentials/consent",
        "oauth_creds_url": "https://console.cloud.google.com/apis/credentials",
        "redirect_url": redirect_url,
    }

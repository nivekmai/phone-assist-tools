"""OAuth config flow for gated Google Workspace access."""

import logging
from collections.abc import Mapping
from typing import Any, override

from aiohttp import ClientResponseError
from homeassistant.config_entries import (
    SOURCE_REAUTH,
    SOURCE_RECONFIGURE,
    ConfigFlowResult,
)
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN

OAUTH2_SCOPES = [
    "openid",
    "email",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
]
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"


class OAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle Google OAuth for device-gated Workspace tools."""

    DOMAIN = DOMAIN

    @property
    @override
    def logger(self) -> logging.Logger:
        return logging.getLogger(__name__)

    @property
    @override
    def extra_authorize_data(self) -> dict[str, Any]:
        return {
            "scope": " ".join(OAUTH2_SCOPES),
            "access_type": "offline",
            "prompt": "consent",
        }

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_user(user_input)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(step_id="reauth_confirm")
        return await self.async_step_user()

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        token = data[CONF_TOKEN][CONF_ACCESS_TOKEN]
        try:
            async with async_get_clientsession(self.hass).get(
                USERINFO_URL, headers={"Authorization": f"Bearer {token}"}
            ) as response:
                response.raise_for_status()
                profile = await response.json()
            email = profile["email"]
            if not isinstance(email, str) or not email:
                raise ValueError("Google profile did not include an email address")
        except (ClientResponseError, KeyError, ValueError):
            self.logger.exception("Unable to validate Google access")
            return self.async_abort(reason="access_not_configured")

        await self.async_set_unique_id(email)
        if self.source not in (SOURCE_REAUTH, SOURCE_RECONFIGURE):
            if self._async_current_entries():
                return self.async_abort(reason="already_configured")
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=email, data=data)

        entry = (
            self._get_reauth_entry()
            if self.source == SOURCE_REAUTH
            else self._get_reconfigure_entry()
        )
        self._abort_if_unique_id_mismatch(reason="wrong_account")
        return self.async_update_reload_and_abort(entry, data=data)

"""Short-lived, device-signed authorization for personal-data Assist tools."""

from __future__ import annotations

import base64
import logging
import secrets
from dataclasses import dataclass, field
from time import monotonic
from typing import Any

import voluptuous as vol
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from homeassistant.components import websocket_api
from homeassistant.components.mobile_app.const import CONF_USER_ID, DATA_CONFIG_ENTRIES
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .const import (
    ACTIVE_GRANT_TTL_SECONDS,
    APP_DATA_PERSONAL_DATA_PUBLIC_KEY,
    APP_DATA_PERSONAL_DATA_SCOPES,
    CHALLENGE_TTL_SECONDS,
    DOMAIN,
    MAX_PUBLIC_KEY_LENGTH,
    MAX_SIGNATURE_LENGTH,
    PENDING_GRANT_TTL_SECONDS,
    SUPPORTED_PERSONAL_DATA_SCOPES,
    WS_AUTHORIZE,
    WS_CHALLENGE,
)

_LOGGER = logging.getLogger(__name__)
_MOBILE_APP_DOMAIN = "mobile_app"
_APP_DATA = "app_data"
_CANONICAL_PREFIX = "phone_assist_tools:v1"

DATA_AUTHORIZER: HassKey[PersonalDataAuthorizer]


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """Personal-data identity advertised by one mobile-app registration."""

    user_id: str
    public_key: str
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class Challenge:
    """One server-issued challenge."""

    webhook_id: str
    user_id: str
    nonce: str
    scopes: frozenset[str]
    expires_at: float


@dataclass(frozen=True, slots=True)
class Grant:
    """An authorization waiting for or bound to one Assist context."""

    webhook_id: str
    user_id: str
    scopes: frozenset[str]
    expires_at: float


@dataclass(slots=True)
class PersonalDataAuthorizer:
    """Keep challenges and grants in memory so they cannot survive a restart."""

    challenges: dict[str, Challenge] = field(default_factory=dict)
    pending: dict[tuple[str, str], Grant] = field(default_factory=dict)
    active: dict[str, Grant] = field(default_factory=dict)

    @callback
    def issue_challenge(
        self, webhook_id: str, identity: DeviceIdentity
    ) -> tuple[str, str]:
        """Issue a fresh challenge to an enrolled registration."""
        self._purge()
        challenge_id = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(32)
        self.challenges[challenge_id] = Challenge(
            webhook_id=webhook_id,
            user_id=identity.user_id,
            nonce=nonce,
            scopes=identity.scopes,
            expires_at=monotonic() + CHALLENGE_TTL_SECONDS,
        )
        return challenge_id, nonce

    @callback
    def authorize(
        self,
        *,
        challenge_id: str,
        webhook_id: str,
        identity: DeviceIdentity,
        signature_b64: str,
    ) -> bool:
        """Verify and consume a challenge, creating one pending grant."""
        self._purge()
        challenge = self.challenges.pop(challenge_id, None)
        if (
            challenge is None
            or challenge.webhook_id != webhook_id
            or challenge.user_id != identity.user_id
            or challenge.scopes != identity.scopes
        ):
            return False

        payload = canonical_challenge(
            challenge_id=challenge_id,
            nonce=challenge.nonce,
            webhook_id=webhook_id,
        )
        try:
            public_key_der = base64.b64decode(identity.public_key, validate=True)
            signature = base64.b64decode(signature_b64, validate=True)
            public_key = serialization.load_der_public_key(public_key_der)
            if not isinstance(public_key, ec.EllipticCurvePublicKey):
                return False
            public_key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
        except (ValueError, TypeError, InvalidSignature):
            return False

        self.pending[(identity.user_id, webhook_id)] = Grant(
            webhook_id=webhook_id,
            user_id=identity.user_id,
            scopes=identity.scopes,
            expires_at=monotonic() + PENDING_GRANT_TTL_SECONDS,
        )
        return True

    @callback
    def scopes_for_context(
        self,
        *,
        context: Context | None,
        device_webhook_id: str | None,
    ) -> frozenset[str]:
        """Bind a pending grant to an Assist context, or return its active scopes."""
        self._purge()
        if (
            context is None
            or context.user_id is None
            or not device_webhook_id
        ):
            return frozenset()

        context_id = context.id
        active = self.active.get(context_id)
        if active is not None:
            if (
                active.user_id == context.user_id
                and active.webhook_id == device_webhook_id
            ):
                return active.scopes
            return frozenset()

        grant = self.pending.pop((context.user_id, device_webhook_id), None)
        if grant is None:
            return frozenset()
        active = Grant(
            webhook_id=grant.webhook_id,
            user_id=grant.user_id,
            scopes=grant.scopes,
            expires_at=monotonic() + ACTIVE_GRANT_TTL_SECONDS,
        )
        self.active[context_id] = active
        return active.scopes

    @callback
    def clear(self) -> None:
        """Clear all ephemeral authorization state."""
        self.challenges.clear()
        self.pending.clear()
        self.active.clear()

    @callback
    def _purge(self) -> None:
        now = monotonic()
        for mapping in (self.challenges, self.pending, self.active):
            expired = [key for key, value in mapping.items() if value.expires_at <= now]
            for key in expired:
                mapping.pop(key, None)


DATA_AUTHORIZER = HassKey(f"{DOMAIN}.personal_data_authorizer")


def canonical_challenge(*, challenge_id: str, nonce: str, webhook_id: str) -> bytes:
    """Return the byte-exact payload signed by Android and verified by HA."""
    return f"{_CANONICAL_PREFIX}:{challenge_id}:{nonce}:{webhook_id}".encode()


@callback
def _identity_for_connection(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    webhook_id: str,
) -> DeviceIdentity | None:
    """Resolve an enrolled registration owned by the WebSocket user."""
    try:
        entry = hass.data[_MOBILE_APP_DOMAIN][DATA_CONFIG_ENTRIES][webhook_id]
    except KeyError:
        return None
    if entry.data.get(CONF_USER_ID) != connection.user.id:
        return None
    app_data = entry.data.get(_APP_DATA)
    if not isinstance(app_data, dict):
        return None
    public_key = app_data.get(APP_DATA_PERSONAL_DATA_PUBLIC_KEY)
    scopes_value = app_data.get(APP_DATA_PERSONAL_DATA_SCOPES)
    if not isinstance(public_key, str) or not isinstance(scopes_value, list):
        return None
    scopes = frozenset(scopes_value) & SUPPORTED_PERSONAL_DATA_SCOPES
    if not scopes:
        return None
    return DeviceIdentity(connection.user.id, public_key, scopes)


@callback
def async_setup_websocket_api(
    hass: HomeAssistant, authorizer: PersonalDataAuthorizer
) -> None:
    """Register phone authorization WebSocket commands."""

    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_CHALLENGE,
            vol.Required("webhook_id"): vol.All(str, vol.Length(min=1, max=128)),
        }
    )
    @callback
    def websocket_challenge(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        identity = _identity_for_connection(hass, connection, msg["webhook_id"])
        if identity is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_UNAUTHORIZED, "Device is not enrolled"
            )
            return
        challenge_id, nonce = authorizer.issue_challenge(msg["webhook_id"], identity)
        connection.send_result(
            msg["id"],
            {"challenge_id": challenge_id, "nonce": nonce},
        )

    @websocket_api.websocket_command(
        {
            vol.Required("type"): WS_AUTHORIZE,
            vol.Required("webhook_id"): vol.All(str, vol.Length(min=1, max=128)),
            vol.Required("challenge_id"): vol.All(str, vol.Length(min=1, max=128)),
            vol.Required("signature"): vol.All(
                str, vol.Length(min=1, max=MAX_SIGNATURE_LENGTH)
            ),
        }
    )
    @callback
    def websocket_authorize(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        identity = _identity_for_connection(hass, connection, msg["webhook_id"])
        if identity is None or len(identity.public_key) > MAX_PUBLIC_KEY_LENGTH:
            connection.send_error(
                msg["id"], websocket_api.ERR_UNAUTHORIZED, "Device is not enrolled"
            )
            return
        if not authorizer.authorize(
            challenge_id=msg["challenge_id"],
            webhook_id=msg["webhook_id"],
            identity=identity,
            signature_b64=msg["signature"],
        ):
            _LOGGER.warning(
                "Rejected personal-data authorization for mobile registration %s",
                msg["webhook_id"],
            )
            connection.send_error(
                msg["id"], websocket_api.ERR_UNAUTHORIZED, "Invalid device proof"
            )
            return
        connection.send_result(msg["id"], {"authorized": True})

    websocket_api.async_register_command(hass, websocket_challenge)
    websocket_api.async_register_command(hass, websocket_authorize)

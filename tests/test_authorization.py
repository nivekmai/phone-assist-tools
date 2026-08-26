"""Tests for device-signed, one-use personal-data grants."""

import base64
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from custom_components.phone_assist_tools.authorization import (
    DeviceIdentity,
    PersonalDataAuthorizer,
    canonical_challenge,
)


def _identity() -> tuple[DeviceIdentity, ec.EllipticCurvePrivateKey]:
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return (
        DeviceIdentity(
            user_id="user-1",
            public_key=base64.b64encode(public_key).decode(),
            scopes=frozenset({"gmail_readonly"}),
        ),
        private_key,
    )


def test_signed_grant_is_bound_once_then_reused_only_by_context() -> None:
    """A proof creates one pending grant and binds it to the first context."""
    authorizer = PersonalDataAuthorizer()
    identity, private_key = _identity()
    challenge_id, nonce = authorizer.issue_challenge("webhook-1", identity)
    payload = canonical_challenge(
        challenge_id=challenge_id, nonce=nonce, webhook_id="webhook-1"
    )
    signature = private_key.sign(payload, ec.ECDSA(hashes.SHA256()))

    assert authorizer.authorize(
        challenge_id=challenge_id,
        webhook_id="webhook-1",
        identity=identity,
        signature_b64=base64.b64encode(signature).decode(),
    )
    context = SimpleNamespace(id="context-1", user_id="user-1")
    assert authorizer.scopes_for_context(
        context=context, device_webhook_id="webhook-1"
    ) == frozenset({"gmail_readonly"})
    assert authorizer.scopes_for_context(
        context=context, device_webhook_id="webhook-1"
    ) == frozenset({"gmail_readonly"})
    assert not authorizer.scopes_for_context(
        context=SimpleNamespace(id="context-2", user_id="user-1"),
        device_webhook_id="webhook-1",
    )


def test_invalid_signature_consumes_challenge_without_grant() -> None:
    """A bad proof cannot be retried or create a pending grant."""
    authorizer = PersonalDataAuthorizer()
    identity, _private_key = _identity()
    challenge_id, _nonce = authorizer.issue_challenge("webhook-1", identity)

    assert not authorizer.authorize(
        challenge_id=challenge_id,
        webhook_id="webhook-1",
        identity=identity,
        signature_b64=base64.b64encode(b"not a signature").decode(),
    )
    assert not authorizer.pending
    assert challenge_id not in authorizer.challenges

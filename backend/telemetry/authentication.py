"""
Device token authentication.

A device presents a shared secret as a bearer token:

    Authorization: Device <token>

or, for firmware where the Authorization header is inconvenient:

    X-Device-Token: <token>

**What this does and does not guarantee.** The server looks up the SHA-256 hash
of the presented token and compares the stored hash in constant time. That
proves the caller knows the secret. It does *not* verify a signature over the
reading payload, so it does not prove the values were produced by that hardware
or that they were not altered in transit by whoever holds the token. The plan
forbids claiming cryptographic verification that is not implemented, so the
limitation is stated here and in `docs/` rather than glossed over. Transport
confidentiality is HTTPS's job.
"""

import secrets

from rest_framework import authentication, exceptions

from telemetry.models import Device, hash_token

HEADER_PREFIX = "device"


class DeviceUser:
    """
    Minimal principal representing an authenticated device.

    DRF needs `request.user.is_authenticated` to be true for `IsAuthenticated`
    to pass. A deliberately separate type is used rather than making `Device`
    masquerade as a user, so that a role-based permission class can never be
    handed a device by accident - it would raise rather than silently allow.
    """

    is_authenticated = True
    is_anonymous = False
    is_staff = False
    is_superuser = False

    def __init__(self, device: Device):
        self.device = device

    def __str__(self) -> str:
        return f"device:{self.device.pk}"


def extract_token(request) -> str | None:
    """Pull the raw token out of either supported header."""
    header = authentication.get_authorization_header(request).decode("latin-1")
    if header:
        parts = header.split()
        if len(parts) == 2 and parts[0].lower() == HEADER_PREFIX:
            return parts[1]
    return request.headers.get("X-Device-Token") or None


class DeviceTokenAuthentication(authentication.BaseAuthentication):
    """Authenticate a request as a device, or defer to the next auth class."""

    keyword = "Device"

    def authenticate(self, request):
        raw_token = extract_token(request)
        if not raw_token:
            # Not a device request; let JWT/session authentication try.
            return None

        device = Device.objects.filter(token_hash=hash_token(raw_token)).select_related(
            "room__floor__building__organisation"
        ).first()

        # Compare in constant time even though the lookup was by hash, so a
        # near-miss cannot be distinguished by timing.
        if device is None or not secrets.compare_digest(
            device.token_hash, hash_token(raw_token)
        ):
            raise exceptions.AuthenticationFailed("Unknown device token.")

        if not device.is_active:
            raise exceptions.AuthenticationFailed("This device is disabled.")

        return DeviceUser(device), device

    def authenticate_header(self, request) -> str:
        return self.keyword

"""
Minimal EcoTrack API client for the simulator.

Deliberately stdlib-only (`urllib`), so the simulator runs on a bare Python with
no virtualenv and no `requests` install. It talks to the Phase 4 auth endpoints
and the Phase 6 device and ingestion endpoints.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

DEFAULT_TIMEOUT = 20


class ApiError(RuntimeError):
    """An API call failed. Carries the status and decoded body when there is one."""

    def __init__(self, message: str, status: int | None = None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _request(url: str, method: str = "GET", body=None, headers: dict | None = None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Accept", "application/json")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = raw
        raise ApiError(
            f"{method} {url} failed with HTTP {error.code}", error.code, payload
        ) from error
    except urllib.error.URLError as error:
        raise ApiError(
            f"Could not reach {url}: {error.reason}. Is the backend running?"
        ) from error


@dataclass
class EcoTrackClient:
    """Authenticated client for registering devices and posting readings."""

    base_url: str
    access_token: str | None = None

    def __post_init__(self):
        self.base_url = self.base_url.rstrip("/")

    # --- auth ----------------------------------------------------------------

    def login(self, username: str, password: str) -> dict:
        data = _request(
            f"{self.base_url}/api/auth/login/",
            method="POST",
            body={"username": username, "password": password},
        )
        self.access_token = data["access"]
        return data["user"]

    def _auth_headers(self) -> dict:
        if not self.access_token:
            raise ApiError("Not logged in: call login() first.")
        return {"Authorization": f"Bearer {self.access_token}"}

    # --- spaces --------------------------------------------------------------

    def rooms(self) -> list[dict]:
        """Every room the logged-in user can see, flattened from the tree."""
        tree = _request(
            f"{self.base_url}/api/spaces/organisations/tree/", headers=self._auth_headers()
        )
        rooms = []
        for organisation in tree:
            for building in organisation["buildings"]:
                for floor in building["floors"]:
                    for room in floor["rooms"]:
                        rooms.append(
                            {
                                "id": room["id"],
                                "name": room["name"],
                                "organisation": organisation["name"],
                            }
                        )
        return rooms

    # --- devices -------------------------------------------------------------

    def devices(self) -> list[dict]:
        results: list[dict] = []
        url = f"{self.base_url}/api/devices/"
        while url:
            page = _request(url, headers=self._auth_headers())
            results.extend(page["results"])
            url = page.get("next")
        return results

    def create_device(self, room_id: int, name: str, kind: str, interval_seconds: int) -> dict:
        """Register a device. The response carries the raw token exactly once."""
        return _request(
            f"{self.base_url}/api/devices/",
            method="POST",
            body={
                "room": room_id,
                "name": name,
                "kind": kind,
                "sample_interval_seconds": interval_seconds,
            },
            headers=self._auth_headers(),
        )

    def rotate_token(self, device_id: int) -> str:
        """Re-issue a token for a device that already exists. Admin only."""
        data = _request(
            f"{self.base_url}/api/devices/{device_id}/rotate-token/",
            method="POST",
            headers=self._auth_headers(),
        )
        return data["token"]

    # --- ingestion -----------------------------------------------------------

    def post_readings(
        self, device_token: str, readings: list[dict], buffer_count: int | None = None
    ) -> dict:
        """Post a batch with a device token, not the user JWT."""
        body: dict = {"readings": readings}
        if buffer_count is not None:
            body["buffer_count"] = buffer_count
        body["firmware_version"] = "simulator"

        return _request(
            f"{self.base_url}/api/readings/",
            method="POST",
            body=body,
            headers={"Authorization": f"Device {device_token}"},
        )

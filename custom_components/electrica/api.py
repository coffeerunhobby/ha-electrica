"""HTTP client for the Electrica România customer API (api.myelectrica.ro).

Unlike some Romanian utility portals, Electrica exposes a plain JSON REST API
behind a bearer token, so there is no HTML scraping here: ``/login`` returns an
``app_token`` that authorises every subsequent call. The token is refreshed
transparently when the API answers 401.

The client owns its own :class:`aiohttp.ClientSession` (built on Home
Assistant's shared connector when one is supplied) so the token and headers stay
isolated from the rest of Home Assistant.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

import aiohttp

from .const import (
    CLIENT_DATA_URL,
    CONTRACT_URL,
    CONVENTION_URL,
    HIERARCHY_URL,
    INVOICES_URL,
    LOGIN_URL,
    METER_LIST_URL,
    PAYMENTS_URL,
    READINGS_URL,
    REQUEST_TIMEOUT,
    SET_INDEX_URL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)


# ── Exceptions ──────────────────────────────────────────────────────────────
class ElectricaError(Exception):
    """Base Electrica exception."""


class ElectricaAuthError(ElectricaError):
    """Credentials rejected, or the session could not be renewed."""


class ElectricaConnectionError(ElectricaError):
    """The API could not be reached."""


# ── Value objects ───────────────────────────────────────────────────────────
@dataclass(slots=True)
class ConsumptionPoint:
    """A single NLC ("loc de consum") under a client code.

    ``nlc`` is Electrica's stable identifier for a metering point; it is what the
    integration keys devices and entities on (never the address text).
    """

    nlc: str
    client_code: str
    address: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class ElectricaApiClient:
    """Talks to the Electrica customer API and returns raw decoded payloads."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._token: str | None = None
        self._owns_session = session is None

        if session is not None:
            connector = session.connector
            self._session = aiohttp.ClientSession(
                connector=connector,
                connector_owner=False,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers=self._base_headers(),
            )
        else:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                headers=self._base_headers(),
            )

    @staticmethod
    def _base_headers() -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def close(self) -> None:
        if not self._session.closed:
            await self._session.close()

    # ── Auth ────────────────────────────────────────────────────────────────
    @property
    def token(self) -> str | None:
        return self._token

    async def async_login(self) -> str:
        """Authenticate and cache the bearer token."""
        payload = {"email": self._username, "password": self._password}
        try:
            async with self._session.post(LOGIN_URL, json=payload) as resp:
                if resp.status in (401, 403):
                    raise ElectricaAuthError("Invalid e-mail or password")
                if resp.status >= 500:
                    raise ElectricaConnectionError(
                        f"Electrica API error: HTTP {resp.status}"
                    )
                data = await self._decode(resp)
        except aiohttp.ClientError as err:
            raise ElectricaConnectionError(str(err)) from err

        token = self._extract_token(data)
        if not token:
            # A 200 without a token means the credentials were refused.
            raise ElectricaAuthError(
                self._extract_message(data) or "Login failed (no token returned)"
            )

        self._token = token
        return token

    @staticmethod
    def _extract_token(data: Any) -> str | None:
        """Pull the bearer token out of a login response, tolerating key drift."""
        if not isinstance(data, dict):
            return None
        for key in ("app_token", "token", "access_token", "accessToken"):
            value = data.get(key)
            if isinstance(value, str) and value:
                return value
        # Some responses nest the payload one level down.
        for key in ("data", "result", "user"):
            nested = data.get(key)
            if isinstance(nested, dict):
                token = ElectricaApiClient._extract_token(nested)
                if token:
                    return token
        return None

    @staticmethod
    def _extract_message(data: Any) -> str | None:
        if isinstance(data, dict):
            for key in ("message", "error_message", "msg", "detail"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    async def _decode(resp: aiohttp.ClientResponse) -> Any:
        """Decode a JSON body, tolerating a wrong/missing content-type."""
        try:
            return await resp.json(content_type=None)
        except (aiohttp.ContentTypeError, ValueError):
            text = await resp.text(errors="ignore")
            raise ElectricaError(
                f"Unexpected non-JSON response (HTTP {resp.status}): {text[:200]}"
            ) from None

    # ── Core request helper ─────────────────────────────────────────────────
    async def _request(
        self, method: str, url: str, payload: dict[str, Any] | None = None
    ) -> Any:
        """Issue an authenticated request, logging in / retrying once on 401."""
        if self._token is None:
            await self.async_login()

        for attempt in (1, 2):
            headers = {"Authorization": f"Bearer {self._token}"}
            try:
                async with self._session.request(
                    method, url, json=payload, headers=headers
                ) as resp:
                    if resp.status in (401, 403) and attempt == 1:
                        # Token expired — re-authenticate once and replay.
                        self._token = None
                        await self.async_login()
                        continue
                    if resp.status in (401, 403):
                        raise ElectricaAuthError("Session rejected by Electrica")
                    if resp.status == 404:
                        return None
                    if resp.status >= 400:
                        raise ElectricaError(
                            f"Electrica API error for {url}: HTTP {resp.status}"
                        )
                    return await self._decode(resp)
            except aiohttp.ClientError as err:
                raise ElectricaConnectionError(str(err)) from err

        raise ElectricaAuthError("Could not authenticate with Electrica")

    async def _get(self, url: str) -> Any:
        return await self._request("GET", url)

    async def _post(self, url: str, payload: dict[str, Any]) -> Any:
        return await self._request("POST", url, payload)

    # ── Endpoints ───────────────────────────────────────────────────────────
    async def async_get_hierarchy(self) -> Any:
        """Client codes and their NLCs — the entry point for everything else."""
        return await self._get(HIERARCHY_URL)

    async def async_get_client_data(self, client_code: str) -> Any:
        return await self._get(CLIENT_DATA_URL.format(client_code=client_code))

    async def async_get_contract(self, nlc: str) -> Any:
        return await self._get(CONTRACT_URL.format(nlc=nlc))

    async def async_get_meter_list(self, nlc: str) -> Any:
        return await self._get(METER_LIST_URL.format(nlc=nlc))

    async def async_get_readings(self, client_code: str, nlc: str) -> Any:
        return await self._get(
            READINGS_URL.format(client_code=client_code, nlc=nlc)
        )

    async def async_get_convention(self, nlc: str) -> Any:
        return await self._get(CONVENTION_URL.format(nlc=nlc))

    async def async_get_invoices(self, client_code: str, **extra: Any) -> Any:
        return await self._post(INVOICES_URL, {"client_code": client_code, **extra})

    async def async_get_payments(self, client_code: str, **extra: Any) -> Any:
        return await self._post(PAYMENTS_URL, {"client_code": client_code, **extra})

    async def async_set_index(self, payload: dict[str, Any]) -> Any:
        """Submit a self-read meter index.

        Deliberately takes the payload verbatim: this is the only write the
        integration performs, so the caller stays explicit about what is sent.
        """
        return await self._post(SET_INDEX_URL, payload)

    # ── Convenience ─────────────────────────────────────────────────────────
    async def async_probe_all(self, pause: float = 0.2) -> dict[str, Any]:
        """Fetch one of everything, for development/diagnostics.

        Returns the raw payloads keyed by endpoint so response shapes can be
        inspected before they are modelled.
        """
        result: dict[str, Any] = {"hierarchy": await self.async_get_hierarchy()}
        points = self.extract_points(result["hierarchy"])
        result["points"] = [
            {"nlc": p.nlc, "client_code": p.client_code} for p in points
        ]

        for point in points:
            await asyncio.sleep(pause)
            result[f"contract:{point.nlc}"] = await self.async_get_contract(point.nlc)
            result[f"meters:{point.nlc}"] = await self.async_get_meter_list(point.nlc)
            result[f"readings:{point.nlc}"] = await self.async_get_readings(
                point.client_code, point.nlc
            )
            result[f"convention:{point.nlc}"] = await self.async_get_convention(
                point.nlc
            )

        for client_code in {p.client_code for p in points}:
            await asyncio.sleep(pause)
            result[f"client:{client_code}"] = await self.async_get_client_data(
                client_code
            )
            result[f"invoices:{client_code}"] = await self.async_get_invoices(
                client_code
            )
            result[f"payments:{client_code}"] = await self.async_get_payments(
                client_code
            )

        return result

    @staticmethod
    def extract_points(hierarchy: Any) -> list[ConsumptionPoint]:
        """Walk the account hierarchy and collect every (client_code, NLC) pair.

        The exact nesting is discovered at runtime, so this walks the structure
        looking for the identifying keys rather than assuming a fixed shape.
        """
        points: list[ConsumptionPoint] = []
        seen: set[tuple[str, str]] = set()

        def _walk(node: Any, client_code: str | None) -> None:
            if isinstance(node, list):
                for item in node:
                    _walk(item, client_code)
                return
            if not isinstance(node, dict):
                return

            code = client_code
            for key in ("client_code", "clientCode", "cod_client", "codClient"):
                value = node.get(key)
                if value:
                    code = str(value)
                    break

            nlc = None
            for key in ("nlc", "NLC", "nlc_code", "nlcCode", "pod", "POD"):
                value = node.get(key)
                if value:
                    nlc = str(value)
                    break

            if nlc and code and (code, nlc) not in seen:
                seen.add((code, nlc))
                address = None
                for key in ("address", "adresa", "consumption_address", "adresa_consum"):
                    value = node.get(key)
                    if isinstance(value, str) and value:
                        address = value
                        break
                points.append(
                    ConsumptionPoint(nlc=nlc, client_code=code, address=address)
                )

            for value in node.values():
                if isinstance(value, (dict, list)):
                    _walk(value, code)

        _walk(hierarchy, None)
        return points

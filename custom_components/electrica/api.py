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
from datetime import date, timedelta
from dataclasses import dataclass, field
from typing import Any, Final

import aiohttp

from .const import (
    CLIENT_DATA_URL,
    HISTORY_LOOKBACK_DAYS,
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
            "Accept": "application/json, text/plain, */*",
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
        """Authenticate and cache the bearer token.

        The API is Romanian-localised: the password field is ``parola``, and a
        successful body carries ``error: false`` alongside ``app_token``.
        """
        payload = {"email": self._username, "parola": self._password}
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

        # The API returns HTTP 200 with ``error: true`` for bad credentials.
        if isinstance(data, dict) and data.get("error") is True:
            raise ElectricaAuthError(
                self._extract_message(data) or "Invalid e-mail or password"
            )

        token = self._extract_token(data)
        if not token:
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

    @staticmethod
    def _date_range(lookback_days: int = HISTORY_LOOKBACK_DAYS) -> tuple[str, str]:
        """(start, end) as YYYY-MM-DD, ending today."""
        today = date.today()
        start = today - timedelta(days=lookback_days)
        return start.isoformat(), today.isoformat()

    async def async_get_invoices(
        self, client_code: str, *, unpaid_only: bool = False
    ) -> Any:
        """Invoice history for a client code (defaults to the last two years)."""
        start_date, end_date = self._date_range()
        return await self._get(
            INVOICES_URL.format(
                client_code=client_code,
                start_date=start_date,
                end_date=end_date,
                unpaid=str(unpaid_only).lower(),
            )
        )

    async def async_get_payments(self, client_code: str) -> Any:
        """Payment history for a client code (defaults to the last two years)."""
        start_date, end_date = self._date_range()
        return await self._get(
            PAYMENTS_URL.format(
                client_code=client_code,
                start_date=start_date,
                end_date=end_date,
            )
        )

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

    # Key aliases, compared lower-cased. Electrica's payloads are SAP-derived
    # (``IdLocConsum``, ``ClientCode``), but spellings vary between endpoints,
    # so match case-insensitively against a set of known names.
    _NLC_KEYS: Final = ("idlocconsum", "nlc", "nlc_code", "nlccode", "pod")
    _CLIENT_KEYS: Final = ("clientcode", "client_code", "cod_client", "codclient")

    @staticmethod
    def _first(node: dict[str, Any], names: tuple[str, ...]) -> str | None:
        """Return the first non-empty value whose key matches (case-insensitive)."""
        for key, value in node.items():
            if key.lower() in names and value not in (None, ""):
                return str(value)
        return None

    @staticmethod
    def format_address(node: dict[str, Any]) -> str | None:
        """Build a readable address from Electrica's split address fields.

        Electrica returns Street/HouseNumber/Building/Entrance/Floor/RoomNumber
        as separate keys; joined they make a sensible device name.
        """
        get = lambda k: str(node.get(k) or "").strip()  # noqa: E731
        street = " ".join(x for x in (get("Street"), get("HouseNumber")) if x)
        parts = [
            street,
            f"bl. {get('Building')}" if get("Building") else "",
            f"sc. {get('Entrance')}" if get("Entrance") else "",
            f"et. {get('Floor')}" if get("Floor") else "",
            f"ap. {get('RoomNumber')}" if get("RoomNumber") else "",
            get("City"),
        ]
        joined = ", ".join(p for p in parts if p)
        return joined or None

    @classmethod
    def extract_points(cls, hierarchy: Any) -> list[ConsumptionPoint]:
        """Walk the account hierarchy and collect every (client_code, NLC) pair.

        The nesting is discovered at runtime rather than assumed, so added levels
        in the SAP payload do not break discovery.
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

            # A client code seen at this level applies to everything beneath it.
            code = cls._first(node, cls._CLIENT_KEYS) or client_code
            nlc = cls._first(node, cls._NLC_KEYS)

            if nlc and code and (code, nlc) not in seen:
                seen.add((code, nlc))
                points.append(
                    ConsumptionPoint(
                        nlc=nlc,
                        client_code=code,
                        address=cls.format_address(node),
                        extra={
                            k: v
                            for k, v in node.items()
                            if not isinstance(v, (dict, list))
                        },
                    )
                )

            for value in node.values():
                if isinstance(value, (dict, list)):
                    _walk(value, code)

        _walk(hierarchy, None)
        return points

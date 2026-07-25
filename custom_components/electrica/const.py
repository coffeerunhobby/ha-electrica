"""Constants for the Electrica România integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "electrica"

MANUFACTURER: Final = "Electrica România"
MODEL: Final = "Electrica - cont online"
ATTRIBUTION: Final = "Date furnizate de myelectrica.ro"

# ── Config / option keys ────────────────────────────────────────────────────
CONF_USERNAME: Final = "username"
CONF_PASSWORD: Final = "password"
CONF_CLIENT_CODE: Final = "client_code"
CONF_NLC_LIST: Final = "nlc_list"
CONF_UPDATE_INTERVAL: Final = "update_interval"
CONF_HISTORY_LIMIT: Final = "history_limit"

# ── Defaults / bounds ───────────────────────────────────────────────────────
# Electrica bills monthly and meter readings change at most daily, so polling
# hard buys nothing; default to a few times a day.
DEFAULT_UPDATE_INTERVAL_HOURS: Final = 6
MIN_UPDATE_INTERVAL_HOURS: Final = 1
MAX_UPDATE_INTERVAL_HOURS: Final = 24

DEFAULT_HISTORY_LIMIT: Final = 12
MIN_HISTORY_LIMIT: Final = 1
MAX_HISTORY_LIMIT: Final = 24

CURRENCY_RON: Final = "RON"

# ── Local storage ───────────────────────────────────────────────────────────
STORAGE_VERSION: Final = 1
# The password-encryption key lives in its own store, deliberately separate from
# the config entry holding the ciphertext, so leaking one file is not enough.
STORAGE_KEY_SECRET: Final = f"{DOMAIN}_key"
# Locally recorded meter readings plus which PAC windows have been submitted.
STORAGE_KEY_READINGS: Final = f"{DOMAIN}_readings"

# ── Electrica REST API ──────────────────────────────────────────────────────
# The myelectrica.ro portal is backed by a plain JSON API secured with a bearer
# token obtained from /login (no 2FA), so unlike a scraped portal the payloads
# are stable and cheap to parse.
BASE_URL: Final = "https://api.myelectrica.ro/api"

LOGIN_URL: Final = f"{BASE_URL}/login"
# Account tree: the client codes owned by the login and the NLC (loc de consum)
# under each one. This is the entry point every other call keys off.
HIERARCHY_URL: Final = f"{BASE_URL}/account-data-hierarchy"
CLIENT_DATA_URL: Final = f"{BASE_URL}/client-data/{{client_code}}"
CONTRACT_URL: Final = f"{BASE_URL}/contract-nlc-details/{{nlc}}"
# Invoices/payments take the date range as path segments (YYYY-MM-DD), and
# invoices additionally take an "unpaid only" flag as "true"/"false".
INVOICES_URL: Final = (
    f"{BASE_URL}/client-code-invoices"
    "/{client_code}/{start_date}/{end_date}/{unpaid}"
)
PAYMENTS_URL: Final = (
    f"{BASE_URL}/client-code-payments/{{client_code}}/{{start_date}}/{{end_date}}"
)
# How far back to ask for invoice/payment history.
HISTORY_LOOKBACK_DAYS: Final = 730
METER_LIST_URL: Final = f"{BASE_URL}/meter-list/{{nlc}}"
READINGS_URL: Final = f"{BASE_URL}/readings/{{client_code}}/{{nlc}}"
# NB: "consumtion" is Electrica's own spelling in the endpoint path.
CONVENTION_URL: Final = f"{BASE_URL}/consumtion-convention/{{nlc}}"
SET_INDEX_URL: Final = f"{BASE_URL}/set-index"

REQUEST_TIMEOUT: Final = 30

USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)

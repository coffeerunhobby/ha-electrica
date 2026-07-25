"""Local dev probe for the Electrica România API client.

Runs the *real* ``custom_components/electrica/api.py`` against api.myelectrica.ro
outside Home Assistant, so the login + endpoint shapes can be verified with a
real account. Development tool only — not shipped to Home Assistant.

Credentials come from ``tools/.electrica_creds.json`` (git-ignored):

    {"accounts": [{"label": "primary", "username": "...", "password": "..."}]}

Usage:
    python tools/probe_electrica.py login              # verify credentials
    python tools/probe_electrica.py hierarchy          # account tree (redacted)
    python tools/probe_electrica.py probe              # hit every endpoint
    python tools/probe_electrica.py keys <file>        # show shape of a raw dump

IMPORTANT — privacy: output is REDACTED by default. Real identifiers (NLC,
client codes, names, addresses, e-mails, IBANs) are masked so they never end up
in logs or terminal transcripts. Raw payloads are written to
``tools/.electrica_raw.json`` (git-ignored) for local inspection only.
Pass ``--raw`` to disable masking (avoid unless strictly necessary).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PKG_DIR = os.path.join(ROOT, "custom_components", "electrica")
CREDS_FILE = os.path.join(HERE, ".electrica_creds.json")
RAW_FILE = os.path.join(HERE, ".electrica_raw.json")


def _load_api() -> types.ModuleType:
    """Load const + api from the integration without importing Home Assistant."""
    pkg_name = "electricaprobe"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [PKG_DIR]
    sys.modules[pkg_name] = pkg

    def _load(mod_name: str) -> types.ModuleType:
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{mod_name}", os.path.join(PKG_DIR, f"{mod_name}.py")
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{mod_name}"] = module
        spec.loader.exec_module(module)
        return module

    _load("const")
    return _load("api")


api = _load_api()

# ── Redaction ───────────────────────────────────────────────────────────────
# Keys whose values are personal data. Matched case-insensitively as substrings.
SENSITIVE_KEYS = (
    "nlc", "pod", "client_code", "clientcode", "cod_client", "codclient",
    "cont", "account", "iban", "name", "nume", "prenume", "denumire",
    "address", "adresa", "strada", "street", "city", "oras", "localitate",
    "email", "mail", "phone", "telefon", "cnp", "cui", "serie", "meter",
    "contor", "token", "password", "parola",
)

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RE_LONGNUM = re.compile(r"\b\d{6,}\b")


def _mask_scalar(value):
    if isinstance(value, bool) or value is None:
        return value
    text = str(value)
    if not text:
        return value
    if len(text) <= 4:
        return "***"
    return f"{text[:2]}…{text[-2:]} [len {len(text)}]"


def redact(node, *, enabled: bool = True):
    """Recursively mask personal data, keeping structure and types visible."""
    if not enabled:
        return node
    if isinstance(node, list):
        return [redact(item, enabled=enabled) for item in node]
    if isinstance(node, dict):
        out = {}
        for key, value in node.items():
            if isinstance(value, (dict, list)):
                out[key] = redact(value, enabled=enabled)
            elif any(s in key.lower() for s in SENSITIVE_KEYS):
                out[key] = _mask_scalar(value)
            elif isinstance(value, str) and (
                RE_EMAIL.search(value) or RE_LONGNUM.search(value)
            ):
                out[key] = _mask_scalar(value)
            else:
                out[key] = value
        return out
    return node


def shape(node, depth: int = 0, max_depth: int = 3):
    """Describe a payload's structure (keys and types) without any values."""
    pad = "  " * depth
    if isinstance(node, dict):
        lines = []
        for key, value in node.items():
            if isinstance(value, (dict, list)) and depth < max_depth:
                lines.append(f"{pad}{key}:")
                lines.append(shape(value, depth + 1, max_depth))
            else:
                kind = type(value).__name__
                if isinstance(value, list):
                    kind = f"list[{len(value)}]"
                lines.append(f"{pad}{key}: <{kind}>")
        return "\n".join(x for x in lines if x)
    if isinstance(node, list):
        if not node:
            return f"{pad}(empty list)"
        return f"{pad}[{len(node)} items] first:\n" + shape(
            node[0], depth + 1, max_depth
        )
    return f"{pad}<{type(node).__name__}>"


def _accounts() -> list[dict]:
    if not os.path.exists(CREDS_FILE):
        raise SystemExit(
            f"Missing {CREDS_FILE}\n"
            'Create it as: {"accounts": [{"label": "primary", '
            '"username": "...", "password": "..."}]}'
        )
    with open(CREDS_FILE, encoding="utf-8") as fh:
        data = json.load(fh)
    accounts = data.get("accounts")
    if not accounts:
        accounts = [data] if data.get("username") else []
    if not accounts:
        raise SystemExit("No accounts configured in the credentials file.")
    return accounts


def _pick(label: str | None) -> dict:
    accounts = _accounts()
    if label:
        for account in accounts:
            if account.get("label") == label:
                return account
        raise SystemExit(f"No account labelled {label!r}")
    return accounts[0]


def _client(account: dict):
    return api.ElectricaApiClient(account["username"], account["password"])


async def _cmd_login(label: str | None) -> None:
    account = _pick(label)
    client = _client(account)
    try:
        token = await client.async_login()
        print(f"login OK for account {account.get('label', '?')!r}")
        print(f"token: {_mask_scalar(token)}")
    finally:
        await client.close()


async def _cmd_hierarchy(label: str | None, raw: bool) -> None:
    account = _pick(label)
    client = _client(account)
    try:
        data = await client.async_get_hierarchy()
        print("── hierarchy SHAPE ──")
        print(shape(data))
        print("\n── hierarchy (redacted) ──")
        print(json.dumps(redact(data, enabled=not raw), indent=2, ensure_ascii=False)[:3000])
        points = api.ElectricaApiClient.extract_points(data)
        print(f"\nconsumption points found: {len(points)}")
        for point in points:
            print(
                f"  nlc={_mask_scalar(point.nlc)} "
                f"client_code={_mask_scalar(point.client_code)}"
            )
    finally:
        await client.close()


async def _cmd_probe(label: str | None, raw: bool) -> None:
    account = _pick(label)
    client = _client(account)
    try:
        result = await client.async_probe_all()
        with open(RAW_FILE, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False, default=str)
        print(f"raw payloads written to {RAW_FILE} (git-ignored)\n")
        for key, value in result.items():
            # Section keys embed the NLC / client code (e.g. "contract:700...").
            # Mask the identifier so it never reaches the terminal transcript.
            label = key
            if ":" in key:
                prefix, ident = key.split(":", 1)
                label = f"{prefix}:{_mask_scalar(ident)}"
            print(f"\n===== {label} =====")
            if value is None:
                print("  (null / 404)")
                continue
            print(shape(value))
    finally:
        await client.close()


def _cmd_keys(path: str) -> None:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    for key, value in data.items():
        print(f"\n===== {key} =====")
        print(shape(value))


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

    args = [a for a in sys.argv[1:] if a != "--raw"]
    raw = "--raw" in sys.argv
    if not args:
        print(__doc__)
        return

    cmd = args[0]
    label = args[1] if len(args) > 1 else None

    if cmd == "login":
        asyncio.run(_cmd_login(label))
    elif cmd == "hierarchy":
        asyncio.run(_cmd_hierarchy(label, raw))
    elif cmd == "probe":
        asyncio.run(_cmd_probe(label, raw))
    elif cmd == "keys":
        if not label:
            raise SystemExit("Usage: probe_electrica.py keys <file>")
        _cmd_keys(label)
    else:
        raise SystemExit(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()

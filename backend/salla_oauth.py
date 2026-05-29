"""
Salla OAuth 2.0 helper — one-time setup to get an access token.
Run once, save the token in .env, and you're done.
"""

import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://accounts.salla.sa/oauth2/auth"
TOKEN_URL = "https://accounts.salla.sa/oauth2/token"
ENV_FILE   = Path(__file__).parent / ".env"
TOKEN_FILE = Path(__file__).parent / "tokens.json"   # survives restarts within same deploy


def _load_tokens_from_file():
    """Load tokens from tokens.json into os.environ (called at startup)."""
    try:
        if TOKEN_FILE.exists():
            data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
            # Only apply if not already set via Railway env vars
            if not os.environ.get("SALLA_ACCESS_TOKEN") and data.get("access_token"):
                os.environ["SALLA_ACCESS_TOKEN"] = data["access_token"]
                print("[salla_oauth] Loaded access token from tokens.json")
            if not os.environ.get("SALLA_REFRESH_TOKEN") and data.get("refresh_token"):
                os.environ["SALLA_REFRESH_TOKEN"] = data["refresh_token"]
    except Exception as e:
        print(f"[salla_oauth] Could not load tokens.json: {e}")


# Run immediately on import so tokens are available before anything else
_load_tokens_from_file()


def get_auth_url(redirect_uri: str) -> str:
    from urllib.parse import urlencode
    params = {
        "client_id": os.environ["SALLA_CLIENT_ID"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "offline_access",
    }
    return AUTH_URL + "?" + urlencode(params)


async def exchange_code(code: str, redirect_uri: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": os.environ["SALLA_CLIENT_ID"],
                "client_secret": os.environ["SALLA_CLIENT_SECRET"],
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )
        r.raise_for_status()
        return r.json()


async def refresh_access_token() -> str:
    refresh_token = os.getenv("SALLA_REFRESH_TOKEN", "")
    if not refresh_token:
        raise RuntimeError("No refresh token stored. Please re-authorize.")

    async with httpx.AsyncClient() as client:
        r = await client.post(
            TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "client_id": os.environ["SALLA_CLIENT_ID"],
                "client_secret": os.environ["SALLA_CLIENT_SECRET"],
                "refresh_token": refresh_token,
            },
        )
        r.raise_for_status()
        data = r.json()

    new_token = data.get("access_token", "")
    new_refresh = data.get("refresh_token", refresh_token)

    # Use save_tokens so Railway in-memory env + .env file are both updated
    save_tokens(new_token, new_refresh)
    return new_token


def save_tokens(access_token: str, refresh_token: str):
    """Persist tokens to in-memory env, tokens.json, and .env (if present)."""
    # 1. Update in-memory env immediately
    os.environ["SALLA_ACCESS_TOKEN"] = access_token
    os.environ["SALLA_REFRESH_TOKEN"] = refresh_token

    # 2. Save to tokens.json — survives server restarts within the same deploy
    try:
        TOKEN_FILE.write_text(
            json.dumps({"access_token": access_token, "refresh_token": refresh_token},
                       ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"[salla_oauth] Tokens saved to tokens.json (token: {access_token[:8]}…)")
    except Exception as e:
        print(f"[salla_oauth] Warning: could not write tokens.json: {e}")

    # 3. Also update .env if it exists locally (dev environment)
    try:
        if ENV_FILE.exists():
            import re
            content = ENV_FILE.read_text(encoding="utf-8")
            content = re.sub(r"^SALLA_ACCESS_TOKEN=.*$", f"SALLA_ACCESS_TOKEN={access_token}", content, flags=re.MULTILINE)
            content = re.sub(r"^SALLA_REFRESH_TOKEN=.*$", f"SALLA_REFRESH_TOKEN={refresh_token}", content, flags=re.MULTILINE)
            ENV_FILE.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"[salla_oauth] Warning: could not write .env: {e}")

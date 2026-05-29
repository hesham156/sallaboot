"""
Salla OAuth 2.0 helper — one-time setup to get an access token.
Run once, save the token in .env, and you're done.
"""

import os
import json
import httpx
from pathlib import Path
from dotenv import load_dotenv, set_key

load_dotenv()

AUTH_URL = "https://accounts.salla.sa/oauth2/auth"
TOKEN_URL = "https://accounts.salla.sa/oauth2/token"
ENV_FILE = Path(__file__).parent / ".env"


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
    # Update in-memory env first
    os.environ["SALLA_ACCESS_TOKEN"] = access_token
    os.environ["SALLA_REFRESH_TOKEN"] = refresh_token

    # Read .env file and replace token lines directly (more reliable than set_key)
    try:
        env_path = ENV_FILE
        if env_path.exists():
            content = env_path.read_text(encoding="utf-8")
            import re
            content = re.sub(r"^SALLA_ACCESS_TOKEN=.*$", f"SALLA_ACCESS_TOKEN={access_token}", content, flags=re.MULTILINE)
            content = re.sub(r"^SALLA_REFRESH_TOKEN=.*$", f"SALLA_REFRESH_TOKEN={refresh_token}", content, flags=re.MULTILINE)
            env_path.write_text(content, encoding="utf-8")
    except Exception as e:
        print(f"Warning: could not write tokens to .env: {e}")

"""Resolve Etsy OAuth credentials, refreshing short-lived access tokens when needed."""

from __future__ import annotations

from time import time
from typing import Any

import httpx
from sqlalchemy import text

from merch.config import Settings
from merch.database import session_scope
from merch.services.credentials import CredentialCipher, CredentialStore


async def etsy_access_token(
    settings: Settings, client: httpx.AsyncClient | None = None
) -> str:
    configured_access = settings.etsy_access_token.get_secret_value()
    configured_refresh = settings.etsy_refresh_token.get_secret_value()
    encryption_key = settings.credential_encryption_key.get_secret_value()
    if not encryption_key:
        if configured_refresh:
            raise RuntimeError("MERCH_CREDENTIAL_ENCRYPTION_KEY is required for Etsy token refresh")
        return configured_access

    with session_scope() as session:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            # The worker and analytics can start together; rotate a token only once.
            session.execute(text("SELECT pg_advisory_xact_lock(1163154265)"))
        store = CredentialStore(session, CredentialCipher(encryption_key))
        refresh = store.get("etsy_refresh_token") or configured_refresh
        access = store.get("etsy_access_token") or configured_access
        expires_at = store.get("etsy_access_token_expires_at")
        if not refresh:
            return access
        if access and expires_at and float(expires_at) > time() + 300:
            return access
        keystring = settings.etsy_api_key.get_secret_value()
        if not keystring:
            raise RuntimeError("MERCH_ETSY_API_KEY is required for Etsy token refresh")
        payload = {
            "grant_type": "refresh_token",
            "client_id": keystring,
            "refresh_token": refresh,
        }
        if client is None:
            async with httpx.AsyncClient(timeout=30) as owned_client:
                response = await owned_client.post(
                    "https://api.etsy.com/v3/public/oauth/token", data=payload
                )
        else:
            response = await client.post(
                "https://api.etsy.com/v3/public/oauth/token", data=payload
            )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        new_access = str(data.get("access_token") or "")
        new_refresh = str(data.get("refresh_token") or "")
        expires_in = int(data.get("expires_in") or 0)
        if not new_access or not new_refresh or expires_in <= 0:
            raise RuntimeError("Etsy token refresh returned incomplete credentials")
        store.set("etsy_access_token", new_access)
        store.set("etsy_refresh_token", new_refresh)
        store.set("etsy_access_token_expires_at", str(int(time() + expires_in)))
        return new_access

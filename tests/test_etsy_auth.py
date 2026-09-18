from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest
from sqlalchemy import select

from merch.config import get_settings
from merch.database import get_engine, session_scope
from merch.models import Base, ConnectorCredentialRecord
from merch.services.credentials import CredentialCipher, CredentialStore
from merch.services.etsy_auth import etsy_access_token


@pytest.mark.asyncio
async def test_etsy_refresh_rotates_and_caches_credentials(
    isolated_app: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MERCH_CREDENTIAL_ENCRYPTION_KEY", "test-encryption-key")
    monkeypatch.setenv("MERCH_ETSY_API_KEY", "test-key")
    monkeypatch.setenv("MERCH_ETSY_REFRESH_TOKEN", "old-refresh")
    monkeypatch.setenv("MERCH_ETSY_ACCESS_TOKEN", "")
    get_settings.cache_clear()
    settings = get_settings()
    Base.metadata.create_all(get_engine())
    requests: list[dict[str, list[str]]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://api.etsy.com/v3/public/oauth/token"
        requests.append(parse_qs(request.content.decode()))
        return httpx.Response(
            200,
            json={
                "access_token": "123.new-access",
                "refresh_token": "123.new-refresh",
                "expires_in": 3600,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await etsy_access_token(settings, client) == "123.new-access"
        assert await etsy_access_token(settings, client) == "123.new-access"

    assert requests == [
        {
            "grant_type": ["refresh_token"],
            "client_id": ["test-key"],
            "refresh_token": ["old-refresh"],
        }
    ]
    with session_scope() as session:
        store = CredentialStore(session, CredentialCipher("test-encryption-key"))
        assert store.get("etsy_refresh_token") == "123.new-refresh"
        assert store.get("etsy_access_token") == "123.new-access"
        assert session.scalar(select(ConnectorCredentialRecord).where(ConnectorCredentialRecord.name == "etsy_access_token_expires_at")) is not None

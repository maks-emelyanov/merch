from __future__ import annotations

import hmac
import secrets
import time
from collections import defaultdict, deque
from typing import Any, cast

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request, status

from merch.config import Settings


class LoginThrottle:
    def __init__(self, limit: int, window_seconds: int = 900):
        self.limit = limit
        self.window_seconds = window_seconds
        self._attempts: dict[str, deque[float]] = defaultdict(deque)

    def check(self, identity: str) -> None:
        now = time.monotonic()
        attempts = self._attempts[identity]
        while attempts and attempts[0] < now - self.window_seconds:
            attempts.popleft()
        if len(attempts) >= self.limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many login attempts")

    def failure(self, identity: str) -> None:
        self._attempts[identity].append(time.monotonic())

    def success(self, identity: str) -> None:
        self._attempts.pop(identity, None)


def password_matches(password: str, settings: Settings) -> bool:
    password_hash = settings.admin_password_hash.get_secret_value()
    if password_hash:
        try:
            return cast(bool, PasswordHasher().verify(password_hash, password))
        except VerifyMismatchError, InvalidHashError:
            return False
    if settings.app_env == "production":
        return False
    return hmac.compare_digest(password, settings.local_admin_password.get_secret_value())


def csrf_token(request: Request) -> str:
    value = request.session.get("csrf")
    if not isinstance(value, str):
        value = secrets.token_urlsafe(32)
        request.session["csrf"] = value
    return value


async def require_csrf(request: Request) -> None:
    expected = request.session.get("csrf")
    supplied = request.headers.get("x-csrf-token")
    if supplied is None and request.headers.get("content-type", "").startswith(
        "application/x-www-form-urlencoded"
    ):
        supplied = str((await request.form()).get("csrf_token", ""))
    if (
        not isinstance(expected, str)
        or not isinstance(supplied, str)
        or not hmac.compare_digest(expected, supplied)
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")


def require_admin(request: Request) -> str:
    actor = request.session.get("actor")
    if actor != "admin":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    return "admin"


def client_identity(request: Request, settings: Settings) -> str:
    peer = request.client.host if request.client else "unknown"
    trusted = {item.strip() for item in settings.trusted_proxy_ips.split(",") if item.strip()}
    if peer in trusted:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",", 1)[0].strip()
    return peer


def safe_json(value: Any) -> Any:
    if isinstance(value, dict):
        forbidden = ("name", "email", "address", "phone")
        return {
            key: safe_json(item)
            for key, item in value.items()
            if not any(term in key.lower() for term in forbidden)
        }
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    return value

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.orm import Session

from merch.models import ConnectorCredentialRecord


class CredentialCipher:
    def __init__(self, key: str):
        if not key:
            self._fernet = None
        else:
            try:
                self._fernet = Fernet(key.encode())
            except ValueError:
                derived = base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest())
                self._fernet = Fernet(derived)

    def encrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("credential encryption key is not configured")
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if self._fernet is None:
            raise RuntimeError("credential encryption key is not configured")
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("encrypted credential could not be decrypted") from exc


def redact(value: str, secrets: list[str]) -> str:
    output = value
    for secret in secrets:
        if secret:
            output = output.replace(secret, "[REDACTED]")
    return output


class CredentialStore:
    def __init__(self, session: Session, cipher: CredentialCipher):
        self.session = session
        self.cipher = cipher

    def set(self, name: str, value: str) -> None:
        record = self.session.get(ConnectorCredentialRecord, name)
        if record is None:
            record = ConnectorCredentialRecord(name=name, encrypted_value="")
            self.session.add(record)
        record.encrypted_value = self.cipher.encrypt(value)

    def get(self, name: str) -> str | None:
        record = self.session.get(ConnectorCredentialRecord, name)
        if record is None:
            return None
        return self.cipher.decrypt(record.encrypted_value)

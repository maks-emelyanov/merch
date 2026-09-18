from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, cast

import boto3  # type: ignore[import-untyped]

from merch.config import Settings


class ArtifactStorage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client: Any | None = None
        if settings.storage_backend == "s3":
            self._client = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                region_name=settings.s3_region,
                aws_access_key_id=settings.s3_access_key.get_secret_value(),
                aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
            )

    def ensure_bucket(self) -> None:
        if self._client is None:
            self.settings.local_storage_path.mkdir(parents=True, exist_ok=True)
            return
        try:
            self._client.head_bucket(Bucket=self.settings.s3_bucket)
        except Exception:
            self._client.create_bucket(Bucket=self.settings.s3_bucket)

    def put(
        self, data: bytes, suffix: str = "png", content_type: str = "image/png"
    ) -> tuple[str, str]:
        digest = hashlib.sha256(data).hexdigest()
        key = f"artifacts/{digest[:2]}/{digest}.{suffix}"
        if self._client is None:
            path = self.settings.local_storage_path / key
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(data)
        else:
            self._client.put_object(
                Bucket=self.settings.s3_bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        return key, digest

    def get(self, key: str) -> bytes:
        if ".." in Path(key).parts or not key.startswith("artifacts/"):
            raise ValueError("invalid artifact key")
        if self._client is None:
            return (self.settings.local_storage_path / key).read_bytes()
        response = self._client.get_object(Bucket=self.settings.s3_bucket, Key=key)
        return cast(bytes, response["Body"].read())

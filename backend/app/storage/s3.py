"""S3-compatible storage (Cloudflare R2 / AWS S3 / MinIO etc).

Phase B SaaS backend. Boto3-based to maximise compatibility; the same
class talks to Cloudflare R2 by setting ``endpoint_url`` to the R2
gateway. We pick configuration from env:

    AWS_REGION                  defaults to "auto" (R2-friendly)
    AWS_ACCESS_KEY_ID
    AWS_SECRET_ACCESS_KEY
    STORAGE_BUCKET              required
    STORAGE_ENDPOINT_URL        e.g. https://<account>.r2.cloudflarestorage.com
                                or leave blank for AWS S3
    STORAGE_PUBLIC_BASE         optional CDN/public domain in front of the bucket

If boto3 isn't installed we raise on first use rather than at import
time, so a Phase A install doesn't need boto3.
"""

from __future__ import annotations

import os
from pathlib import Path


class S3CompatibleStorage:
    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "auto",
        public_base: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        if not bucket:
            raise ValueError("STORAGE_BUCKET is required for S3-compatible storage")
        self.bucket = bucket
        self.endpoint_url = endpoint_url or None
        self.region = region
        self.public_base = public_base.rstrip("/") if public_base else None
        self._access_key = access_key
        self._secret_key = secret_key
        self._client = None

    @classmethod
    def from_env(cls, *, default_endpoint_kind: str = "r2") -> "S3CompatibleStorage":
        endpoint = os.environ.get("STORAGE_ENDPOINT_URL") or None
        if endpoint is None and default_endpoint_kind == "r2":
            # If the user picked R2 but didn't set an endpoint, use the
            # canonical gateway when ACCOUNT_ID is supplied.
            acct = os.environ.get("R2_ACCOUNT_ID")
            if acct:
                endpoint = f"https://{acct}.r2.cloudflarestorage.com"
        return cls(
            bucket=os.environ.get("STORAGE_BUCKET", ""),
            endpoint_url=endpoint,
            region=os.environ.get("AWS_REGION", "auto"),
            public_base=os.environ.get("STORAGE_PUBLIC_BASE"),
            access_key=os.environ.get("AWS_ACCESS_KEY_ID"),
            secret_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        )

    def _get_client(self):
        if self._client is not None:
            return self._client
        try:
            import boto3
            from botocore.client import Config
        except ImportError as e:
            raise RuntimeError(
                "boto3 not installed. Run: uv pip install boto3"
            ) from e
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint_url,
            region_name=self.region,
            aws_access_key_id=self._access_key,
            aws_secret_access_key=self._secret_key,
            config=Config(signature_version="s3v4"),
        )
        return self._client

    def put(self, key: str, data: bytes, content_type: str | None = None) -> str:
        c = self._get_client()
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        c.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return self.get_url(key)

    def put_file(self, key: str, src_path, content_type: str | None = None) -> str:
        c = self._get_client()
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        c.upload_file(str(Path(src_path)), self.bucket, key, ExtraArgs=extra or None)
        return self.get_url(key)

    def get_url(self, key: str, *, signed: bool = False, ttl_sec: int = 3600) -> str:
        if not signed and self.public_base:
            return f"{self.public_base}/{key}"
        c = self._get_client()
        return c.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_sec,
        )

    def delete(self, key: str) -> bool:
        try:
            self._get_client().delete_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def exists(self, key: str) -> bool:
        try:
            self._get_client().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

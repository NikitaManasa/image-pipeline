import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    table_name: str
    uploads_bucket: str
    processed_bucket: str
    max_upload_bytes: int = 10 * 1024 * 1024
    url_ttl_seconds: int = 900

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            table_name=os.environ["JOBS_TABLE"],
            uploads_bucket=os.environ["UPLOADS_BUCKET"],
            processed_bucket=os.environ["PROCESSED_BUCKET"],
            max_upload_bytes=int(os.getenv("MAX_UPLOAD_BYTES", cls.max_upload_bytes)),
            url_ttl_seconds=int(os.getenv("URL_TTL_SECONDS", cls.url_ttl_seconds)),
        )

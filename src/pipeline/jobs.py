"""Job records in DynamoDB. Status moves PENDING_UPLOAD -> PROCESSING -> COMPLETED | FAILED."""

import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from botocore.exceptions import ClientError

RETENTION_SECONDS = 30 * 24 * 3600  # DynamoDB TTL deletes old jobs for free


class JobStatus:
    PENDING_UPLOAD = "PENDING_UPLOAD"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _plain(value: Any) -> Any:
    """DynamoDB returns numbers as Decimal; convert for JSON."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    return value


class JobStore:
    def __init__(self, table):
        self._table = table

    def create(self, job_id: str, filename: str, content_type: str, upload_key: str) -> dict:
        now = _now()
        item = {
            "job_id": job_id,
            "status": JobStatus.PENDING_UPLOAD,
            "filename": filename,
            "content_type": content_type,
            "upload_key": upload_key,
            "created_at": now,
            "updated_at": now,
            "expires_at": int(time.time()) + RETENTION_SECONDS,
        }
        self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(job_id)")
        return item

    def get(self, job_id: str) -> dict | None:
        item = self._table.get_item(Key={"job_id": job_id}, ConsistentRead=True).get("Item")
        return _plain(item) if item else None

    def start_processing(self, job_id: str) -> bool:
        """Claims the job. False if it is unknown or already finished (duplicate S3/SQS delivery).

        PROCESSING is allowed so that a retry after a crash mid-processing can pick the job up again.
        """
        try:
            self._table.update_item(
                Key={"job_id": job_id},
                UpdateExpression="SET #s = :processing, updated_at = :now",
                ConditionExpression="attribute_exists(job_id) AND #s IN (:pending, :processing)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={
                    ":processing": JobStatus.PROCESSING,
                    ":pending": JobStatus.PENDING_UPLOAD,
                    ":now": _now(),
                },
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def complete(self, job_id: str, metadata: dict, outputs: dict[str, str]) -> None:
        self._table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :done, metadata = :m, outputs = :o, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":done": JobStatus.COMPLETED, ":m": metadata, ":o": outputs, ":now": _now()},
        )

    def fail(self, job_id: str, reason: str) -> None:
        self._table.update_item(
            Key={"job_id": job_id},
            UpdateExpression="SET #s = :failed, failure_reason = :r, updated_at = :now",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": JobStatus.FAILED, ":r": reason[:500], ":now": _now()},
        )

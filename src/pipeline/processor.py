"""SQS-triggered worker. Each SQS message carries an S3 "ObjectCreated" notification.

Error handling:
  - bad image (permanent)  -> job marked FAILED, message deleted; retrying would never help
  - anything else (transient: throttling, network) -> reported as a batch item failure, so only
    that message is retried; after 3 attempts SQS moves it to the dead-letter queue (and an alarm fires)
"""

import json
import uuid
from urllib.parse import unquote_plus

from pipeline.aws import deps
from pipeline.images import InvalidImage, process_image
from pipeline.jobs import JobStatus
from pipeline.log import get_logger

log = get_logger(__name__)


def handler(event: dict, context) -> dict:
    failures = []
    for record in event.get("Records", []):
        try:
            process_message(record["body"])
        except Exception:
            log.exception("message failed, will be retried", extra={"key": record.get("messageId")})
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def process_message(body: str) -> None:
    notification = json.loads(body)
    if notification.get("Event") == "s3:TestEvent":  # S3 sends this once when notifications are set up
        return
    for s3_record in notification.get("Records", []):
        bucket = s3_record["s3"]["bucket"]["name"]
        key = unquote_plus(s3_record["s3"]["object"]["key"])  # S3 URL-encodes keys in events
        process_object(bucket, key)


def process_object(bucket: str, key: str) -> None:
    config, s3, store = deps()

    job_id = _job_id_from_key(key)
    if job_id is None:
        log.warning("ignoring object outside the uploads/<job_id>/ layout", extra={"key": key})
        return
    if not store.start_processing(job_id):
        log.info("job unknown or already finished, skipping", extra={"job_id": job_id})
        return

    obj = s3.get_object(Bucket=bucket, Key=key)
    if obj["ContentLength"] > config.max_upload_bytes:  # defence in depth; the presigned POST also limits size
        store.fail(job_id, "file too large")
        return
    data = obj["Body"].read()

    try:
        image = process_image(data)
    except InvalidImage as exc:
        store.fail(job_id, str(exc))
        log.info("job failed", extra={"job_id": job_id, "status": JobStatus.FAILED, "reason": str(exc)})
        return

    outputs = {}
    for size, blob in image.renditions.items():
        out_key = f"processed/{job_id}/{size}.webp"
        s3.put_object(Bucket=config.processed_bucket, Key=out_key, Body=blob, ContentType="image/webp")
        outputs[str(size)] = out_key

    metadata = {"width": image.width, "height": image.height, "format": image.format, "size_bytes": len(data)}
    store.complete(job_id, metadata, outputs)
    log.info("job completed", extra={"job_id": job_id, "status": JobStatus.COMPLETED})


def _job_id_from_key(key: str) -> str | None:
    parts = key.split("/")
    if len(parts) != 3 or parts[0] != "uploads":
        return None
    try:
        return str(uuid.UUID(parts[1]))
    except ValueError:
        return None

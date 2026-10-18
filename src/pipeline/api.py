"""HTTP API (API Gateway HTTP API, payload v2).

POST /uploads        -> creates a job, returns a presigned S3 POST the client uploads to directly
GET  /jobs/{job_id}  -> job status, plus short-lived download links once processing is done

Files never pass through Lambda: the client uploads straight to S3, which avoids API Gateway's
10 MB payload limit and means we don't pay for Lambda time spent moving bytes.
"""

import base64
import json
import re
import uuid

from pipeline.aws import deps
from pipeline.jobs import JobStatus
from pipeline.log import get_logger

log = get_logger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._-]")


class BadRequest(Exception):
    pass


def handler(event: dict, context) -> dict:
    route = event.get("routeKey")
    try:
        if route == "POST /uploads":
            return create_upload(_json_body(event))
        if route == "GET /jobs/{job_id}":
            return get_job((event.get("pathParameters") or {}).get("job_id", ""))
        return _response(404, {"error": "route not found"})
    except BadRequest as exc:
        return _response(400, {"error": str(exc)})
    except Exception:
        log.exception("unhandled error")
        return _response(500, {"error": "internal error", "request_id": getattr(context, "aws_request_id", None)})


def create_upload(body: dict) -> dict:
    config, s3, store = deps()

    filename = body.get("filename")
    content_type = body.get("content_type")
    if not isinstance(filename, str) or not 1 <= len(filename) <= 200:
        raise BadRequest("filename must be a string of 1-200 characters")
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise BadRequest(f"content_type must be one of {sorted(ALLOWED_CONTENT_TYPES)}")

    job_id = str(uuid.uuid4())
    key = f"uploads/{job_id}/{safe_filename(filename)}"
    # Presigned POST (not PUT) so S3 itself enforces the size limit and content type.
    upload = s3.generate_presigned_post(
        Bucket=config.uploads_bucket,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, config.max_upload_bytes]],
        ExpiresIn=config.url_ttl_seconds,
    )
    store.create(job_id, filename, content_type, key)
    log.info("upload created", extra={"job_id": job_id, "key": key})

    return _response(
        201,
        {
            "job_id": job_id,
            "status": JobStatus.PENDING_UPLOAD,
            "upload": upload,
            "expires_in": config.url_ttl_seconds,
            "max_bytes": config.max_upload_bytes,
        },
    )


def get_job(job_id: str) -> dict:
    config, s3, store = deps()
    if not _is_uuid(job_id):
        raise BadRequest("job_id must be a UUID")

    job = store.get(job_id)
    if job is None:
        return _response(404, {"error": "job not found"})

    result = {
        k: job.get(k)
        for k in ("job_id", "status", "filename", "created_at", "updated_at", "failure_reason", "metadata")
        if job.get(k) is not None
    }
    if job["status"] == JobStatus.COMPLETED:
        result["downloads"] = {
            size: s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": config.processed_bucket, "Key": key},
                ExpiresIn=config.url_ttl_seconds,
            )
            for size, key in job.get("outputs", {}).items()
        }
    return _response(200, result)


def safe_filename(filename: str) -> str:
    """Strips directories and odd characters so the S3 key is predictable and can't escape its prefix."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = _UNSAFE_CHARS.sub("_", name).strip("._")
    return name[:100] or "upload"


def _is_uuid(value: str) -> bool:
    try:
        return str(uuid.UUID(value)) == value
    except ValueError:
        return False


def _json_body(event: dict) -> dict:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequest("body must be JSON") from exc
    if not isinstance(body, dict):
        raise BadRequest("body must be a JSON object")
    return body


def _response(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}

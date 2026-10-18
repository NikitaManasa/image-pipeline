"""The whole pipeline against fake AWS: API creates job -> object lands in S3 -> processor runs."""

import json
import uuid

import pytest

from conftest import PROCESSED, UPLOADS, http_event, make_image, s3_event
from pipeline import api, processor
from pipeline.aws import deps
from pipeline.jobs import JobStatus


def new_job(filename="photo.jpg", content_type="image/jpeg") -> tuple[str, str]:
    resp = api.handler(http_event("POST /uploads", {"filename": filename, "content_type": content_type}), None)
    body = json.loads(resp["body"])
    return body["job_id"], body["upload"]["fields"]["key"]


def upload_and_process(s3, data: bytes, **kwargs) -> tuple[str, dict]:
    job_id, key = new_job(**kwargs)
    s3.put_object(Bucket=UPLOADS, Key=key, Body=data)  # what the client's presigned POST does
    result = processor.handler({"Records": [s3_event(key)]}, None)
    return job_id, result


def job(job_id):
    return deps()[2].get(job_id)


def test_valid_image_completes_with_renditions(aws):
    job_id, result = upload_and_process(aws, make_image("JPEG", size=(2000, 1000)))

    assert result == {"batchItemFailures": []}
    record = job(job_id)
    assert record["status"] == JobStatus.COMPLETED
    assert record["metadata"]["width"] == 2000
    assert record["metadata"]["format"] == "JPEG"
    keys = {o["Key"] for o in aws.list_objects_v2(Bucket=PROCESSED)["Contents"]}
    assert keys == {f"processed/{job_id}/256.webp", f"processed/{job_id}/1024.webp"}
    assert aws.head_object(Bucket=PROCESSED, Key=f"processed/{job_id}/256.webp")["ContentType"] == "image/webp"


def test_invalid_image_fails_job_without_retrying(aws):
    job_id, result = upload_and_process(aws, b"<script>alert(1)</script>")

    assert result == {"batchItemFailures": []}  # permanent error: don't send it back to the queue
    record = job(job_id)
    assert record["status"] == JobStatus.FAILED
    assert "not a valid image" in record["failure_reason"]


def test_oversized_object_is_rejected(aws):
    job_id, _ = upload_and_process(aws, b"x" * (2 * 1024 * 1024 + 1))

    assert job(job_id)["failure_reason"] == "file too large"


def test_duplicate_delivery_is_processed_once(aws):
    job_id, key = new_job()
    aws.put_object(Bucket=UPLOADS, Key=key, Body=make_image())
    processor.handler({"Records": [s3_event(key)]}, None)
    first_update = job(job_id)["updated_at"]

    result = processor.handler({"Records": [s3_event(key)]}, None)

    assert result == {"batchItemFailures": []}
    assert job(job_id)["updated_at"] == first_update


def test_object_for_unknown_job_is_ignored(aws):
    key = f"uploads/{uuid.uuid4()}/sneaky.jpg"
    aws.put_object(Bucket=UPLOADS, Key=key, Body=make_image())

    assert processor.handler({"Records": [s3_event(key)]}, None) == {"batchItemFailures": []}


@pytest.mark.parametrize("key", ["somewhere/else.jpg", "uploads/not-a-uuid/x.jpg", "uploads/a/b/c.jpg"])
def test_unexpected_keys_are_ignored(key):
    assert processor.handler({"Records": [s3_event(key)]}, None) == {"batchItemFailures": []}


def test_s3_test_event_is_ignored():
    record = {"messageId": "m", "body": json.dumps({"Event": "s3:TestEvent", "Bucket": UPLOADS})}

    assert processor.handler({"Records": [record]}, None) == {"batchItemFailures": []}


def test_transient_failure_is_retried_then_succeeds(aws):
    job_id, key = new_job()
    aws.put_object(Bucket=UPLOADS, Key=key, Body=make_image())
    aws.delete_bucket(Bucket=PROCESSED)  # simulate S3 being unavailable for writes

    result = processor.handler({"Records": [s3_event(key, message_id="m-42")]}, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "m-42"}]}
    assert job(job_id)["status"] == JobStatus.PROCESSING

    aws.create_bucket(Bucket=PROCESSED)  # SQS redelivers after the visibility timeout
    assert processor.handler({"Records": [s3_event(key, message_id="m-42")]}, None) == {"batchItemFailures": []}
    assert job(job_id)["status"] == JobStatus.COMPLETED


def test_one_bad_message_does_not_fail_the_batch(aws):
    good_id, good_key = new_job()
    aws.put_object(Bucket=UPLOADS, Key=good_key, Body=make_image())
    broken = {"messageId": "broken", "body": "{not json"}

    result = processor.handler({"Records": [broken, s3_event(good_key, message_id="good")]}, None)

    assert result == {"batchItemFailures": [{"itemIdentifier": "broken"}]}
    assert job(good_id)["status"] == JobStatus.COMPLETED


def test_url_encoded_keys_from_s3_events_are_decoded(aws):
    # Real S3 events URL-encode the key ("my photo.jpg" arrives as "my+photo.jpg").
    job_id = str(uuid.uuid4())
    deps()[2].create(job_id, "my photo.jpg", "image/jpeg", f"uploads/{job_id}/my photo.jpg")
    aws.put_object(Bucket=UPLOADS, Key=f"uploads/{job_id}/my photo.jpg", Body=make_image())

    processor.handler({"Records": [s3_event(f"uploads/{job_id}/my+photo.jpg")]}, None)

    assert job(job_id)["status"] == JobStatus.COMPLETED

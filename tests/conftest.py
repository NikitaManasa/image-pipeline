import json
from io import BytesIO

import boto3
import pytest
from moto import mock_aws
from PIL import Image

from pipeline.aws import deps

REGION = "us-east-1"
TABLE = "jobs"
UPLOADS = "test-uploads"
PROCESSED = "test-processed"


@pytest.fixture(autouse=True)
def aws(monkeypatch):
    """Fake AWS account (moto) with the same resources Terraform creates."""
    for name, value in {
        "AWS_ACCESS_KEY_ID": "testing",
        "AWS_SECRET_ACCESS_KEY": "testing",
        "AWS_SESSION_TOKEN": "testing",
        "AWS_DEFAULT_REGION": REGION,
        "JOBS_TABLE": TABLE,
        "UPLOADS_BUCKET": UPLOADS,
        "PROCESSED_BUCKET": PROCESSED,
        "MAX_UPLOAD_BYTES": str(2 * 1024 * 1024),
    }.items():
        monkeypatch.setenv(name, value)

    with mock_aws():
        deps.cache_clear()
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket=UPLOADS)
        s3.create_bucket(Bucket=PROCESSED)
        boto3.client("dynamodb", region_name=REGION).create_table(
            TableName=TABLE,
            KeySchema=[{"AttributeName": "job_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "job_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield s3
        deps.cache_clear()


_FILL = {"RGB": (200, 30, 30), "RGBA": (200, 30, 30, 128), "P": 1, "1": 0}


def make_image(fmt: str = "JPEG", size=(1600, 900), mode: str = "RGB", **save_kwargs) -> bytes:
    out = BytesIO()
    Image.new(mode, size, color=_FILL[mode]).save(out, format=fmt, **save_kwargs)
    return out.getvalue()


def s3_event(key: str, bucket: str = UPLOADS, message_id: str = "msg-1") -> dict:
    """An SQS record wrapping an S3 ObjectCreated notification, as Lambda receives it."""
    body = {
        "Records": [{"eventName": "ObjectCreated:Post", "s3": {"bucket": {"name": bucket}, "object": {"key": key}}}]
    }
    return {"messageId": message_id, "body": json.dumps(body)}


def http_event(route: str, body: dict | None = None, job_id: str | None = None) -> dict:
    return {
        "routeKey": route,
        "body": json.dumps(body) if body is not None else None,
        "pathParameters": {"job_id": job_id} if job_id is not None else None,
        "isBase64Encoded": False,
    }

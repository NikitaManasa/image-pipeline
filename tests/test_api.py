import base64
import json
import uuid

import pytest

from conftest import PROCESSED, UPLOADS, http_event
from pipeline import api
from pipeline.aws import deps
from pipeline.jobs import JobStatus


def call(route, body=None, job_id=None):
    resp = api.handler(http_event(route, body, job_id), context=None)
    return resp["statusCode"], json.loads(resp["body"])


def create_upload(filename="cat.jpg", content_type="image/jpeg"):
    return call("POST /uploads", {"filename": filename, "content_type": content_type})


def test_create_upload_returns_presigned_post_and_stores_job():
    status, body = create_upload()

    assert status == 201
    assert body["status"] == JobStatus.PENDING_UPLOAD
    fields = body["upload"]["fields"]
    assert fields["key"] == f"uploads/{body['job_id']}/cat.jpg"
    assert fields["Content-Type"] == "image/jpeg"
    assert UPLOADS in body["upload"]["url"]

    _, _, store = deps()
    assert store.get(body["job_id"])["status"] == JobStatus.PENDING_UPLOAD


def test_presigned_post_enforces_size_and_type():
    _, body = create_upload()

    policy = json.loads(base64.b64decode(body["upload"]["fields"]["policy"]))
    conditions = policy["conditions"]
    assert ["content-length-range", 1, 2 * 1024 * 1024] in conditions
    assert {"Content-Type": "image/jpeg"} in conditions


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../etc/passwd", "passwd"),
        ("C:\\Users\\me\\holiday photo.png", "holiday_photo.png"),
        ("..", "upload"),
        ("ünïcødé😀.jpg", "n_c_d__.jpg"),
    ],
)
def test_filenames_are_sanitised(filename, expected):
    assert api.safe_filename(filename) == expected


@pytest.mark.parametrize(
    "body",
    [
        {"filename": "a.gif", "content_type": "image/gif"},
        {"filename": "a.html", "content_type": "text/html"},
        {"filename": "", "content_type": "image/png"},
        {"filename": "x" * 201, "content_type": "image/png"},
        {"content_type": "image/png"},
    ],
)
def test_create_upload_validates_input(body):
    status, resp = call("POST /uploads", body)

    assert status == 400
    assert "error" in resp


def test_rejects_non_json_body():
    resp = api.handler({"routeKey": "POST /uploads", "body": "not json"}, None)

    assert resp["statusCode"] == 400


def test_get_unknown_job_is_404():
    assert call("GET /jobs/{job_id}", job_id=str(uuid.uuid4()))[0] == 404


def test_get_job_rejects_non_uuid():
    assert call("GET /jobs/{job_id}", job_id="../../admin")[0] == 400


def test_unknown_route_is_404():
    assert call("DELETE /jobs/{job_id}", job_id=str(uuid.uuid4()))[0] == 404


def test_pending_job_has_no_download_links():
    _, created = create_upload()

    status, job = call("GET /jobs/{job_id}", job_id=created["job_id"])

    assert status == 200
    assert job["status"] == JobStatus.PENDING_UPLOAD
    assert "downloads" not in job


def test_completed_job_returns_download_links():
    _, created = create_upload()
    _, _, store = deps()
    job_id = created["job_id"]
    store.start_processing(job_id)
    store.complete(job_id, {"width": 10, "height": 5}, {"256": f"processed/{job_id}/256.webp"})

    _, job = call("GET /jobs/{job_id}", job_id=job_id)

    assert job["status"] == JobStatus.COMPLETED
    assert job["metadata"] == {"width": 10, "height": 5}
    assert PROCESSED in job["downloads"]["256"]
    assert "X-Amz-Signature" in job["downloads"]["256"]


def test_unexpected_errors_return_500_without_details(monkeypatch):
    monkeypatch.setattr(api, "create_upload", lambda body: 1 / 0)

    status, body = create_upload()

    assert status == 500
    assert body["error"] == "internal error"
    assert "ZeroDivision" not in json.dumps(body)

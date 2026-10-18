"""Smoke test against a deployed stack: upload an image through the real API and wait for the result.

Usage:  python scripts/demo.py https://abc123.execute-api.us-east-1.amazonaws.com [path/to/image.jpg]
Without an image path it generates one (needs Pillow). Exits non-zero on failure, so CI uses it
to verify every deployment.
"""

import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path


def call(method: str, url: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def presigned_post(url: str, fields: dict, filename: str, content: bytes, content_type: str) -> int:
    """multipart/form-data upload straight to S3; the file field must come last."""
    boundary = uuid.uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields.items()
    ]
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + content
        + f"\r\n--{boundary}--\r\n".encode()
    )
    req = urllib.request.Request(
        url, data=b"".join(parts), method="POST", headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(errors="replace"))
        return exc.code


def sample_image() -> tuple[str, bytes, str]:
    from PIL import Image

    out = BytesIO()
    Image.new("RGB", (1920, 1080), (40, 120, 200)).save(out, format="JPEG")
    return "smoke-test.jpg", out.getvalue(), "image/jpeg"


def upload(api: str, filename: str, content: bytes, content_type: str) -> str:
    status, created = call("POST", f"{api}/uploads", {"filename": filename, "content_type": content_type})
    if status != 201:
        raise SystemExit(f"POST /uploads -> {status}: {created}")
    s3_status = presigned_post(created["upload"]["url"], created["upload"]["fields"], filename, content, content_type)
    if s3_status not in (200, 204):
        raise SystemExit(f"S3 upload -> {s3_status}")
    return created["job_id"]


def wait(api: str, job_id: str, timeout: float = 90) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, job = call("GET", f"{api}/jobs/{job_id}")
        if job.get("status") in ("COMPLETED", "FAILED"):
            return job
        time.sleep(2)
    raise SystemExit(f"job {job_id} not finished after {timeout}s")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    api = sys.argv[1].rstrip("/")
    if len(sys.argv) > 2:
        path = Path(sys.argv[2])
        content_type = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        filename, content, ctype = path.name, path.read_bytes(), content_type[path.suffix.lower()]
    else:
        filename, content, ctype = sample_image()

    job_id = upload(api, filename, content, ctype)
    print(f"uploaded {filename} -> job {job_id}")
    job = wait(api, job_id)
    print(json.dumps({k: v for k, v in job.items() if k != "downloads"}, indent=2))
    if job["status"] != "COMPLETED":
        raise SystemExit("FAILED: image was not processed")
    for size, link in job["downloads"].items():
        with urllib.request.urlopen(link, timeout=15) as resp:
            print(f"  {size}px rendition: {len(resp.read())} bytes ({resp.headers['Content-Type']})")

    # A fake "image" must be rejected by the pipeline, not crash it.
    bad_job = upload(api, "evil.jpg", b"<?php system($_GET['c']); ?>", "image/jpeg")
    bad = wait(api, bad_job)
    print(f"fake image -> {bad['status']}: {bad.get('failure_reason')}")
    if bad["status"] != "FAILED":
        raise SystemExit("FAILED: a non-image was accepted")
    print("\nSmoke test passed.")


if __name__ == "__main__":
    main()

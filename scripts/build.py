"""Packages the two Lambda functions into build/api.zip and build/processor.zip.

The processor needs Pillow compiled for Amazon Linux, so pip downloads the manylinux wheel
for Python 3.12 / x86_64 regardless of the OS this script runs on (works on Windows too).
Zips are deterministic (fixed timestamps, sorted entries): the same code gives the same hash,
so Terraform only redeploys a function when its code actually changed.

Usage:  python scripts/build.py
"""

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
PILLOW = "pillow==11.0.0"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def build(name: str, extra_packages: list[str]) -> Path:
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:  # outside the repo, so sync tools can't lock files mid-build
        return _build(name, extra_packages, Path(tmp))


def _build(name: str, extra_packages: list[str], staging: Path) -> Path:
    shutil.copytree(ROOT / "src" / "pipeline", staging / "pipeline", ignore=shutil.ignore_patterns("__pycache__"))

    if extra_packages:
        subprocess.run(
            [
                sys.executable, "-m", "pip", "install", "--quiet", "--target", str(staging),
                "--platform", "manylinux2014_x86_64", "--implementation", "cp", "--python-version", "3.12",
                "--only-binary=:all:", *extra_packages,
            ],
            check=True,
        )  # fmt: skip

    archive = BUILD / f"{name}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(p for p in staging.rglob("*") if p.is_file() and "__pycache__" not in p.parts):
            info = zipfile.ZipInfo(path.relative_to(staging).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    print(f"built {archive.relative_to(ROOT)} ({archive.stat().st_size / 1024:.0f} KB)")
    return archive


if __name__ == "__main__":
    build("api", [])
    build("processor", [PILLOW])

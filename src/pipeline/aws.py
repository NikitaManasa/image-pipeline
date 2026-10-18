"""AWS clients, created once per Lambda container and reused across invocations (faster warm starts)."""

import functools
from typing import Any

import boto3
from botocore.config import Config as BotoConfig

from pipeline.config import Config
from pipeline.jobs import JobStore


@functools.cache
def deps() -> tuple[Config, Any, JobStore]:
    config = Config.from_env()
    s3 = boto3.client("s3", config=BotoConfig(signature_version="s3v4", retries={"mode": "standard"}))
    table = boto3.resource("dynamodb").Table(config.table_name)
    return config, s3, JobStore(table)

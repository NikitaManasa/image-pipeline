"""JSON logs so CloudWatch Logs Insights can filter by job_id, e.g.
`fields @timestamp, msg | filter job_id = "..."`.
"""

import json
import logging

_EXTRA_FIELDS = ("job_id", "key", "status", "reason")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {"level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                entry[field] = getattr(record, field)
        request_id = getattr(record, "aws_request_id", None)  # set by the Lambda runtime
        if request_id:
            entry["request_id"] = request_id
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def get_logger(name: str) -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:  # running outside Lambda (tests, scripts)
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    root.setLevel(logging.INFO)
    return logging.getLogger(name)

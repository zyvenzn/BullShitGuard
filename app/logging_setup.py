"""Structured JSON logging with secret redaction."""
from __future__ import annotations

import json
import logging
import re
import sys
import time

_TOKEN_RE = re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b")
_STD = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}


def redact(text: str, secrets: list[str] | tuple[str, ...] = ()) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return _TOKEN_RE.sub("***", text)


class JsonFormatter(logging.Formatter):
    def __init__(self, secrets: list[str] | tuple[str, ...] = ()) -> None:
        super().__init__()
        self.secrets = list(secrets)

    def format(self, record: logging.LogRecord) -> str:
        data = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD and not k.startswith("_"):
                data[k] = v if isinstance(v, (int, float, bool, type(None), list, dict)) else str(v)
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return redact(json.dumps(data, ensure_ascii=False, default=str), self.secrets)


def setup_logging(level: str = "INFO", secrets: list[str] | tuple[str, ...] = ()) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(secrets))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # aiogram logs request URLs that contain the token on errors; keep it tame
    logging.getLogger("aiogram").setLevel(logging.WARNING if level.upper() != "DEBUG" else logging.DEBUG)

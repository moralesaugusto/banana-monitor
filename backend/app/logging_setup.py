import logging
import re
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any, cast

import structlog

_SECRET_KEY_PATTERN = re.compile(
    r"(password|passphrase|secret|token|private_key|api_key|credential)", re.IGNORECASE
)
_REDACTED = "***REDACTED***"


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            k: _REDACTED if _SECRET_KEY_PATTERN.search(str(k)) else _redact_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact_value(v) for v in value]
    return value


def redact_processor(
    logger: object, method_name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    for key in list(event_dict.keys()):
        if _SECRET_KEY_PATTERN.search(key):
            event_dict[key] = _REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def configure_logging(level: str = "INFO", json_output: bool = False) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    # httpx logs one INFO line per outbound request by default, which drowns
    # out our own logs given how many polls/probes run per minute.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        redact_processor,
    ]

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    structlog.configure(
        processors=[*shared_processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    root_handler = logging.getLogger().handlers[0]
    root_handler.setFormatter(formatter)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger(name))

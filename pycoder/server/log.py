"""
Structured logging for PyCoder.
Uses structlog for structured, context-rich logging.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Attempt structlog import, fall back to simple logging
try:
    import structlog
    import logging

    # 使用标准 logging.LoggerFactory 而非 PrintLoggerFactory
    # PrintLogger 缺少 disabled 属性，会导致 filter_by_level 崩溃
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        stream=sys.stdout,
    )

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _has_structlog = True
except ImportError:
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
    )
    _has_structlog = False


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger."""
    if _has_structlog:
        return structlog.get_logger(name or __name__)
    import logging
    return logging.getLogger(name or __name__)


# Convenience access
log = get_logger("pycoder")

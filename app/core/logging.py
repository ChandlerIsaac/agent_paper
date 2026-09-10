"""Centralized logging configuration."""

import logging
from logging.config import dictConfig
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs"


def setup_logging(level: str = "INFO") -> None:
    """Configure console output and bounded rotating file logs."""

    normalized = level.upper()
    if normalized not in logging.getLevelNamesMapping():
        raise ValueError(f"无效日志级别：{level}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                }
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": normalized,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": normalized,
                    "filename": str(LOG_DIR / "researchmate.log"),
                    "maxBytes": 10 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "handlers": ["console", "file"],
                "level": normalized,
            },
        }
    )

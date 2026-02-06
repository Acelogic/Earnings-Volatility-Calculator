"""Shared logging helpers."""

import logging


def add_console_logging(logger: logging.Logger, level=logging.INFO):
    """Add a console handler to a logger if one doesn't exist."""
    if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
        ch = logging.StreamHandler()
        ch.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        ch.setFormatter(formatter)
        logger.addHandler(ch)


def create_logger(name: str, log_file: str) -> logging.Logger:
    """Create a logger with file + console handlers."""
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        fh = logging.FileHandler(log_file)
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    add_console_logging(logger, level=logging.INFO)
    return logger

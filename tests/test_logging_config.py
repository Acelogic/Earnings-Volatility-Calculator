"""Tests for logging_config module."""

import logging

from earnings_calculator.logging_config import add_console_logging, create_logger


class TestAddConsoleLogging:
    def test_adds_stream_handler(self):
        logger = logging.getLogger("test_add_console")
        logger.handlers.clear()
        add_console_logging(logger)
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 1

    def test_does_not_duplicate(self):
        logger = logging.getLogger("test_no_dup")
        logger.handlers.clear()
        add_console_logging(logger)
        add_console_logging(logger)
        stream_handlers = [
            h for h in logger.handlers if isinstance(h, logging.StreamHandler)
        ]
        assert len(stream_handlers) == 1

    def test_respects_level(self):
        logger = logging.getLogger("test_level")
        logger.handlers.clear()
        add_console_logging(logger, level=logging.WARNING)
        sh = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)][0]
        assert sh.level == logging.WARNING


class TestCreateLogger:
    def test_creates_logger_with_handlers(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        logger = create_logger("test_create", log_file)
        assert logger.name == "test_create"
        assert logger.level == logging.DEBUG
        file_handlers = [
            h for h in logger.handlers if isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) >= 1

    def test_logger_writes_to_file(self, tmp_path):
        log_file = str(tmp_path / "write_test.log")
        logger = create_logger("test_write", log_file)
        logger.info("hello")
        with open(log_file) as f:
            content = f.read()
        assert "hello" in content

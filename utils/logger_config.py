"""
utils/logger_config.py
Centralised logging setup for the entire CloseAI process.

Call `configure_logging()` exactly ONCE at the top-level entry point
(RISHI.py __main__ block or orchestrator).  Every other module must
only call  logging.getLogger(__name__)  — never basicConfig().
"""
import logging
import sys


def configure_logging(level: int = logging.INFO) -> None:
    """
    Idempotent: safe to call multiple times, only configures once.
    Writes structured, timestamped output to stdout.
    """
    root = logging.getLogger()
    if root.handlers:
        return  # already configured — avoid duplicate handlers

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)

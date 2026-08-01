import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOGS_DIR = Path(__file__).with_name("logs")
LOG_PATH = LOGS_DIR / "viewshed_module.log"


def get_logger(name):
    logger = logging.getLogger("vieshed_module")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            LOGS_DIR.mkdir(exist_ok=True)
            handler = RotatingFileHandler(
                LOG_PATH,
                maxBytes=5_000_000,
                backupCount=3,
                encoding="utf-8",
            )
        except OSError:
            handler = logging.NullHandler()
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
            )
        )
        logger.addHandler(handler)
    return logging.getLogger(name)

import logging
import time

from sqlalchemy import text

from app.config import settings
from app.db import engine
from app.logging import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger("worker")

HEARTBEAT_SECONDS = 30


def main() -> None:
    logger.info("worker starting")
    while True:
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("worker heartbeat: db ok")
        except Exception:
            logger.exception("worker heartbeat: db unreachable")
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()

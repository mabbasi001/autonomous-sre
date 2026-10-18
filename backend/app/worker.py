import logging
import time

from app.config import settings
from app.db import SessionLocal
from app.detection.engine import absence_sweep, process_pending_events
from app.logging import setup_logging

setup_logging(settings.log_level)
logger = logging.getLogger("worker")

POLL_SECONDS = 2


def tick() -> int:
    with SessionLocal() as db:
        fired = process_pending_events(db)
        fired += absence_sweep(db)
    return fired


def main() -> None:
    logger.info("worker starting")
    while True:
        try:
            fired = tick()
            if fired:
                logger.info(f"fired {fired} alert(s)")
        except Exception:
            logger.exception("detection tick failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

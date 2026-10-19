import logging
import time

from app.config import settings
from app.db import SessionLocal
from app.detection.engine import absence_sweep, process_pending_events
from app.incidents.manager import process_new_alerts
from app.logging import setup_logging
from app.notifications.service import deliver_pending

setup_logging(settings.log_level)
logger = logging.getLogger("worker")

POLL_SECONDS = 2


def tick() -> tuple[int, int]:
    with SessionLocal() as db:
        fired = process_pending_events(db)
        fired += absence_sweep(db)
        opened = process_new_alerts(db)
        deliver_pending(db)
    return fired, opened


def main() -> None:
    logger.info("worker starting")
    while True:
        try:
            fired, opened = tick()
            if fired or opened:
                logger.info(f"fired {fired} alert(s), opened {opened} incident(s)")
        except Exception:
            logger.exception("detection tick failed")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()

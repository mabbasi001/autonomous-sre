import logging
import time

from app.approvals.service import expire_pending
from app.commands.service import expire_commands
from app.config import settings
from app.db import SessionLocal
from app.detection.engine import absence_sweep, process_pending_events
from app.incidents.manager import process_new_alerts
from app.investigation.service import investigate_open_incidents
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
        investigate_open_incidents(db)
        expire_pending(db)
        expire_commands(db)
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

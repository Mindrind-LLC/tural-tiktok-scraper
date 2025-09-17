#!/usr/bin/env python3
"""Simple runner that executes the Instagram seeding workflow every 8 hours."""

import logging
import signal
import sys
import time
from datetime import datetime, timedelta

from ig_seed_cookies import main as run_seed_workflow


LOG_FILE = "ig_cron.log"
RUN_INTERVAL = timedelta(hours=8)


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler(sys.stdout),
        ],
    )


def _sleep_until(next_run: datetime) -> None:
    while True:
        now = datetime.now()
        remaining = (next_run - now).total_seconds()
        if remaining <= 0:
            return
        sleep_chunk = min(remaining, 60.0)
        time.sleep(sleep_chunk)


def run_cron_loop() -> None:
    _configure_logging()
    logging.info("🚀 Starting IG cron loop; runs every %s hours", RUN_INTERVAL.total_seconds() / 3600)

    stop_requested = False

    def _handle_sigterm(signum, frame):
        nonlocal stop_requested
        logging.info("⚠️ Received signal %s; will exit after current run", signum)
        stop_requested = True

    signal.signal(signal.SIGTERM, _handle_sigterm)

    while True:
        run_started = datetime.now()
        logging.info("▶️  Run started at %s", run_started.isoformat())

        try:
            run_seed_workflow()
            logging.info("✅ Run finished at %s", datetime.now().isoformat())
        except KeyboardInterrupt:
            logging.info("⏹️  Interrupted by user; stopping cron loop")
            break
        except Exception:
            logging.exception("❌ Unhandled exception during IG seeding run")

        if stop_requested:
            logging.info("🛑 Stop requested; exiting cron loop")
            break

        next_run = run_started + RUN_INTERVAL
        logging.info("😴 Sleeping until next run at %s", next_run.isoformat())
        _sleep_until(next_run)


if __name__ == "__main__":
    run_cron_loop()


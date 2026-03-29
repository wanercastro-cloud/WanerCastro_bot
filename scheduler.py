from __future__ import annotations

import time

import schedule

from config import SETTINGS


def run_loop(run_overnight, run_review, run_status) -> None:
    schedule.every().day.at(f"{SETTINGS.overnight_hour:02d}:{SETTINGS.overnight_minute:02d}").do(run_overnight)
    schedule.every(SETTINGS.scan_interval_minutes).minutes.do(run_status)
    schedule.every(60).minutes.do(run_review)
    while True:
        schedule.run_pending()
        time.sleep(20)

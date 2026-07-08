"""Lightweight background scheduler for watch-topic radar runs.

Avoids adding a new dependency (APScheduler) for the local MVP: a single daemon
thread wakes up periodically and runs any watch topic whose interval has elapsed.
"""

from __future__ import annotations

import threading
import time
import traceback

_thread: threading.Thread | None = None
_stop = threading.Event()
POLL_SECONDS = 60


def _loop() -> None:
    # Imported lazily so this module has no import-time dependency on the discover
    # plugins / channels stack (keeps startup fast and avoids circular imports).
    from intel_service import run_due_watch_topics

    while not _stop.is_set():
        try:
            run_due_watch_topics()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        _stop.wait(POLL_SECONDS)


def start_scheduler() -> None:
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="intel-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()

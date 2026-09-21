"""Whether a pipeline run is in progress, shared by /run and the /api routes.

A run takes far longer than a polling interval, so a scheduler (or a second click)
will try to start another on top of it. Two runs would append to the same
checkpoint and race on output.json, so the second is refused. In-process rather
than a lock file, which would survive a crash and wedge every later run.
"""
import threading
from typing import Optional

lock = threading.Lock()

# Set by "stop" while a run holds the lock. The run checks it between emails, so the
# emails already in flight finish and are saved, and the rest are left for a resume.
_stop = threading.Event()

# Filled in by the run that holds the lock; read by /api/status for the progress bar.
current: dict = {"scope": None, "total": 0}


def begin(scope: str, total: int) -> None:
    _stop.clear()
    current.update(scope=scope, total=total)


def end() -> None:
    _stop.clear()
    current.update(scope=None, total=0)


def request_stop() -> bool:
    """Ask the run in progress to stop. False when nothing is running."""
    if not lock.locked():
        return False
    _stop.set()
    return True


def stop_requested() -> bool:
    return _stop.is_set()


def running_scope() -> Optional[str]:
    return current["scope"] if lock.locked() else None

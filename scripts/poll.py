"""Poll the inbox on an interval: process anything new, refresh the dashboard.

Each tick calls POST /run?new_only=true, which processes only the emails that have no
saved result in results/results.jsonl, such as ones that have appeared since the last tick.
Everything already saved, failed ones included, is left alone, so a tick that finds nothing
new costs no API calls, and an API outage is never retried (and re-billed) every interval.

    python scripts/poll.py                 # loop every 5 minutes
    python scripts/poll.py --interval 120  # loop every 2 minutes
    python scripts/poll.py --once          # single tick, for Task Scheduler/cron
    python scripts/poll.py --retry-failed  # also retry the emails that failed on the API

The server refuses overlapping runs with HTTP 409, so a tick that lands while
the previous one is still working skips rather than corrupting the checkpoint.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def log(message: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {message}", flush=True)


def run_url(base_url: str, retry_failed: bool = False) -> str:
    """New emails only by default; resume=true also retries the ones that failed."""
    return f"{base_url}/run?{'resume=true' if retry_failed else 'new_only=true'}"


def tick(base_url: str, rebuild: bool, retry_failed: bool = False) -> bool:
    """Run one poll. Returns False only for errors worth surfacing."""
    request = urllib.request.Request(run_url(base_url, retry_failed), method="POST")
    try:
        with urllib.request.urlopen(request, timeout=7200) as response:
            body = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 409:
            log("previous run still going -- skipping this tick")
            return True
        log(f"server returned {exc.code}: {exc.read()[:200]!r}")
        return False
    except urllib.error.URLError as exc:
        log(f"cannot reach {base_url} ({exc.reason}) -- is uvicorn running?")
        return False

    log(f"run complete: {body.get('emails_processed')} emails")

    if rebuild:
        result = subprocess.run(
            [sys.executable, str(ROOT / "web" / "build_report.py")],
            capture_output=True, text=True, cwd=ROOT,
        )
        if result.returncode == 0:
            log("dashboard data refreshed")
        else:
            log(f"build_report failed: {result.stderr.strip()[:200]}")
            return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=300, help="seconds between ticks")
    parser.add_argument("--once", action="store_true", help="one tick, then exit")
    parser.add_argument("--url", default="http://localhost:8000", help="server base URL")
    parser.add_argument("--no-rebuild", action="store_true", help="skip refreshing the dashboard")
    parser.add_argument("--retry-failed", action="store_true", help="also retry emails that failed on the model API")
    args = parser.parse_args()

    if args.once:
        return 0 if tick(args.url, not args.no_rebuild, args.retry_failed) else 1

    log(f"polling {args.url} every {args.interval}s -- Ctrl+C to stop")
    while True:
        try:
            tick(args.url, not args.no_rebuild, args.retry_failed)
        except KeyboardInterrupt:
            log("stopped")
            return 0
        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            log("stopped")
            return 0


if __name__ == "__main__":
    sys.exit(main())

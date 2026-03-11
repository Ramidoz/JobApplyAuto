"""
run_pipeline.py — Background scheduler for the job application pipeline.

Usage:
  python run_pipeline.py                  # one-shot, dry-run (safe default)
  python run_pipeline.py --live           # one-shot, submit real applications
  python run_pipeline.py --loop           # run every 6 hours, dry-run
  python run_pipeline.py --loop --live    # run every 6 hours, live mode
  python run_pipeline.py --interval 2     # loop every 2 hours

Statuses it will process:   pending, dry_run
Statuses it will skip:      submitted, skipped, needs_review, captcha_pending, error

Logs to: logs/pipeline.log  (also prints to stdout)
"""

import argparse
import json
import logging
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ─────────────────────────────────────────────
# PATHS
# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).parent
TRACKER_PATH = BASE_DIR / "applications_tracker.json"
APPLY_SCRIPT = BASE_DIR / "scripts" / "apply_playwright.py"
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_PATH = LOG_DIR / "pipeline.log"

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("pipeline")

# ─────────────────────────────────────────────
# TRACKER HELPERS
# ─────────────────────────────────────────────

PROCESSABLE_STATUSES = {"pending", "dry_run"}
SKIP_STATUSES = {"submitted", "skipped", "needs_review", "captcha_pending", "error"}


def load_tracker() -> dict:
    with open(TRACKER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_tracker(data: dict):
    data["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def update_job_status(tracker: dict, job_id: str, status: str, notes_append: str = ""):
    for job in tracker["applications"]:
        if job["id"] == job_id:
            job["status"] = status
            if notes_append:
                existing = job.get("notes", "")
                job["notes"] = (existing + " | " + notes_append).strip(" |")
            break
    save_tracker(tracker)


# ─────────────────────────────────────────────
# RUN ONE JOB
# ─────────────────────────────────────────────

def parse_result_from_output(stdout: str) -> dict | None:
    """Extract the JSON result line printed by apply_playwright.py."""
    for line in stdout.splitlines():
        if line.startswith("RESULT:"):
            try:
                return json.loads(line[len("RESULT:"):].strip())
            except json.JSONDecodeError:
                pass
    return None


def run_job(job: dict, live: bool, chrome_profile: str) -> dict:
    """
    Call apply_playwright.py for a single job.
    Returns the result dict (with at least a 'status' key).
    """
    cmd = [
        sys.executable, str(APPLY_SCRIPT),
        "--job-url", job["job_url"],
        "--resume", str(BASE_DIR / job["resume_path"]),
        "--headless",
        "--profile", chrome_profile,
    ]

    if job.get("cover_letter_path"):
        cmd += ["--cover-letter", str(BASE_DIR / job["cover_letter_path"])]

    if not live:
        cmd.append("--dry-run")

    log.info(f"[{job['id']}] Starting {'LIVE' if live else 'DRY RUN'} → {job['job_url']}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute hard cap per job
        )
        stdout = proc.stdout
        stderr = proc.stderr

        if stderr.strip():
            log.warning(f"[{job['id']}] stderr: {stderr.strip()[:300]}")

        result = parse_result_from_output(stdout)

        if result is None:
            log.error(f"[{job['id']}] No RESULT line found in output. stdout snippet: {stdout[-300:]}")
            return {"status": "error", "reason": "no_result_line"}

        return result

    except subprocess.TimeoutExpired:
        log.error(f"[{job['id']}] Timed out after 5 minutes.")
        return {"status": "error", "reason": "timeout"}
    except Exception as e:
        log.error(f"[{job['id']}] Unexpected error: {e}")
        return {"status": "error", "reason": str(e)}


# ─────────────────────────────────────────────
# ONE PIPELINE RUN
# ─────────────────────────────────────────────

def run_once(live: bool, chrome_profile: str) -> dict:
    """Process all pending/dry_run jobs. Returns a summary dict."""
    tracker = load_tracker()
    jobs = tracker.get("applications", [])

    pending = [j for j in jobs if j.get("status") in PROCESSABLE_STATUSES]
    skipped = [j for j in jobs if j.get("status") in SKIP_STATUSES]

    log.info("=" * 60)
    log.info(f"Pipeline run started — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    log.info(f"Mode: {'LIVE' if live else 'DRY RUN'} | Profile: {chrome_profile}")
    log.info(f"Jobs to process: {len(pending)} | Already done/skipped: {len(skipped)}")
    log.info("=" * 60)

    summary = {
        "submitted": [],
        "dry_run_ok": [],
        "needs_review": [],
        "captcha": [],
        "error": [],
        "skipped_already": [j["id"] for j in skipped],
    }

    if not pending:
        log.info("Nothing to process — all jobs are already handled.")
        return summary

    for job in pending:
        result = run_job(job, live=live, chrome_profile=chrome_profile)
        status = result.get("status", "error")

        # Map result status → tracker status
        tracker_status_map = {
            "submitted": "submitted",
            "dry_run_ok": "dry_run",         # stays dry_run until promoted to live
            "needs_review": "needs_review",
            "captcha": "captcha_pending",
            "captcha_timeout": "captcha_pending",
            "no_easy_apply": "skipped",
            "unsupported_platform": "skipped",
            "stuck": "needs_review",
            "max_steps_exceeded": "needs_review",
            "submit_not_found": "needs_review",
            "error": "error",
        }
        new_tracker_status = tracker_status_map.get(status, "error")

        notes = ""
        if result.get("flagged"):
            notes = "Flagged fields: " + ", ".join(result["flagged"])
        if result.get("reason"):
            notes = result["reason"]

        # Update tracker immediately after each job
        tracker = load_tracker()  # re-read in case of concurrent edits
        update_job_status(tracker, job["id"], new_tracker_status, notes)

        # Bucket for summary
        bucket = status if status in summary else "error"
        summary[bucket].append(job["id"])

        log.info(
            f"[{job['id']}] {status.upper()} → tracker: {new_tracker_status}"
            + (f" | {notes}" if notes else "")
        )

        # Brief pause between jobs to avoid hammering servers
        time.sleep(3)

    # Print summary
    log.info("")
    log.info("─── Run Summary ───────────────────────────────────────")
    for key in ("submitted", "dry_run_ok", "needs_review", "captcha", "error"):
        if summary[key]:
            log.info(f"  {key:20s}: {', '.join(summary[key])}")
    log.info(f"  {'already done':20s}: {len(summary['skipped_already'])} job(s)")
    log.info("───────────────────────────────────────────────────────")
    log.info("")

    return summary


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Background pipeline runner for job applications.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--live", action="store_true",
        help="Submit real applications (default: dry-run only)"
    )
    parser.add_argument(
        "--loop", action="store_true",
        help="Run continuously on a schedule (default: run once and exit)"
    )
    parser.add_argument(
        "--interval", type=float, default=6.0, metavar="HOURS",
        help="Hours between runs in --loop mode (default: 6)"
    )
    parser.add_argument(
        "--profile", default="Default", metavar="PROFILE",
        help="Chrome profile directory name (default: Default)"
    )
    args = parser.parse_args()

    if not TRACKER_PATH.exists():
        log.error(f"Tracker not found: {TRACKER_PATH}")
        sys.exit(1)

    if not APPLY_SCRIPT.exists():
        log.error(f"apply_playwright.py not found: {APPLY_SCRIPT}")
        sys.exit(1)

    if args.live:
        log.warning("LIVE MODE — applications will be submitted for real.")
    else:
        log.info("DRY RUN mode (safe). Pass --live to submit real applications.")

    if args.loop:
        interval_sec = int(args.interval * 3600)
        log.info(f"Loop mode: running every {args.interval}h. Press Ctrl+C to stop.")
        while True:
            try:
                run_once(live=args.live, chrome_profile=args.profile)
            except KeyboardInterrupt:
                log.info("Interrupted by user.")
                break
            except Exception as e:
                log.error(f"Run failed with exception: {e}")

            next_run = datetime.now().strftime("%H:%M")
            log.info(f"Sleeping {args.interval}h. Next run around "
                     f"{datetime.fromtimestamp(time.time() + interval_sec).strftime('%H:%M')}.")
            try:
                time.sleep(interval_sec)
            except KeyboardInterrupt:
                log.info("Interrupted during sleep. Exiting.")
                break
    else:
        run_once(live=args.live, chrome_profile=args.profile)


if __name__ == "__main__":
    main()

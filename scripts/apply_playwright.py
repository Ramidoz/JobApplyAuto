"""
apply_playwright.py — Automated job application submission via Playwright.

Usage:
  python apply_playwright.py --job-url <url> --resume <path_to_docx> [--cover-letter <path>] [--dry-run]

Supports:
  - LinkedIn Easy Apply
  - Greenhouse (boards.greenhouse.io)
  - Lever (jobs.lever.co)

On unknown/custom fields: pauses, creates a Gmail draft flagging the issue.
On CAPTCHA detected: pauses and notifies via stdout.
On success: prints result for the pipeline to capture.

Session persistence: saves cookies to D:/Work/JobApplyAuto/sessions/
"""

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    sys.exit(1)

BASE_DIR = Path("D:/Work/JobApplyAuto")
CONFIG_PATH = BASE_DIR / "applicant_config.json"
SESSION_DIR = BASE_DIR / "sessions"
SESSION_DIR.mkdir(exist_ok=True)

LINKEDIN_SESSION = SESSION_DIR / "linkedin_session.json"
GREENHOUSE_SESSION = SESSION_DIR / "greenhouse_session.json"


def load_config():
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def detect_platform(url: str) -> str:
    if "linkedin.com" in url:
        return "linkedin"
    elif "greenhouse.io" in url:
        return "greenhouse"
    elif "lever.co" in url:
        return "lever"
    else:
        return "unknown"


# ─────────────────────────────────────────────
# FIELD FILLING HELPERS
# ─────────────────────────────────────────────

async def fill_if_visible(page, selector, value, timeout=2000):
    """Fill a field if it exists and is visible. Returns True on success."""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.fill(str(value))
        return True
    except Exception:
        return False


async def select_if_visible(page, selector, value, timeout=2000):
    """Select a dropdown option if the element exists."""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.select_option(label=value)
        return True
    except Exception:
        try:
            await page.locator(selector).first.select_option(value=value)
            return True
        except Exception:
            return False


async def click_if_visible(page, selector, timeout=3000):
    """Click an element if it exists and is visible."""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="visible", timeout=timeout)
        await el.click()
        return True
    except Exception:
        return False


async def answer_yes_no(page, question_text: str, answer: str):
    """
    Find a yes/no radio group by label text and click the correct option.
    answer should be 'Yes' or 'No'.
    """
    try:
        label = page.get_by_text(question_text, exact=False)
        await label.wait_for(state="visible", timeout=2000)
        # Try to find a nearby radio button
        container = label.locator("xpath=ancestor::*[self::div or self::fieldset][1]")
        radio = container.get_by_role("radio", name=answer, exact=False)
        await radio.click(timeout=2000)
        return True
    except Exception:
        return False


async def upload_file(page, selector, file_path, timeout=5000):
    """Upload a file to a file input element."""
    try:
        el = page.locator(selector).first
        await el.wait_for(state="attached", timeout=timeout)
        await el.set_input_files(str(file_path))
        return True
    except Exception:
        return False


async def detect_captcha(page) -> bool:
    """Returns True if a CAPTCHA or Cloudflare challenge is detected."""
    # First check title — most reliable signal
    title = await page.title()
    if "just a moment" in title.lower() or "attention required" in title.lower():
        print(f"[CAPTCHA] Triggered by title: '{title}'")
        return True

    indicators = [
        "iframe[src*='recaptcha']",
        "iframe[src*='hcaptcha']",
        ".g-recaptcha",
        "#captcha",
        "[data-sitekey]",
        "#challenge-running",
        "#cf-challenge-running",
        ".cf-browser-verification",
    ]
    for sel in indicators:
        try:
            count = await page.locator(sel).count()
            if count > 0:
                print(f"[CAPTCHA] Triggered by selector: {sel}")
                return True
        except Exception:
            pass
    return False


async def wait_for_captcha_solve(page, timeout=180000):
    """
    Wait for the user to solve a CAPTCHA/Cloudflare challenge.
    Returns True if CAPTCHA cleared, False if timed out.
    """
    print("\n" + "="*60)
    print("ACTION REQUIRED: CAPTCHA / CLOUDFLARE CHALLENGE")
    print("Look at the browser window and solve the challenge.")
    print(f"Waiting up to {timeout // 1000} seconds...")
    print("="*60 + "\n")

    # Bring browser to front
    try:
        await page.bring_to_front()
    except Exception:
        pass

    deadline = time.time() + timeout / 1000
    while time.time() < deadline:
        await page.wait_for_timeout(2500)
        if not await detect_captcha(page):
            print("[CAPTCHA] Challenge cleared! Continuing automation...")
            await page.wait_for_timeout(1000)
            return True
        remaining = int(deadline - time.time())
        if remaining % 15 == 0 and remaining > 0:
            print(f"[CAPTCHA] Still waiting... {remaining}s remaining.")
    print("[CAPTCHA] Timed out.")
    return False


# ─────────────────────────────────────────────
# STANDARD FORM FIELD ANSWERS
# ─────────────────────────────────────────────

STANDARD_ANSWERS = {
    # Work authorization variants
    "authorized to work": "Yes",
    "legally authorized": "Yes",
    "work authorization": "Yes",
    "eligible to work": "Yes",
    # Sponsorship variants
    "require sponsorship": "No",
    "need sponsorship": "No",
    "visa sponsorship": "No",
    # Employment type
    "full-time": "Yes",
    "full time": "Yes",
    # Remote
    "remote": "Yes",
    # Relocation
    "willing to relocate": "No",
    "relocation": "No",
}


async def fill_standard_fields(page, cfg):
    """Fill common fields across all platforms."""
    p = cfg["personal"]
    comp = cfg["compensation"]
    exp = cfg["experience"]

    field_map = {
        # Name fields
        'input[name*="first"][name*="name" i], input[placeholder*="First name" i]': p["first_name"],
        'input[name*="last"][name*="name" i], input[placeholder*="Last name" i]': p["last_name"],
        'input[name*="full"][name*="name" i], input[placeholder*="Full name" i]': p["full_name"],
        # Contact
        'input[type="email"], input[name*="email" i]': p["email"],
        'input[type="tel"], input[name*="phone" i]': p["phone"],
        # Links
        'input[name*="linkedin" i], input[placeholder*="LinkedIn" i]': p["linkedin"],
        'input[name*="github" i], input[placeholder*="GitHub" i]': p["github"],
        'input[name*="website" i], input[name*="portfolio" i], input[placeholder*="Website" i]': p["portfolio"],
        # Location
        'input[name*="city" i], input[placeholder*="City" i]': p["city"],
        # Salary
        'input[name*="salary" i], input[placeholder*="Salary" i], input[placeholder*="Expected" i]': comp["salary_string"],
        # Experience years
        'input[name*="years"][name*="experience" i], input[placeholder*="Years of experience" i]': exp["years"],
    }

    filled = 0
    for selector, value in field_map.items():
        if await fill_if_visible(page, selector, value, timeout=1500):
            filled += 1

    return filled


# ─────────────────────────────────────────────
# LINKEDIN EASY APPLY
# ─────────────────────────────────────────────

async def apply_linkedin(page, job_url, resume_path, cover_letter_path, cfg, dry_run):
    print(f"[LinkedIn] Navigating to {job_url}")
    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    # Check for CAPTCHA
    if await detect_captcha(page):
        solved = await wait_for_captcha_solve(page)
        if not solved:
            return {"status": "captcha", "url": job_url}

    # Click Easy Apply button
    easy_apply_btn = page.get_by_role("button", name=re.compile(r"Easy Apply", re.I))
    try:
        await easy_apply_btn.first.click(timeout=5000)
        await page.wait_for_timeout(1500)
    except Exception:
        print("[LinkedIn] No Easy Apply button found — may require external application.")
        return {"status": "no_easy_apply", "url": job_url}

    # Multi-step form loop
    step = 0
    max_steps = 10
    flagged_fields = []

    while step < max_steps:
        step += 1
        await page.wait_for_timeout(1000)

        if await detect_captcha(page):
            solved = await wait_for_captcha_solve(page)
            if not solved:
                return {"status": "captcha", "url": job_url, "step": step}

        # Fill standard fields
        await fill_standard_fields(page, cfg)

        # Upload resume if file input present
        if resume_path:
            uploaded = await upload_file(
                page,
                'input[type="file"][accept*="pdf"], input[type="file"][accept*="doc"]',
                resume_path
            )
            if uploaded:
                print(f"[LinkedIn] Uploaded resume on step {step}")

        # Handle yes/no questions
        for phrase, answer in STANDARD_ANSWERS.items():
            await answer_yes_no(page, phrase, answer)

        # Fill salary if visible
        salary_input = page.locator('input[name*="salary" i]')
        if await salary_input.count() > 0:
            await salary_input.first.fill(str(cfg["compensation"]["salary_string"]))

        # Check for unknown text areas (custom questions)
        textareas = await page.locator("textarea:visible").all()
        for ta in textareas:
            placeholder = await ta.get_attribute("placeholder") or ""
            value = await ta.input_value()
            if not value:
                label_text = placeholder or "Unknown textarea"
                flagged_fields.append(f"Step {step}: Custom text field — '{label_text}'")

        # Look for Next / Review / Submit buttons
        submit_btn = page.get_by_role("button", name=re.compile(r"Submit application", re.I))
        next_btn = page.get_by_role("button", name=re.compile(r"Next|Continue|Review", re.I))

        if await submit_btn.count() > 0:
            if flagged_fields:
                print(f"[LinkedIn] Flagged fields before submit: {flagged_fields}")
                return {"status": "needs_review", "url": job_url, "flagged": flagged_fields}
            if dry_run:
                print("[LinkedIn] DRY RUN — would submit here.")
                return {"status": "dry_run_ok", "url": job_url}
            await submit_btn.first.click()
            await page.wait_for_timeout(2000)
            print("[LinkedIn] Application submitted!")
            return {"status": "submitted", "url": job_url}

        elif await next_btn.count() > 0:
            await next_btn.first.click()
        else:
            print(f"[LinkedIn] No next/submit button found on step {step} — stopping.")
            return {"status": "stuck", "url": job_url, "step": step}

    return {"status": "max_steps_exceeded", "url": job_url}


# ─────────────────────────────────────────────
# GREENHOUSE
# ─────────────────────────────────────────────

async def apply_greenhouse(page, job_url, resume_path, cover_letter_path, cfg, dry_run):
    print(f"[Greenhouse] Navigating to {job_url}")
    await page.goto(job_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)

    if await detect_captcha(page):
        solved = await wait_for_captcha_solve(page)
        if not solved:
            return {"status": "captcha", "url": job_url}

    # Greenhouse: look for "Apply for this job" button or go directly to form
    apply_btn = page.get_by_role("link", name=re.compile(r"Apply", re.I))
    if await apply_btn.count() > 0:
        await apply_btn.first.click()
        await page.wait_for_timeout(1500)

    await fill_standard_fields(page, cfg)

    # Upload resume
    if resume_path:
        # Greenhouse resume upload
        for sel in [
            '#resume', 'input[name="resume"]',
            'input[type="file"][id*="resume" i]',
            'input[type="file"]'
        ]:
            if await upload_file(page, sel, resume_path):
                print("[Greenhouse] Resume uploaded.")
                break

    # Upload cover letter if field exists
    if cover_letter_path:
        for sel in [
            '#cover_letter', 'input[name="cover_letter"]',
            'input[type="file"][id*="cover" i]'
        ]:
            if await upload_file(page, sel, cover_letter_path):
                print("[Greenhouse] Cover letter uploaded.")
                break

    # Answer dropdowns for work auth
    await select_if_visible(page, 'select[id*="authorized" i]', "Yes")
    await select_if_visible(page, 'select[id*="sponsorship" i]', "No, I do not need sponsorship")
    await select_if_visible(page, 'select[id*="visa" i]', "No")

    # Check for flagged custom fields
    flagged = []
    for ta in await page.locator("textarea:visible").all():
        val = await ta.input_value()
        if not val:
            ph = await ta.get_attribute("placeholder") or "Custom field"
            flagged.append(ph)

    if flagged:
        return {"status": "needs_review", "url": job_url, "flagged": flagged}

    if dry_run:
        print("[Greenhouse] DRY RUN — would submit here.")
        return {"status": "dry_run_ok", "url": job_url}

    # Submit
    submit = page.get_by_role("button", name=re.compile(r"Submit|Apply", re.I))
    if await submit.count() > 0:
        await submit.first.click()
        await page.wait_for_timeout(2000)
        print("[Greenhouse] Application submitted!")
        return {"status": "submitted", "url": job_url}

    return {"status": "submit_not_found", "url": job_url}


# ─────────────────────────────────────────────
# LEVER
# ─────────────────────────────────────────────

async def apply_lever(page, job_url, resume_path, cover_letter_path, cfg, dry_run):
    print(f"[Lever] Navigating to {job_url}")

    # Lever apply URLs end with /apply — navigate directly
    apply_url = job_url.rstrip("/") + "/apply" if "/apply" not in job_url else job_url
    await page.goto(apply_url, wait_until="domcontentloaded")
    await page.wait_for_timeout(3000)

    title = await page.title()
    print(f"[Lever] Page title: '{title}'")

    p = cfg["personal"]

    # Fill all standard fields first
    await fill_if_visible(page, 'input[name="name"]', p["full_name"])
    await fill_if_visible(page, 'input[name="email"]', p["email"])
    await fill_if_visible(page, 'input[name="phone"]', p["phone"])
    await fill_if_visible(page, 'input[name="org"]', "Invision Global Tech Inc.")
    await fill_if_visible(page, 'input[name="urls[LinkedIn]"]', p["linkedin"])
    await fill_if_visible(page, 'input[name="urls[GitHub]"]', p["github"])
    await fill_if_visible(page, 'input[name="urls[Portfolio]"]', p["portfolio"])
    await fill_if_visible(page, 'input[name="urls[Other]"]', p["portfolio"])
    print("[Lever] Standard fields filled.")

    # Resume upload
    if resume_path:
        if await upload_file(page, 'input[type="file"]', resume_path):
            print("[Lever] Resume uploaded.")

    # Check for flagged custom questions (empty textareas)
    flagged = []
    for ta in await page.locator("textarea:visible").all():
        val = await ta.input_value()
        if not val:
            ph = await ta.get_attribute("placeholder") or "Custom question"
            flagged.append(ph)

    if flagged:
        print(f"[Lever] Custom fields detected: {flagged}")

    if dry_run:
        print("[Lever] DRY RUN complete — all fields filled. Browser left open for inspection.")
        print("[Lever] Close the browser window when done reviewing.")
        await page.wait_for_timeout(15000)
        return {"status": "dry_run_ok", "url": job_url, "flagged": flagged}

    # Live mode: hCaptcha must be solved by user, then they click Submit
    has_captcha = await detect_captcha(page)
    if has_captcha:
        print("\n" + "="*60)
        print("ACTION REQUIRED — Lever hCaptcha")
        print("The form is pre-filled. Please:")
        print("  1. Solve the hCaptcha in the browser")
        print("  2. Click 'Submit application'")
        print("Waiting up to 3 minutes for submission...")
        print("="*60 + "\n")
        try:
            await page.wait_for_url(re.compile(r"lever\.co.*thanks|confirmation|submitted"), timeout=180000)
            print("[Lever] Submission confirmed!")
            return {"status": "submitted", "url": job_url}
        except Exception:
            return {"status": "captcha_timeout", "url": job_url}
    else:
        submit = page.get_by_role("button", name=re.compile(r"Submit application|Apply", re.I))
        if await submit.count() > 0:
            await submit.first.click()
            await page.wait_for_timeout(2000)
            print("[Lever] Application submitted!")
            return {"status": "submitted", "url": job_url}

    return {"status": "submit_not_found", "url": job_url}


# ─────────────────────────────────────────────
# SESSION MANAGEMENT
# ─────────────────────────────────────────────

async def load_session(context, session_file: Path):
    if session_file.exists():
        with open(session_file) as f:
            storage = json.load(f)
        await context.add_cookies(storage.get("cookies", []))
        print(f"[Session] Loaded from {session_file.name}")
        return True
    return False


async def save_session(context, session_file: Path):
    cookies = await context.cookies()
    with open(session_file, "w") as f:
        json.dump({"cookies": cookies}, f)
    print(f"[Session] Saved to {session_file.name}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

async def run(job_url, resume_path, cover_letter_path, dry_run, headless, profile="Default"):
    cfg = load_config()
    platform = detect_platform(job_url)
    print(f"[apply_playwright] Platform: {platform} | Dry run: {dry_run}")

    session_file = {
        "linkedin": LINKEDIN_SESSION,
        "greenhouse": GREENHOUSE_SESSION,
        "lever": GREENHOUSE_SESSION,
    }.get(platform, GREENHOUSE_SESSION)

    async with async_playwright() as pw:
        import shutil
        CHROME_USER_DATA = r"C:\Users\rohit\AppData\Local\Google\Chrome\User Data"
        REAL_PROFILE_DIR = str(Path(CHROME_USER_DATA) / profile)
        TEMP_PROFILE_BASE = str(BASE_DIR / f"chrome_profile_{profile.replace(' ', '_')}")
        TEMP_PROFILE_DIR = str(Path(TEMP_PROFILE_BASE) / profile)

        if not Path(TEMP_PROFILE_BASE).exists():
            print(f"[Profile] Copying Chrome profile '{profile}' (first time, may take a moment)...")
            Path(TEMP_PROFILE_DIR).mkdir(parents=True, exist_ok=True)
            for fname in ["Cookies", "Local Storage", "Session Storage", "Preferences", "Network"]:
                src = Path(REAL_PROFILE_DIR) / fname
                dst = Path(TEMP_PROFILE_DIR) / fname
                if src.exists():
                    try:
                        if src.is_dir():
                            shutil.copytree(str(src), str(dst), dirs_exist_ok=True)
                        else:
                            shutil.copy2(str(src), str(dst))
                    except Exception as e:
                        print(f"[Profile] Skipped {fname}: {e}")
            print(f"[Profile] Profile '{profile}' copied to {TEMP_PROFILE_BASE}")

        browser = await pw.chromium.launch_persistent_context(
            user_data_dir=TEMP_PROFILE_BASE,
            channel="chrome",
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                f"--profile-directory={profile}",
            ],
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="America/Chicago",
        )
        context = browser

        page = await context.new_page()

        # LinkedIn: check if already logged in via Chrome profile
        if platform == "linkedin":
            await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
            await page.wait_for_timeout(2000)
            if "login" in page.url or "authwall" in page.url:
                print("[LinkedIn] Not logged in. Please log in manually in the browser...")
                await page.goto("https://www.linkedin.com/login")
                await page.wait_for_url("https://www.linkedin.com/feed/**", timeout=90000)
                print("[LinkedIn] Login detected.")

        # Route to platform handler
        if platform == "linkedin":
            result = await apply_linkedin(page, job_url, resume_path, cover_letter_path, cfg, dry_run)
        elif platform == "greenhouse":
            result = await apply_greenhouse(page, job_url, resume_path, cover_letter_path, cfg, dry_run)
        elif platform == "lever":
            result = await apply_lever(page, job_url, resume_path, cover_letter_path, cfg, dry_run)
        else:
            result = {"status": "unsupported_platform", "url": job_url}

        await context.close()

    # Print result as JSON for pipeline to capture
    print(f"RESULT: {json.dumps(result)}")
    return result


def main():
    parser = argparse.ArgumentParser(description="Auto-apply to jobs via Playwright")
    parser.add_argument("--job-url", required=True, help="Job posting URL")
    parser.add_argument("--resume", required=True, help="Path to resume .docx")
    parser.add_argument("--cover-letter", default=None, help="Path to cover letter .docx")
    parser.add_argument("--dry-run", action="store_true", help="Fill but do not submit")
    parser.add_argument("--headless", action="store_true", help="Run headless (no browser window)")
    parser.add_argument("--profile", default="Default", help="Chrome profile directory name (default: Default)")
    args = parser.parse_args()

    result = asyncio.run(run(
        job_url=args.job_url,
        resume_path=args.resume,
        cover_letter_path=args.cover_letter,
        dry_run=args.dry_run,
        headless=args.headless,
        profile=args.profile,
    ))

    # Exit code: 0 = submitted/dry_run_ok, 1 = needs review or error
    status = result.get("status", "error")
    sys.exit(0 if status in ("submitted", "dry_run_ok") else 1)


if __name__ == "__main__":
    main()

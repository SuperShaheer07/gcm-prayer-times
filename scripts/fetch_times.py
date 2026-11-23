#!/usr/bin/env python3
"""Fetch Glasgow Central Mosque's prayer BEGIN times and save them to data/prayer-times.json.

The times come from the same public feed GCM's own website uses
(the "Daily Prayer Time for Mosques" WordPress plugin):
  https://centralmosque.co.uk/?rest_route=/dpt/v1/prayertime&filter=today  -> today and tomorrow
  https://centralmosque.co.uk/?rest_route=/dpt/v1/prayertime&filter=year   -> every day of the current year
  https://centralmosque.co.uk/  (homepage)                                  -> the Hijri date exactly as GCM shows it

Note: the feed's own "hijri_date_convert" field is NOT used. It is one day ahead of
the Hijri date GCM actually displays (GCM applies its own adjustment on the website).

Safety rules:
  * If anything goes wrong, the existing JSON file is left exactly as it was.
  * New data is merged into the old, so days we already know are never lost.
Only the Python standard library is used, so nothing needs installing.
"""

import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.request
from zoneinfo import ZoneInfo

BASE = "https://centralmosque.co.uk/?rest_route=/dpt/v1/prayertime&filter="
HOME = "https://centralmosque.co.uk/"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "prayer-times.json")
LONDON = ZoneInfo("Europe/London")
HEADERS = {
    "User-Agent": "GCM-prayer-display/1.0 (GitHub Actions; a few requests per day)",
    "Accept": "application/json",
}
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
KEEP_PAST_DAYS = 7  # keep a week of history so a display that was offline can still recover
MAX_HIJRI = 14


def log(msg):
    print(msg, flush=True)


def get_text(url, accept):
    """Download a page, retrying a few times on a network hiccup."""
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=dict(HEADERS, Accept=accept))
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except Exception as err:  # noqa: BLE001 - we really do want to catch everything here
            last_err = err
            log(f"  attempt {attempt + 1} for {url} failed: {err}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not download {url}: {last_err}")


def get_json(filter_name):
    return json.loads(get_text(BASE + filter_name, "application/json"))


HOME_DATE_RE = re.compile(r'class="general-date"[^>]*>\s*<p>\s*([^<]+?)\s*</p>', re.S)
HOME_HIJRI_RE = re.compile(r"class=['\"]scHijriDate['\"][^>]*>\s*([^<]+?)\s*<")


def get_homepage_hijri():
    """Return (iso_date, hijri_text) exactly as shown on GCM's homepage."""
    page = get_text(HOME, "text/html")
    d, h = HOME_DATE_RE.search(page), HOME_HIJRI_RE.search(page)
    if not d or not h:
        raise RuntimeError("could not find the dates on GCM's homepage (layout may have changed)")
    greg = dt.datetime.strptime(" ".join(d.group(1).split()), "%d %B %Y").date()
    hijri = html.unescape(" ".join(h.group(1).split()))
    if not re.match(r"^\d{1,2}\s", hijri) or len(hijri) > 80:
        raise RuntimeError(f"unexpected Hijri text on homepage: {hijri!r}")
    return greg.isoformat(), hijri


def hhmm(value):
    """'13:40:00' -> '13:40'. Returns None if it doesn't look like a time."""
    m = TIME_RE.match(str(value or "").strip())
    if not m:
        return None
    h, mnt = int(m.group(1)), int(m.group(2))
    if h > 23 or mnt > 59:
        return None
    return f"{h:02d}:{mnt:02d}"


def convert_day(raw):
    """Turn one plugin row into our small format. BEGIN times only; Asr = Asr I (mithl 1)."""
    if not isinstance(raw, dict):
        return None, None
    date = str(raw.get("d_date", ""))
    if not DATE_RE.match(date):
        return None, None
    day = {
        "fajr": hhmm(raw.get("fajr_begins")),
        "sunrise": hhmm(raw.get("sunrise")),
        "zuhr": hhmm(raw.get("zuhr_begins")),
        "asr": hhmm(raw.get("asr_mithl_1")),
        "maghrib": hhmm(raw.get("maghrib_begins")),
        "isha": hhmm(raw.get("isha_begins")),
    }
    if any(v is None for v in day.values()):
        return None, None
    order = [day[k] for k in ("fajr", "sunrise", "zuhr", "asr", "maghrib", "isha")]
    if order != sorted(order):  # times must run in order through the day
        return None, None
    return date, day


def rows(payload):
    """The plugin wraps its rows in one or two lists; flatten them."""
    out = []
    stack = [payload]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            out.append(item)
    return out


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
    except FileNotFoundError:
        pass
    except Exception as err:  # noqa: BLE001
        log(f"Existing file unreadable ({err}); starting fresh.")
    return {}


def main():
    now = dt.datetime.now(LONDON)
    today = now.date()
    # Window to keep: a week back, up to the end of NEXT month.
    first_next = (today.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    end_next = (first_next + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    start = today - dt.timedelta(days=KEEP_PAST_DAYS)

    existing = load_existing()
    days = dict(existing.get("days") or {})
    hijri = dict(existing.get("hijri") or {})

    new_days = {}
    errors = []

    # 1) Today's feed: today + tomorrow.
    try:
        for r in rows(get_json("today")):
            for candidate in (r, r.get("tomorrow")):
                d, v = convert_day(candidate)
                if d:
                    new_days[d] = v
    except Exception as err:  # noqa: BLE001
        errors.append(str(err))

    # 1b) The Hijri date, read from GCM's homepage so it matches what they display.
    try:
        greg, h = get_homepage_hijri()
        if abs((dt.date.fromisoformat(greg) - today).days) <= 1:
            hijri[greg] = h
        else:
            errors.append(f"homepage showed an old date ({greg}); Hijri not updated")
    except Exception as err:  # noqa: BLE001
        errors.append(str(err))

    # 2) The whole year (covers this month and next month, except across New Year).
    try:
        for r in rows(get_json("year")):
            d, v = convert_day(r)
            if d:
                new_days[d] = v
    except Exception as err:  # noqa: BLE001
        errors.append(str(err))

    if not new_days:
        log("No usable prayer times were downloaded. Keeping the existing file untouched.")
        for e in errors:
            log("  - " + e)
        return 1

    if today.isoformat() not in new_days and today.isoformat() not in days:
        log("Warning: GCM's feed did not include today's date.")

    days.update(new_days)
    days = {
        d: v for d, v in sorted(days.items())
        if start.isoformat() <= d <= end_next.isoformat()
    }
    hijri = dict(sorted(hijri.items())[-MAX_HIJRI:])

    out = {
        "source": "https://centralmosque.co.uk/prayer-times/",
        "note": "Begin times only. Asr = Asr I (first Asr time).",
        "updated": now.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hijri": hijri,
        "days": days,
    }

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, OUT)  # swap in the new file in one step, so it is never half-written

    log(f"Saved {len(days)} days ({min(days)} to {max(days)}). Hijri today: {hijri.get(today.isoformat(), 'n/a')}")
    if end_next.isoformat() not in days:
        log(f"Note: GCM has not published times up to {end_next} yet (normal near New Year).")
    for e in errors:
        log("Partial problem (the rest was saved): " + e)
    return 0


if __name__ == "__main__":
    sys.exit(main())

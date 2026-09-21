"""Works-here check. Runs in CI after new leads land.

People change jobs, and databases lag by months. So before a lead is handed over we
scrape the person's LinkedIn profile, compare their current positions to the company on
the row, and:
  - mark them STILL HERE, or
  - mark them LEFT (with where they went), drop them, and hand the company back to the
    people step so someone else at that company takes the slot.

Uses the Apify LinkedIn profile scraper. Token from APIFY_TOKEN.
"""
import json
import os
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request

from .util import linkedin_slug

ACTOR = "https://api.apify.com/v2/acts/harvestapi~linkedin-profile-scraper/run-sync-get-dataset-items"
STOP = {"the", "group", "and", "inc", "llc", "ltd", "corp", "co", "services", "service",
        "international", "groupe", "gmbh", "ag", "limited", "solutions", "management",
        "canada", "germany", "deutschland"}


def tokens(s):
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return {t for t in re.sub(r"[^a-z ]", " ", s.lower()).split() if len(t) > 1 and t not in STOP}


def current_companies(profile):
    out = [p.get("companyName") or "" for p in (profile.get("currentPosition") or [])]
    for e in profile.get("experience") or []:
        if ((e.get("endDate") or {}).get("text") or "").lower() == "present":
            out.append(e.get("companyName") or "")
    out.append(profile.get("headline") or "")
    return [c for c in out if c]


def works_here(profile, company):
    """(True, '') if any current position shares a word with the company name,
    else (False, where they are now)."""
    target = tokens(company)
    now = current_companies(profile)
    if any(target & tokens(c) for c in now):
        return True, ""
    return False, next((c for c in now if "linkedin" not in c.lower()), "unknown")


def scrape(urls, batch=10):
    token = os.environ.get("APIFY_TOKEN")
    if not token:
        sys.exit("Set APIFY_TOKEN first.")
    url = ACTOR + "?" + urllib.parse.urlencode({"token": token})
    profiles = {}
    for i in range(0, len(urls), batch):
        body = json.dumps({"urls": urls[i:i + batch],
                           "profileScraperMode": "Profile details no email"}).encode()
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        try:
            items = json.load(urllib.request.urlopen(req, timeout=300))
        except Exception as e:                          # one bad batch should not stop the run
            print("  apify error: %s" % str(e)[:80], file=sys.stderr)
            items = []
        for q in items or []:
            if isinstance(q, dict) and not q.get("error"):
                s = linkedin_slug(q.get("linkedinUrl")) or (q.get("publicIdentifier") or "").lower()
                if s:
                    profiles[s] = q
        time.sleep(4)
    return profiles


def check(leads, profiles):
    """Split leads into (kept, left). Leads we could not scrape are kept and left unmarked,
    so the next run tries them again."""
    kept, left = [], []
    for r in leads:
        pr = profiles.get(linkedin_slug(r.get("linkedin_url")))
        if not pr:
            kept.append(r)
            continue
        ok, now = works_here(pr, r.get("company", ""))
        if ok:
            r["verify"] = "STILL HERE"
            kept.append(r)
        else:
            r["verify"] = "LEFT -> %s" % now[:40]
            left.append(r)
    return kept, left

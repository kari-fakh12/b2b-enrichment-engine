"""The end-of-day file: only the leads that are new since the last run.

Keeps a plain-text snapshot of who was already sent. The first run only seeds the
snapshot and sends nothing, so nobody gets the whole back catalogue by email.
Prints NEW=<n> and FILE=<path> for the GitHub Action to pick up.
"""
import datetime
import os

from .util import company_key, linkedin_slug, person_key, read_csv, write_csv

COLS = ["date_added", "company", "vertical", "full_name", "job_title", "persona", "tier",
        "score", "phone", "linkedin_url", "opener", "opener_status", "verify"]


def _key(r):
    return linkedin_slug(r.get("linkedin_url")) or "%s@%s" % (
        person_key(r.get("full_name")), company_key(r.get("company")))


def build(leads_csv, snapshot, out_dir):
    rows = [r for r in read_csv(leads_csv) if (r.get("full_name") or "").strip()]
    keys = [_key(r) for r in rows]
    if not os.path.exists(snapshot):
        with open(snapshot, "w", encoding="utf-8") as fh:
            fh.write("\n".join(keys) + "\n")
        print("seeded snapshot with %d leads, nothing sent this run" % len(keys))
        print("NEW=0")
        return None
    with open(snapshot, encoding="utf-8") as fh:
        seen = {line.strip() for line in fh if line.strip()}
    new = [r for r, k in zip(rows, keys) if k not in seen]
    with open(snapshot, "w", encoding="utf-8") as fh:
        fh.write("\n".join(keys) + "\n")
    print("new since last digest: %d" % len(new))
    if not new:
        print("NEW=0")
        return None
    today = datetime.date.today().isoformat()
    for r in new:
        r["date_added"] = today
    new.sort(key=lambda r: (r.get("vertical") or "", r.get("company") or ""))
    out = os.path.join(out_dir, "new-leads-%s.csv" % today)
    write_csv(out, new, COLS)
    print("NEW=%d" % len(new))
    print("FILE=%s" % out)
    return out

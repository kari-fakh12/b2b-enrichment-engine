"""The WHO step: find the senior people at each qualified company, most senior first.

Per company we want two people:
  - a decision-maker (the economic buyer: MD, CEO, COO, owner)
  - a pain-feeler (whoever owns call quality every day: Head of QA, Head of Contact Centre)

Managers (tier C) only fill a company where nobody senior turned up. Off-ICP functions
(HR, legal, creative, engineering) are dropped however senior the title sounds, because a
people database happily returns an "Art Director" for the word "Director".
"""
import os
import sys

from . import config
from .http import post_json
from .util import domain_of, linkedin_slug, person_key

PROSPEO_PERSON = "https://api.prospeo.io/search-person"


def tier_of(title):
    if config.TIER_A.search(title or ""):
        return "A"
    if config.TIER_B.search(title or ""):
        return "B"
    return "C"


def rank(title, table):
    for rx, pts in table:
        if rx.search(title or ""):
            return pts
    return 0


def classify(person):
    t = person.get("job_title") or ""
    person["tier"] = tier_of(t)
    person["persona"] = "pain-feeler" if config.PAIN_FEELER.search(t) else "decision-maker"
    return person


def select(people, per_company=config.PEOPLE_PER_COMPANY):
    """Pick up to `per_company` people per company. Returns (picked, gaps) where gaps maps
    company -> the roles still missing, so someone can go find them by hand."""
    by_co, order = {}, []
    for p in people:
        classify(p)
        co = p.get("company") or ""
        if co not in by_co:
            by_co[co] = []
            order.append(co)
        if config.OFF_ICP.search(p.get("job_title") or ""):
            continue
        by_co[co].append(p)

    picked, gaps = [], {}
    tier_order = {"A": 0, "B": 1, "C": 2}
    for co in order:
        cands = by_co[co]
        senior = [p for p in cands if p["tier"] in ("A", "B")]
        pool = senior or cands                       # managers only if nobody senior
        # most senior first, then how well the title fits the role
        dm = sorted(pool, key=lambda p: (tier_order[p["tier"]],
                                         -rank(p["job_title"], config.DECISION_MAKER_RANK)))
        dm = next((p for p in dm if rank(p["job_title"], config.DECISION_MAKER_RANK)), None)
        pf = sorted(pool, key=lambda p: -rank(p["job_title"], config.PAIN_FEELER_RANK))
        pf = next((p for p in pf if rank(p["job_title"], config.PAIN_FEELER_RANK)
                   and p is not dm), None)
        chosen = []
        if dm:
            dm["persona"] = "decision-maker"
            chosen.append(dm)
        if pf:
            pf["persona"] = "pain-feeler"
            chosen.append(pf)
        # still room: fill with the next most senior people left in the pool
        rest = sorted((p for p in pool if p not in chosen),
                      key=lambda p: tier_order[p["tier"]])
        chosen += rest[:max(0, per_company - len(chosen))]
        picked += chosen[:per_company]
        missing = [r for r, hit in (("decision-maker", dm), ("pain-feeler", pf)) if not hit]
        if missing:
            gaps[co] = missing
    return picked, gaps


# ------------------------------------------------------------------ provider
def _flatten(r, companies_by_domain):
    p, co = r.get("person") or {}, r.get("company") or {}
    dom = domain_of(co.get("domain") or co.get("website") or "")
    acct = companies_by_domain.get(dom, {})
    mob = p.get("mobile") or {}
    return {
        "company": acct.get("company") or co.get("name", ""),
        "domain": dom,
        "full_name": p.get("full_name") or ("%s %s" % (p.get("first_name", ""),
                                                       p.get("last_name", ""))).strip(),
        "first_name": p.get("first_name", ""),
        "job_title": p.get("current_job_title", "") or "",
        "city": (p.get("location") or {}).get("city", ""),
        "linkedin_url": p.get("linkedin_url", ""),
        "email": (p.get("email") or {}).get("email", "") if isinstance(p.get("email"), dict)
        else (p.get("email") or ""),
        "mobile_status": mob.get("status", ""),
        "source": "prospeo",
    }


def search_prospeo(companies, market, max_people=400, max_pages=40):
    """Senior people at the given (already qualified) companies. Search is free of the
    mobile filter on purpose: the phone waterfall exists to find the numbers Prospeo lacks."""
    key = os.environ.get("PROSPEO_API_KEY")
    if not key:
        sys.exit("Set PROSPEO_API_KEY first.")
    by_dom = {c["domain"]: c for c in companies if c.get("domain")}
    if not by_dom:
        return []
    filters = {
        "person_location_search": {"include": [config.MARKETS[market]["location"]]},
        "person_job_title": {"include": config.JOB_TITLES, "match_mode": "CONTAINS"},
        "company": {"websites": {"include": sorted(by_dom), "exclude": []}},
    }
    out, seen = [], set()
    for page in range(1, max_pages + 1):
        r = post_json(PROSPEO_PERSON, {"page": page, "filters": filters},
                      headers={"X-KEY": key}, pause=0.5)
        res = r.get("results") or []
        for x in res:
            p = _flatten(x, by_dom)
            k = linkedin_slug(p["linkedin_url"]) or person_key(p["full_name"])
            if k and k not in seen:
                seen.add(k)
                out.append(p)
        if not res or len(out) >= max_people:
            break
        if page >= (r.get("pagination") or {}).get("total_page", page):
            break
    return out

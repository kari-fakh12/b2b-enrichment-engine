"""Discovery: three lanes that each produce candidate companies.

None of these lanes decides anything. An industry tag or a job post is not a phone floor.
Every candidate goes through qualify.py before anyone gets enriched.

  1. accounts  - a researched account list (CSV you or a research agent built by hand)
  2. prospeo   - Prospeo company search on website text and NAICS codes, per segment
  3. hiring    - companies posting call-QA / quality-monitoring jobs (a CSV or JSONL export)
"""
import json
import os
import sys

from . import config
from .http import post_json
from .util import company_key, domain_of, read_csv

PROSPEO_COMPANY = "https://api.prospeo.io/search-company"

# One search per segment. Industry labels are thin for these businesses (in Germany the
# "Collection Agencies" label returned zero companies), so search the company's own website
# text and NAICS codes instead. Noisier, and that is fine: the qualifier decides.
SEGMENT_SEARCHES = {
    "CA": [
        {"segment": "Debt collection / ARM",
         "keywords": ["collection agency", "accounts receivable management", "recouvrement"]},
        {"segment": "BPO / contact centre", "naics": [561422]},
        {"segment": "BPO / contact centre",
         "keywords": ["contact centre outsourcing", "call centre", "answering service"]},
        {"segment": "Insurance / claims",
         "keywords": ["claims management", "roadside assistance", "insurance broker"]},
    ],
    "DE": [
        {"segment": "Debt collection / ARM",
         "keywords": ["Inkasso", "Forderungsmanagement", "Debt collection"]},
        {"segment": "BPO / contact centre", "naics": [561422]},
        {"segment": "BPO / contact centre",
         "keywords": ["Callcenter", "Contact Center", "Kundenservice Outsourcing"]},
        {"segment": "Insurance / claims", "naics": [524291]},
        {"segment": "Insurance / claims",
         "keywords": ["Schadenmanagement", "Schadenregulierung", "Assistance"]},
        {"segment": "Market research (CATI)",
         "keywords": ["Telefonstudio", "CATI", "Telefonbefragung"]},
    ],
}
DEFAULT_SEARCHES = [
    {"segment": "Debt collection / ARM", "keywords": ["debt collection", "collection agency"]},
    {"segment": "BPO / contact centre", "naics": [561422]},
    {"segment": "Insurance / claims", "naics": [524291]},
]

# The job searches the hiring lane was built on. A company hiring for these roles is
# doing call QA by hand today, which is the pain.
HIRING_QUERIES = [
    "call quality analyst contact centre",
    "quality assurance analyst call centre",
    "contact centre quality coach",
    "call centre compliance monitoring",
    "customer service quality analyst",
    "speech analytics quality contact centre",
]


def _candidate(name, website, source, **extra):
    c = {"company": (name or "").strip(), "website": (website or "").strip(),
         "domain": domain_of(website), "source": source}
    c.update({k: v for k, v in extra.items() if v not in (None, "")})
    return c


# ------------------------------------------------------------------ lane 1
def from_accounts(path):
    """A researched account list. Needs at least `company` and `website` columns; any of
    headcount, vertical, runs_call_centre, qa_evidence, pain, fact, fact_source carry through."""
    out = []
    for r in read_csv(path):
        r = {k.strip().lower(): (v or "").strip() for k, v in r.items() if k}
        name = r.pop("company", "")
        web = r.pop("website", "")
        if name:
            out.append(_candidate(name, web, "accounts", **r))
    return out


# ------------------------------------------------------------------ lane 2
def from_prospeo(market, max_pages=1, estimate=False):
    """Prospeo company search. 1 credit per page of 25. `estimate` reads page 1 only."""
    key = os.environ.get("PROSPEO_API_KEY")
    if not key:
        sys.exit("Set PROSPEO_API_KEY first.")
    m = config.MARKETS[market]
    out = []
    for spec in SEGMENT_SEARCHES.get(market, DEFAULT_SEARCHES):
        f = {"company_location_search": {"include": [m["location"]]},
             "company_headcount_custom": {"min": config.HEADCOUNT_MIN, "max": config.HEADCOUNT_MAX}}
        if spec.get("keywords"):
            f["company_keywords"] = {"include": spec["keywords"], "include_all": False,
                                     "search_everywhere": True,
                                     "sources": ["specialties", "seo_description", "website_pages"]}
        if spec.get("naics"):
            f["company_naics"] = {"include": spec["naics"]}      # integers, not strings
        total = None
        for page in range(1, (1 if estimate else max_pages) + 1):
            r = post_json(PROSPEO_COMPANY, {"page": page, "filters": f},
                          headers={"X-KEY": key}, pause=1.2)
            if total is None:
                total = (r.get("pagination") or {}).get("total_count", 0)
            res = r.get("results") or []
            for x in res:
                co = x.get("company", x)
                out.append(_candidate(co.get("name"), co.get("website") or co.get("domain"),
                                      "prospeo", vertical=spec["segment"],
                                      headcount=co.get("headcount"),
                                      prospeo_industry=co.get("industry"), country=market))
            if not res:
                break
        print("  prospeo %-24s %s total in %s" % (spec["segment"][:24], total, market))
    return out


# ------------------------------------------------------------------ lane 3
def from_hiring(path):
    """Job posts, one per line (JSONL) or row (CSV), with company, title and url.
    Any job source works; the queries above are what we searched on."""
    rows = []
    if path.endswith(".jsonl"):
        with open(path, encoding="utf-8") as fh:
            rows = [json.loads(line) for line in fh if line.strip()]
    else:
        rows = read_csv(path)
    by_co = {}
    for r in rows:
        name = r.get("company") or ""
        if not name:
            continue
        c = by_co.setdefault(company_key(name), _candidate(
            name, r.get("website", ""), "hiring", country=r.get("country", "")))
        c.setdefault("jobs", []).append(r.get("title", ""))
        # The job post itself is the checkable fact, with its own URL as the source.
        if r.get("url") and "fact" not in c:
            c["qa_evidence"] = "yes"
            c["pain"] = "hiring for call QA"
            c["fact"] = "%s is hiring a %s" % (name, r.get("title", "").strip())
            c["fact_source"] = r["url"]
    for c in by_co.values():
        c["jobs"] = "; ".join(c["jobs"])
    return list(by_co.values())


def merge(*lanes):
    """One row per company across lanes. The first lane to supply a field wins; the
    source column keeps every lane that found it."""
    merged = {}
    for lane in lanes:
        for c in lane:
            k = c["domain"] or company_key(c["company"])
            if not k:
                continue
            if k not in merged:
                merged[k] = dict(c)
                continue
            m = merged[k]
            if c["source"] not in m["source"].split("+"):
                m["source"] += "+" + c["source"]
            for f, v in c.items():
                if v and not m.get(f):
                    m[f] = v
    return list(merged.values())

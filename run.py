#!/usr/bin/env python3
"""Command line for the enrichment engine.

  python3 run.py --sample                  offline run on examples/, no keys, no network
  python3 run.py crm-fetch                 pull the HubSpot dedupe cache (read-only)
  python3 run.py --market CA discover --accounts accounts.csv [--hiring jobs.jsonl] [--prospeo]
  python3 run.py --market CA enrich            people + numbers + score + openers (prices only)
  python3 run.py --market CA enrich --spend    same, and actually pays for reveals
  python3 run.py --market CA verify --replace  works-here check, drop leavers, refill their slot
  python3 run.py digest                        today's new leads as a CSV

Global options (--market, --markets, --crm) go before the command.

Standard library only. Python 3.8+.
"""
import argparse
import os
import sys
from collections import Counter

from engine import discover, openers, people, phones, qualify
from engine.dedupe import CrmIndex, dedupe_people, fetch_hubspot
from engine.util import company_key, read_csv, write_csv

HERE = os.path.dirname(os.path.abspath(__file__))
EXAMPLES = os.path.join(HERE, "examples")
OUT = os.path.join(HERE, "out")

COMPANY_COLS = ["verdict", "reasons", "company", "website", "domain", "country", "vertical",
                "headcount", "runs_call_centre", "qa_evidence", "qa_tool", "pain", "bilingual",
                "fact", "fact_source", "source"]
LEAD_COLS = ["score", "route", "tier", "persona", "full_name", "job_title", "company",
             "vertical", "city", "phone", "phone_type", "phone_src", "linkedin_url",
             "opener", "opener_status", "verify"]


# ------------------------------------------------------------------ shared steps
def qualify_companies(companies, markets, crm):
    for c in companies:
        c["verdict"], reasons = qualify.gate(c, markets, crm)
        c["reasons"] = "; ".join(reasons)
    keep = [c for c in companies if c["verdict"] != "DISQUALIFY"]
    return keep, Counter(c["verdict"] for c in companies)


def finish(with_phone, companies):
    """Score every contact, write its opener, sort best first."""
    by_key = {company_key(c["company"]): c for c in companies}
    for p in with_phone:
        co = by_key.get(company_key(p.get("company")), {})
        p["vertical"] = co.get("vertical", "")
        qualify.score_contact(p, co)
        p["opener"], p["opener_status"] = openers.opener(p, co)
    with_phone.sort(key=lambda p: (-p["score"], p.get("company", "")))
    return with_phone


def enrich(companies, market, crm, primary, fallback, spend, pool=None):
    pool = pool if pool is not None else people.search_prospeo(companies, market)
    picked, gaps = people.select(pool)
    fresh, crm_skipped = dedupe_people(picked, crm)
    with_phone, dropped, stats = phones.waterfall(fresh, market, primary, fallback, spend)
    stats["crm_skipped"] = crm_skipped
    return finish(with_phone, companies), dropped, gaps, stats, len(pool)


def print_summary(leads, dropped, gaps, stats, pool_size):
    print("  people in pool: %d" % pool_size)
    print("  skipped, already in the CRM: %d" % stats["crm_skipped"])
    print("  numbers: on record %d, prospeo %d, fallback %d, rejected format %d, none %d"
          % (stats["on_record"], stats["revealed"], stats["fallback_hits"],
             stats["rejected_format"], stats["no_number"]))
    print("  dropped for no valid phone: %d" % len(dropped))
    for d in dropped:
        print("     - %s (%s): %s" % (d["full_name"], d["company"], d.get("phone_note", "")))
    if gaps:
        print("  roles still missing (find by hand):")
        for co, m in gaps.items():
            print("     - %s: %s" % (co, ", ".join(m)))
    uniq, rep, dash = openers.pack_report([l["opener"] for l in leads])
    print("  openers: %d unique facts, most repeated body %d, em-dashes %d, needs check %d"
          % (uniq, rep, dash, sum(l["opener_status"] != "ok" for l in leads)))
    print("  tiers %s, routes %s" % (dict(Counter(l["tier"] for l in leads)),
                                      dict(Counter(l["route"] for l in leads))))


# ------------------------------------------------------------------ sample mode
class SampleNumbers:
    """Stands in for Prospeo and the fallback. Reads what each provider 'would' return
    from the sample people file, so the whole waterfall runs with no network."""
    CREDITS_PER_REVEAL = 10

    def status(self, p):
        full = p.get("prospeo_mobile") or ""
        return (full[:-4] + "****") if full else None

    def reveal(self, p):
        return p.get("prospeo_mobile")

    def find(self, group):
        return {i: p["fallback_mobile"] for i, p in enumerate(group) if p.get("fallback_mobile")}


def cmd_sample(args):
    print("SAMPLE RUN: examples/ only, no network, no keys, nothing spent.\n")
    crm = CrmIndex.load(os.path.join(EXAMPLES, "sample_crm.csv"))
    companies = discover.merge(discover.from_accounts(
        os.path.join(EXAMPLES, "sample_companies.csv")))
    kept, verdicts = qualify_companies(companies, set(discover_markets(args)), crm)
    print("1. qualify: %d companies -> %s" % (len(companies), dict(verdicts)))
    for c in companies:
        print("     %-11s %-28s %s" % (c["verdict"], c["company"], c["reasons"]))

    kept_keys = {company_key(c["company"]) for c in kept}
    pool = [dict(p) for p in read_csv(os.path.join(EXAMPLES, "sample_people.csv"))
            if company_key(p["company"]) in kept_keys]
    sn = SampleNumbers()
    leads, dropped, gaps, stats, n = enrich(kept, args.market, crm, sn, sn, True, pool=pool)
    print("\n2. people, 3. dedupe, 4. phone waterfall")
    print_summary(leads, dropped, gaps, stats, n)

    out = os.path.join(OUT, "sample_leads.csv")
    write_csv(out, leads, LEAD_COLS)
    write_csv(os.path.join(OUT, "sample_companies_scored.csv"), companies, COMPANY_COLS)
    print("\n5. ranked leads (%d), written to %s" % (len(leads), os.path.relpath(out, HERE)))
    for l in leads:
        print("  %3d %s  %-18s %-30s %-30s %s" % (l["score"], l["route"], l["full_name"],
                                                  l["job_title"][:30], l["company"][:30],
                                                  l["phone"]))
    if leads:
        print("\nopener for the top lead:\n  %s" % leads[0]["opener"])
    return 0


def discover_markets(args):
    return [m.strip().upper() for m in (args.markets or args.market).split(",")]


# ------------------------------------------------------------------ live commands
def cmd_discover(args):
    crm = CrmIndex.load(args.crm)
    lanes = []
    if args.accounts:
        lanes.append(discover.from_accounts(args.accounts))
    if args.prospeo:
        lanes.append(discover.from_prospeo(args.market, args.max_pages, estimate=args.estimate))
    if args.hiring:
        lanes.append(discover.from_hiring(args.hiring))
    if not lanes:
        sys.exit("Give at least one lane: --accounts, --prospeo or --hiring.")
    companies = discover.merge(*lanes)
    for c in companies:
        c.setdefault("country", args.market)
    kept, verdicts = qualify_companies(companies, set(discover_markets(args)), crm)
    write_csv(args.out, companies, COMPANY_COLS)
    print("%d companies -> %s. Wrote the full scorecard to %s" % (len(companies),
                                                                   dict(verdicts), args.out))
    print("DISQUALIFY rows stay in the scorecard for the record; enrich skips them.")


def cmd_enrich(args):
    crm = CrmIndex.load(args.crm)
    companies = [c for c in read_csv(args.companies) if c.get("verdict") != "DISQUALIFY"]
    primary, fallback = phones.Prospeo(), phones.BetterContact()
    leads, dropped, gaps, stats, n = enrich(companies, args.market, crm, primary, fallback,
                                            args.spend)
    if not args.spend:
        print("PRICE CHECK ONLY. %d numbers ready to reveal = %d Prospeo credits."
              % (stats["reveal_ready"], stats["credits_needed"]))
        print("Nothing spent. Re-run with --spend once the cost is approved.")
        return
    write_csv(args.out, leads, LEAD_COLS)
    print_summary(leads, dropped, gaps, stats, n)
    print("wrote %d phone-verified leads to %s" % (len(leads), args.out))


def cmd_verify(args):
    from engine import verify
    leads = read_csv(args.leads)
    todo = [r for r in leads if "/in/" in (r.get("linkedin_url") or "")
            and not (r.get("verify") or "").startswith("STILL HERE")]
    profiles = verify.scrape([r["linkedin_url"] for r in todo])
    checked, left = verify.check(todo, profiles)
    rest = [r for r in leads if r not in todo]
    kept = rest + checked
    print("checked %d: %d still here, %d left" % (len(todo), len(checked), len(left)))
    for r in left:
        print("  LEFT %s (%s) %s" % (r["full_name"], r["company"], r["verify"]))
    if left and args.replace:
        companies = [c for c in read_csv(args.companies)
                     if company_key(c["company"]) in {company_key(r["company"]) for r in left}]
        crm = CrmIndex.load(args.crm)
        # leavers and people we already have must not come back as their own replacement
        crm = _with_known(crm, leads)
        new, _, _, _, _ = enrich(companies, args.market, crm, phones.Prospeo(),
                                 phones.BetterContact(), True)
        print("  replacements found: %d" % len(new))
        kept += new
    write_csv(args.leads, kept, LEAD_COLS)
    print("CHANGED=%d" % (1 if left or checked else 0))


def _with_known(crm, rows):
    from engine.util import linkedin_slug, person_key
    for r in rows:
        s = linkedin_slug(r.get("linkedin_url"))
        if s:
            crm.slugs.add(s)
        crm.name_at.add((person_key(r.get("full_name")), company_key(r.get("company"))))
    return crm


def cmd_digest(args):
    from engine import digest
    digest.build(args.leads, args.snapshot, args.out_dir)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sample", "--dry-run", dest="sample", action="store_true",
                    help="offline run on examples/, no network")
    ap.add_argument("--market", default="CA", help="market code, e.g. CA or DE")
    ap.add_argument("--markets", help="comma list of markets in scope (default: --market)")
    ap.add_argument("--crm", default=os.path.join(HERE, "crm_cache.json"))
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("crm-fetch", help="pull HubSpot contacts + companies into the cache")

    d = sub.add_parser("discover", help="run the discovery lanes and the company gate")
    d.add_argument("--accounts", help="researched account list CSV")
    d.add_argument("--prospeo", action="store_true", help="Prospeo company search lane")
    d.add_argument("--estimate", action="store_true", help="Prospeo: page 1 only, read counts")
    d.add_argument("--max-pages", type=int, default=2)
    d.add_argument("--hiring", help="job posts CSV or JSONL for the hiring lane")
    d.add_argument("--out", default=os.path.join(OUT, "companies.csv"))

    e = sub.add_parser("enrich", help="people, numbers, score, openers")
    e.add_argument("--companies", default=os.path.join(OUT, "companies.csv"))
    e.add_argument("--spend", action="store_true", help="actually pay for reveals")
    e.add_argument("--out", default=os.path.join(OUT, "leads.csv"))

    v = sub.add_parser("verify", help="works-here check on every lead")
    v.add_argument("--leads", default=os.path.join(OUT, "leads.csv"))
    v.add_argument("--companies", default=os.path.join(OUT, "companies.csv"))
    v.add_argument("--replace", action="store_true", help="find someone new for each leaver")

    g = sub.add_parser("digest", help="write today's new leads")
    g.add_argument("--leads", default=os.path.join(OUT, "leads.csv"))
    g.add_argument("--snapshot", default=os.path.join(OUT, "last_digest.txt"))
    g.add_argument("--out-dir", default=OUT)

    args = ap.parse_args(argv)
    if args.sample:
        return cmd_sample(args)
    if args.cmd == "crm-fetch":
        fetch_hubspot(args.crm)
    elif args.cmd == "discover":
        cmd_discover(args)
    elif args.cmd == "enrich":
        cmd_enrich(args)
    elif args.cmd == "verify":
        cmd_verify(args)
    elif args.cmd == "digest":
        cmd_digest(args)
    else:
        ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())

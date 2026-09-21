"""Dedupe against the client's CRM (HubSpot), at company and at person level.

`fetch_hubspot()` pages through every contact and company with the list endpoint (the
search endpoint stops at 10k) and writes a local cache. Read-only: it never writes to HubSpot.
Every later step loads the cache through CrmIndex, so a full run costs one CRM pull.

A person counts as already in the CRM when any of these match:
  - email
  - LinkedIn profile slug
  - full name (accent-insensitive) at the same company, or anywhere if the CRM row has no company
"""
import json
import os
import sys
import time

from .http import get_json
from .util import company_key, domain_of, linkedin_slug, person_key, read_csv

HUBSPOT = "https://api.hubapi.com/crm/v3/objects"


def _pages(obj, props, token):
    after = None
    while True:
        url = "%s/%s?limit=100&properties=%s" % (HUBSPOT, obj, ",".join(props))
        if after:
            url += "&after=%s" % after
        d = get_json(url, headers={"Authorization": "Bearer %s" % token})
        for r in d.get("results", []):
            yield r.get("properties") or {}
        after = ((d.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            return
        time.sleep(0.08)


def fetch_hubspot(cache_path):
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("Set HUBSPOT_TOKEN first (a read-only private app token is enough).")
    contacts = []
    for p in _pages("contacts", ["email", "firstname", "lastname", "company",
                                 "hs_linkedin_url", "linkedinurl"], token):
        contacts.append({
            "email": (p.get("email") or "").strip().lower(),
            "full_name": "%s %s" % (p.get("firstname") or "", p.get("lastname") or ""),
            "company": p.get("company") or "",
            "linkedin_url": p.get("hs_linkedin_url") or p.get("linkedinurl") or "",
        })
    companies = [{"company": p.get("name") or "", "domain": p.get("domain") or ""}
                 for p in _pages("companies", ["name", "domain"], token)]
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump({"contacts": contacts, "companies": companies}, fh)
    print("CRM cache: %d contacts, %d companies -> %s" % (len(contacts), len(companies),
                                                           cache_path))
    return cache_path


class CrmIndex:
    def __init__(self, contacts=(), companies=()):
        self.emails, self.slugs, self.names, self.name_at = set(), set(), set(), set()
        self.co_keys, self.domains = set(), set()
        for c in contacts:
            if c.get("email"):
                self.emails.add(c["email"].strip().lower())
            s = linkedin_slug(c.get("linkedin_url"))
            if s:
                self.slugs.add(s)
            n = person_key(c.get("full_name"))
            if n:
                ck = company_key(c.get("company"))
                if ck:
                    self.name_at.add((n, ck))
                else:
                    self.names.add(n)
        for c in companies:
            if company_key(c.get("company")):
                self.co_keys.add(company_key(c["company"]))
            if domain_of(c.get("domain")):
                self.domains.add(domain_of(c["domain"]))

    @classmethod
    def load(cls, path):
        """A JSON cache from fetch_hubspot(), or a CSV export with full_name, company,
        email, linkedin_url columns (company-only rows mark the company as known)."""
        if not path or not os.path.exists(path):
            print("  no CRM cache found, CRM dedupe is OFF", file=sys.stderr)
            return cls()
        if path.endswith(".json"):
            with open(path, encoding="utf-8") as fh:
                d = json.load(fh)
            return cls(d.get("contacts", []), d.get("companies", []))
        rows = read_csv(path)
        return cls([r for r in rows if r.get("full_name")],
                   [r for r in rows if r.get("company") and not r.get("full_name")])

    def has_company(self, company):
        return (company_key(company.get("company")) in self.co_keys
                or (domain_of(company.get("website") or company.get("domain"))
                    in self.domains - {""}))

    def has_person(self, p):
        if (p.get("email") or "").strip().lower() in self.emails - {""}:
            return True
        if linkedin_slug(p.get("linkedin_url")) in self.slugs - {""}:
            return True
        n = person_key(p.get("full_name"))
        return bool(n) and (n in self.names or (n, company_key(p.get("company"))) in self.name_at)


def dedupe_people(people, crm):
    """Drop people already in the CRM and repeats inside the batch itself."""
    out, seen, skipped = [], set(), 0
    for p in people:
        k = linkedin_slug(p.get("linkedin_url")) or (person_key(p.get("full_name")),
                                                    company_key(p.get("company")))
        if k in seen:
            continue
        seen.add(k)
        if crm.has_person(p):
            skipped += 1
            continue
        out.append(p)
    return out, skipped

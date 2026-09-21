"""The number waterfall. Cheapest source first, and nothing ships without a valid number.

  1. number already on the record         free, just validated
  2. Prospeo status lookup                 free, returns a masked mobile + VERIFIED flag
  3. check the masked number's format      free, BEFORE paying (a +92 number on a Canadian
                                           director is a bad match, not a lead)
  4. Prospeo reveal                        paid, only for masked numbers that passed step 3
  5. fallback provider (BetterContact)     paid only on a hit, for everyone still missing
  6. validate again                        whatever comes back must pass the market rule

A contact that falls out of the bottom has no phone and is dropped. Phone-verified or out.
"""
import os
import re
import sys
import time
import urllib.parse

from . import config
from .http import get_json, post_json

# ------------------------------------------------------------------ validation
# NANP area codes in use in Canada, and the toll-free ones we never accept.
CA_AREA = set(
    "204 226 236 249 250 263 289 306 343 354 365 367 368 382 403 416 418 428 431 437 438 450"
    " 468 474 506 514 519 548 579 581 584 587 604 613 639 647 672 683 705 709 742 753 778"
    " 780 782 807 819 825 867 873 879 902 905".split())
TOLL_FREE = {"800", "833", "844", "855", "866", "877", "888"}

# German mobiles are 15x / 16x / 17x after the country code. A city landline is a
# switchboard, not the direct line the client asked for.
DE_MOBILE = re.compile(r"^49(15\d|16\d|17\d)")
DE_BAD = re.compile(r"^49(800|180|900)")          # toll-free and premium-rate


def to_e164_digits(phone, market):
    """Digits only, with the country code in front. Masked digits (*) are kept."""
    p = re.sub(r"[^\d*+]", "", phone or "")
    dial = config.MARKETS[market]["dial"]
    if p.startswith("+"):
        return p[1:]
    if p.startswith("00"):
        return p[2:]
    if market == "CA" and len(p) == 10:
        return "1" + p
    if p.startswith("0"):
        return dial + p[1:]
    return p


def validate(phone, market):
    """Return (ok, phone_type, reason). phone_type is mobile, direct or switchboard."""
    d = to_e164_digits(phone, market)
    if not d:
        return False, "", "empty"
    dial = config.MARKETS[market]["dial"]
    if not d.startswith(dial):
        return False, "", "foreign number (+%s)" % d[:3]
    if market == "CA":
        area = d[1:4]
        if area in TOLL_FREE:
            return False, "", "toll-free %s" % area
        if area not in CA_AREA:
            return False, "", "not a Canadian area code (%s)" % area
        # NANP numbers do not say whether they are mobile; the provider flag decides that.
        return True, "direct", "ok"
    if market == "DE":
        if DE_BAD.match(d):
            return False, "", "toll-free or premium-rate"
        if not DE_MOBILE.match(d):
            return False, "switchboard", "landline, not a direct mobile"
        return True, "mobile", "ok"
    return True, "direct", "country code ok, format not checked for %s" % market


# ------------------------------------------------------------------ providers
class Prospeo:
    URL = "https://api.prospeo.io/enrich-person"
    CREDITS_PER_REVEAL = 10

    def __init__(self):
        self.key = os.environ.get("PROSPEO_API_KEY")
        if not self.key:
            sys.exit("Set PROSPEO_API_KEY first.")

    def _mobile(self, body):
        r = post_json(self.URL, body, headers={"X-KEY": self.key}, pause=0.5)
        person = (r.get("response") or r).get("person") or {}
        return person.get("mobile") or {}

    def status(self, person):
        """Free. Masked number if Prospeo holds a VERIFIED mobile, else None."""
        if "/in/" not in (person.get("linkedin_url") or ""):
            return None
        m = self._mobile({"data": {"linkedin_url": person["linkedin_url"]}})
        if m.get("status") == "VERIFIED":
            return m.get("mobile_international") or m.get("mobile")
        return None

    def reveal(self, person):
        """Paid. The full number."""
        m = self._mobile({"enrich_mobile": True, "only_verified_mobile": True,
                          "data": {"linkedin_url": person["linkedin_url"]}})
        return m.get("mobile_international") or m.get("mobile")


class BetterContact:
    """Async API: submit everyone, wait, then collect. Charged only when it finds a number."""
    BASE = "https://app.bettercontact.rocks/api/v2/async"

    def __init__(self):
        self.key = os.environ.get("BETTERCONTACT_API_KEY")

    def find(self, people):
        if not self.key:
            print("  BETTERCONTACT_API_KEY not set, skipping the fallback.", file=sys.stderr)
            return {}
        q = "?" + urllib.parse.urlencode({"api_key": self.key})
        ids = {}
        for i, x in enumerate(people):
            w = (x.get("full_name") or "").split()
            li = x.get("linkedin_url") or ""
            body = {"data": [{"first_name": w[0] if w else "", "last_name": w[-1] if w else "",
                              "company": x.get("company", ""),
                              "linkedin_url": li if "/in/" in li else "", "custom_fields": {}}],
                    "enrich_email_address": False, "enrich_phone_number": True}
            rid = post_json(self.BASE + q, body, pause=0.7).get("id")
            if rid:
                ids[i] = rid
        if ids:
            time.sleep(40)
        found = {}
        for i, rid in ids.items():
            for _ in range(10):
                r = get_json("%s/%s%s" % (self.BASE, rid, q))
                if r.get("status") == "terminated":
                    ph = ((r.get("data") or [{}])[0]).get("contact_phone_number")
                    if ph:
                        found[i] = ph
                    break
                time.sleep(10)
        return found


# ------------------------------------------------------------------ the waterfall
def waterfall(people, market, primary, fallback, spend=False):
    """Fill `phone`, `phone_type` and `phone_src` on each person that gets a valid number.

    spend=False prices the job: steps 1-3 run (they are free), nothing is revealed.
    Returns (with_phone, dropped, stats)."""
    stats = {"on_record": 0, "reveal_ready": 0, "revealed": 0, "fallback_hits": 0,
             "rejected_format": 0, "no_number": 0, "credits_needed": 0}
    kept, to_reveal, to_fallback = [], [], []

    for x in people:
        ok, ptype, _ = validate(x.get("phone"), market) if x.get("phone") else (False, "", "")
        if ok:                                            # 1. already have it
            x.update(phone_type=ptype, phone_src=x.get("phone_src") or "record")
            stats["on_record"] += 1
            kept.append(x)
            continue
        masked = primary.status(x)                        # 2. free status
        if masked:
            ok, _, why = validate(masked, market)         # 3. check before paying
            if ok:
                to_reveal.append(x)
                continue
            stats["rejected_format"] += 1
            x["phone_note"] = "masked number rejected: %s" % why
        to_fallback.append(x)

    stats["reveal_ready"] = len(to_reveal)
    stats["credits_needed"] = len(to_reveal) * getattr(primary, "CREDITS_PER_REVEAL", 0)
    if not spend:
        return kept, [], stats

    for x in to_reveal:                                   # 4. paid reveal
        full = primary.reveal(x)
        ok, ptype, why = validate(full, market)
        if ok:
            # the provider only returns VERIFIED mobiles here, so a NANP number counts as one
            x.update(phone=full, phone_type="mobile" if ptype == "direct" else ptype,
                     phone_src="prospeo")
            stats["revealed"] += 1
            kept.append(x)
        else:
            to_fallback.append(x)

    found = fallback.find(to_fallback)                    # 5. fallback, pay on hit
    dropped = []
    for i, x in enumerate(to_fallback):
        ph = found.get(i)
        ok, ptype, why = validate(ph, market) if ph else (False, "", "no number found")
        if ok:                                            # 6. validate again
            x.update(phone=ph, phone_type=ptype, phone_src="fallback")
            stats["fallback_hits"] += 1
            kept.append(x)
        else:
            x["phone_note"] = x.get("phone_note") or why
            stats["no_number"] += 1
            dropped.append(x)
    return kept, dropped, stats

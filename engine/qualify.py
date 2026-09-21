"""The ICP, enforced in code.

Two parts:
  gate()          company level: QUALIFIED / REVIEW / DISQUALIFY with the reasons.
                  DISQUALIFY is deleted, the other two go on to the people step.
  score_contact() contact level: the 100-point matrix that ranks the final list.

The rule behind both: never guess. A field nobody could confirm is "unclear", which
lands the company in REVIEW, never in QUALIFIED.
"""
from . import config
from .util import headcount_mid


def _yes(v):
    return str(v or "").strip().lower() in {"yes", "y", "true", "1"}


def _no(v):
    return str(v or "").strip().lower() in {"no", "n", "false", "0"}


def gate(company, markets=None, crm_companies=None):
    """Return (verdict, reasons). `markets` is the set of market codes in scope;
    `crm_companies` is a dedupe.CrmIndex, used to keep only net-new companies."""
    cut, review = [], []

    country = (company.get("country") or "").upper()
    if markets and country and country not in markets:
        cut.append("market %s not in scope" % country)

    if _no(company.get("runs_call_centre")):
        cut.append("no real phone floor")
    elif not _yes(company.get("runs_call_centre")):
        review.append("phone floor not confirmed")

    size = headcount_mid(company.get("headcount"))
    if size is None:
        review.append("headcount unknown")
    elif size < config.HEADCOUNT_MIN:
        cut.append("headcount %d under %d" % (size, config.HEADCOUNT_MIN))
    elif size > config.HEADCOUNT_MAX:
        cut.append("headcount %d over %d (enterprise)" % (size, config.HEADCOUNT_MAX))

    vertical = " ".join(str(company.get(k) or "") for k in ("vertical", "prospeo_industry"))
    if config.BANNED_VERTICAL.search(vertical):
        cut.append("vertical ruled out: %s" % vertical.strip())

    if config.QA_TOOLS.search(str(company.get("qa_tool") or "")):
        review.append("already runs %s" % company["qa_tool"])

    if not _yes(company.get("qa_evidence")) and not company.get("pain"):
        review.append("no QA function or pain signal found yet")

    if crm_companies is not None and crm_companies.has_company(company):
        cut.append("already in the CRM, not net-new")

    if cut:
        return "DISQUALIFY", cut
    if review:
        return "REVIEW", review
    return "QUALIFIED", ["phone floor, in-band size, pain signal"]


def vertical_points(text):
    for rx, pts in config.VERTICAL_POINTS:
        if rx.search(text or ""):
            return pts
    return config.VERTICAL_DEFAULT


def pain_points(company):
    """15 = named manual-QA / QA hiring, 8 = regulated but unconfirmed, 4 = inferred."""
    if _yes(company.get("qa_evidence")):
        return 15
    if company.get("pain"):
        return 8
    return 4


def score_contact(contact, company):
    """The 100-point matrix. Phone is 30 of it, and a contact with 0 there never ships.

      phone        30  verified mobile/direct 30, switchboard 8, none 0 (dropped)
      seniority    25  tier A 25, B 20, C 8
      vertical     20  collections / BPO 20, insurance and research 15, lending 10
      pain         15  named QA pain 15, regulated-unconfirmed 8, inferred 4
      reach        10  LinkedIn profile 5, bilingual fit 5
    """
    phone = contact.get("phone_type")
    pts_phone = 30 if phone in ("mobile", "direct") else 8 if phone == "switchboard" else 0
    pts_sen = {"A": 25, "B": 20}.get(contact.get("tier"), 8)
    pts_vert = vertical_points(company.get("vertical") or company.get("prospeo_industry"))
    pts_pain = pain_points(company)
    pts_reach = (5 if "/in/" in (contact.get("linkedin_url") or "") else 0) + \
                (5 if _yes(company.get("bilingual")) else 0)
    total = pts_phone + pts_sen + pts_vert + pts_pain + pts_reach
    contact["score"] = total
    contact["route"] = "A" if total >= 80 else "B" if total >= 60 else "C"
    return total

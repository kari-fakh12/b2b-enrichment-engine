"""The personal LinkedIn opener, one per contact.

Rules:
  - The first sentence is one checkable fact about that company, and the fact has to come
    with its source (a URL or a named document). No fact or no source means the row is
    marked "needs check" and gets no opener. We never fill the gap with a made-up line.
  - The angle depends on the persona. A pain-feeler hears coverage and coaching (their
    workload). A decision-maker hears risk (their exposure).
  - Only claim what the product actually does. No invented features or numbers.
  - No em-dashes. The first batch of openers that read like a template got called out,
    so the pack is checked for repeated bodies too.
"""
import re
import zlib
from collections import Counter

NEEDS_CHECK = "needs check"

CLOSE = [
    "Open to 10 minutes on it?",
    "Worth 10 minutes to see it score a batch of your own calls?",
    "Happy to show you what it would look like on your own calls. Open to 10 minutes?",
]

BODY_PAIN = ("As %s you own call quality, and a person can only get through so many calls by "
             "hand. Our tool scores 100 percent of them automatically, so your team spends its "
             "time coaching on the flagged calls instead of choosing which ones to listen to.")
BODY_DM = ("You are expected to stand behind those calls, but a QA team can only hand-sample a "
           "fraction of them. Our tool scores 100 percent automatically for quality and "
           "compliance, so the risk does not sit in the calls nobody hears.")


def first_name(person):
    parts = [p for p in (person.get("full_name") or "").split()
             if not re.match(r"^(dr|prof|dipl|mr|mrs|ms)\.?$", p, re.I)]
    return (person.get("first_name") or (parts[0] if parts else "")).strip()


def opener(person, company):
    """Return (message, status). status is 'ok' or 'needs check: <why>'."""
    fact = (company.get("fact") or "").strip().rstrip(".")
    source = (company.get("fact_source") or "").strip()
    if not fact:
        return "", NEEDS_CHECK + ": no checkable fact for this company"
    if not source:
        return "", NEEDS_CHECK + ": fact has no source"
    name = first_name(person)
    if not name:
        return "", NEEDS_CHECK + ": no first name"
    if person.get("persona") == "pain-feeler":
        body = BODY_PAIN % person.get("job_title", "the owner of the floor")
    else:
        body = BODY_DM
    # crc32, not hash(): Python salts str hashes per run, which made the close change
    # between runs. This keeps the same person on the same close every time.
    close = CLOSE[zlib.crc32((person.get("full_name") or "").encode()) % len(CLOSE)]
    msg = "Hi %s, %s. %s %s" % (name, fact, body, close)
    msg = msg.replace("—", ",").replace("–", "-")
    return msg, "ok"


def pack_report(messages):
    """How template-like is the pack? Returns (unique_facts, most_repeated_body, em_dashes)."""
    msgs = [m for m in messages if m]
    if not msgs:
        return 0, 0, 0
    facts = {m.split(". ")[0] for m in msgs}
    bodies = Counter(m.split(". ", 1)[-1] for m in msgs)
    return len(facts), bodies.most_common(1)[0][1], sum("—" in m for m in msgs)

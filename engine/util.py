"""Normalising and file helpers. Every step keys companies and people the same way."""
import csv
import os
import re
import unicodedata

UMLAUT = [("ä", "a"), ("ö", "o"), ("ü", "u"), ("ß", "ss"), ("ae", "a"), ("oe", "o"), ("ue", "u")]
LEGAL = re.compile(
    r"\b(gmbh|ag|kg|mbh|co|se|e\.?v\.?|b\.?v\.?|ltd|limited|inc|llc|corp|corporation|plc"
    r"|group|gruppe|holdings?|the|niederlassung)\b")


def domain_of(url):
    """Registrable domain. careers.example.com and example.com are the same company."""
    d = re.sub(r"^https?://", "", (url or "").strip().lower()).split("/")[0]
    d = d[4:] if d.startswith("www.") else d
    parts = [p for p in d.split(".") if p]
    if ".".join(parts[-2:]) in {"example.com", "example.org", "example.net"}:
        return d                              # sample data: each subdomain is its own fake company
    if len(parts) > 2 and parts[-2] in {"co", "com", "org", "net", "gov", "ac"}:
        return ".".join(parts[-3:])          # example.co.uk
    return ".".join(parts[-2:]) if len(parts) > 2 else d


def company_key(name):
    """Collapse the name variants of one company to one key."""
    n = (name or "").lower()
    n = re.sub(r"\(.*?\)", " ", n)
    for a, b in UMLAUT:
        n = n.replace(a, b)
    n = LEGAL.sub(" ", n)
    return re.sub(r"[^a-z0-9]+", "", n)


def person_key(full_name):
    """Accent-insensitive, punctuation-free name."""
    s = unicodedata.normalize("NFKD", str(full_name or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", s.lower())


def linkedin_slug(url):
    m = re.search(r"/in/([^/?#]+)", url or "")
    return m.group(1).lower() if m else ""


def headcount_mid(value):
    """'51-200' -> 125.5, '300' -> 300, '' -> None."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(value or "").replace(",", ""))]
    if not nums:
        return None
    return sum(nums[:2]) / len(nums[:2])


def read_csv(path):
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, rows, cols):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})

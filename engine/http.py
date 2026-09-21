"""Small HTTP helpers shared by every provider call. Standard library only."""
import json
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (enrichment-engine)"   # some providers 403 a request with no user agent


def post_json(url, body, headers=None, retries=5, timeout=60, pause=0.0):
    """POST JSON, back off on 429, return the decoded body (also for 4xx errors)."""
    h = {"Content-Type": "application/json", "User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers=h)
    for attempt in range(retries + 1):
        if pause:
            time.sleep(pause)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                wait = min(2 * (2 ** attempt), 60)
                print("  429 rate-limited, waiting %ds" % wait, file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 401:
                sys.exit("ERROR 401: the API key for %s is wrong." % url.split("/")[2])
            if e.code == 402:
                sys.exit("ERROR 402: out of credits at %s." % url.split("/")[2])
            try:
                return json.loads(e.read().decode() or "{}")
            except ValueError:
                return {"error": True, "status": e.code}
    return {"error": True, "status": 429}


def get_json(url, headers=None, retries=5, timeout=60):
    h = {"User-Agent": UA}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            raise
    raise SystemExit("too many 429s from %s" % url.split("/")[2])

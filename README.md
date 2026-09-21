# b2b-enrichment-engine

The lead engine I built for a client that sells AI call-QA software to contact centres, and they sell by phone, so a lead with no phone number is no use to them. They needed senior people at the right call centres in Canada and eight European markets, each with a number they could dial and a first message worth reading.

## How it works

1. **Discover.** Three lanes find candidate companies: a researched account list, a Prospeo company search on website text and industry codes, and companies hiring for call-QA jobs.
2. **Qualify.** All three lanes go through one gate that enforces the ICP in code: a real phone floor, 50 to 1,500 staff, a vertical that fits, a sign of QA pain. Companies already in the client's HubSpot are cut, so only net-new companies ship.
3. **Find the people.** Per company, one decision-maker and one person who owns call quality, most senior first. Managers only fill a gap. HR, legal, creative and engineering titles are dropped however senior they sound.
4. **Dedupe.** Person-level check against the client's HubSpot by email, LinkedIn profile and name.
5. **Get the number.** Cheapest source first: the number on record, then a free Prospeo status check, then a format check before paying for anything, then the paid reveal, then BetterContact for whoever is left. Every number is checked against the market's rules.
6. **Score.** The 100-point ICP matrix: phone 30, seniority 25, vertical 20, pain 15, reach 10.
7. **Write the opener.** Each contact gets a personal LinkedIn opener built on a checkable fact about their company, with the angle picked by role.
8. **Re-check and send.** In CI, a works-here check scrapes each profile and replaces anyone who has left. A daily GitHub Action emails the new leads.

## The rules

- **Phone-verified or out.** No valid number, the contact does not ship.
- **Most senior first.** C-level and Head-of before managers.
- **No fabrication.** Every fact traces to a source. If it can't be confirmed it's marked "needs check" and gets no opener. Nothing is filled in with a guess.

## Results

481 senior contacts at 308 companies, 208 of them with a verified mobile. The client booked 55 calls and closed 25 deals from the list.

## Run the sample

No keys, no network, nothing spent:

```bash
python3 run.py --sample
```

It runs five made-up companies from `examples/` through the gate, picks the people, runs the phone waterfall against a fake provider, dedupes against a fake CRM and prints the ranked list. Python 3.8+, standard library only.

The real run, step by step, is in [RUNBOOK.md](RUNBOOK.md).

## Env vars

Copy `.env.example` and fill in what you need. Keys are only ever read from the environment.

| Var | Used for |
|---|---|
| `PROSPEO_API_KEY` | company search, people search, mobile lookup and reveal |
| `BETTERCONTACT_API_KEY` | phone fallback for people Prospeo has no number for |
| `HUBSPOT_TOKEN` | read-only CRM pull for dedupe |
| `APIFY_TOKEN` | works-here check on LinkedIn profiles |
| `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_TO` | daily email (GitHub secrets, not local) |

## Layout

```
run.py              command line
engine/config.py    titles, tiers, size limits, verticals: the ICP in one file
engine/discover.py  the three discovery lanes
engine/qualify.py   company gate and the 100-point contact score
engine/people.py    decision-maker finder and seniority rank
engine/dedupe.py    HubSpot pull and CRM dedupe
engine/phones.py    the number waterfall and per-market number checks
engine/openers.py   LinkedIn opener, with the no-fact-no-opener rule
engine/verify.py    works-here check
engine/digest.py    daily new-leads file
```

MIT license.

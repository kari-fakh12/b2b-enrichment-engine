# Runbook

For whoever is running the engine, technical or not. Read it once top to bottom, then follow the steps.

## 1. What you are building

A list of senior decision-makers at call and contact centres, every one with a phone number. The client sells call-QA software and dials people, so:

- **Every contact must have a phone number.** A row with no phone is useless to them. The engine drops it.
- **Most senior people first.** C-level, Head-of, Director. Managers only to fill.
- **Only the markets in scope** for this batch (`--market`, or `--markets CA,DE`).
- Bilingual accounts (for example French and English in Canada) are a bonus. Mark them `yes` in the `bilingual` column.

## 2. One-time setup

1. Install Python 3.8 or newer. Check with `python3 --version`. Nothing else to install.
2. Get the keys from whoever owns the accounts: Prospeo (Settings > API), BetterContact, a read-only HubSpot private app token, and Apify if you run the works-here check.
3. Put them in your terminal, never in a file you commit:
   ```bash
   export PROSPEO_API_KEY="..."
   export BETTERCONTACT_API_KEY="..."
   export HUBSPOT_TOKEN="..."
   ```
   Run this in every new terminal, or copy `.env.example` to `.env` and load it. `.env` is gitignored.
4. Try the sample first so you know what good output looks like:
   ```bash
   python3 run.py --sample
   ```

## 3. Run it

**Step A. Pull the CRM cache** (read-only, once per day is enough):
```bash
python3 run.py crm-fetch
```

**Step B. Find and qualify companies.** Use any of the three lanes, or all of them:
```bash
python3 run.py --market CA discover --accounts my-accounts.csv
python3 run.py --market CA discover --prospeo --estimate      # reads counts only
python3 run.py --market CA discover --prospeo --max-pages 2   # 1 credit per page of 25
python3 run.py --market CA discover --hiring job-posts.jsonl
```
The account CSV needs `company` and `website`. It helps a lot to also fill `headcount`, `vertical`, `runs_call_centre`, `qa_evidence`, `pain`, `bilingual`, `fact` and `fact_source` (see `examples/sample_companies.csv`).

This writes `out/companies.csv` with a verdict per company:
- `QUALIFIED`: real phone floor, right size, a pain signal. Goes on.
- `REVIEW`: one thing not confirmed. Goes on, but look at the reason.
- `DISQUALIFY`: cut. Too small (under 50), too big (over 1,500), wrong vertical, no phone floor, or already in the CRM.

**Step C. Price the job.** Free. Finds the people and checks who has a number, spends nothing:
```bash
python3 run.py --market CA enrich
```
It prints how many Prospeo credits the reveals would cost. Get the spend approved before the next step.

**Step D. Spend and build the list:**
```bash
python3 run.py --market CA enrich --spend
```
This writes `out/leads.csv`, sorted by score, with the opener for each person.

**Step E. Works-here check** (also runs in CI):
```bash
python3 run.py --market CA verify --replace
```
Anyone who has left is dropped and the engine looks for someone else at that company.

## 4. Quality checks before you hand it over

Open `out/leads.csv` and confirm:
- [ ] The `phone` column is filled on every row. The engine enforces this, but look anyway.
- [ ] Numbers belong to the market. A Canadian lead starts with a Canadian area code, a German mobile with 15x, 16x or 17x. Flag anything else.
- [ ] At least 80% of rows are tier `A` or `B`.
- [ ] No person appears twice (eyeball company plus name).
- [ ] Every row with `opener_status` other than `ok` says why. Those need a real fact with a source before they go out. Do not write one from memory.
- [ ] No em-dashes in any opener.

## 5. How the credits work

- Prospeo search returns 25 results per page and charges 1 credit per page with results.
- The mobile status check is free. The reveal costs 10 credits, and the engine only reveals numbers that already passed the format check.
- BetterContact charges only when it finds a number.
- `--estimate` and the plain `enrich` run (without `--spend`) are there so you see the cost before paying.

## 6. Troubleshooting

| Problem | Fix |
|---|---|
| `Set PROSPEO_API_KEY first` | You skipped setup step 3. Run the export again. |
| `ERROR 401` | Wrong key. Copy it again from the provider's settings. |
| `ERROR 402` | Out of credits. Ask the account owner to top up. |
| `429 rate-limited` | Normal. The engine waits and retries by itself. |
| Few results from the account list | Run the Prospeo or hiring lane too and let the gate sort them. |
| Too many managers | They only fill companies with nobody senior. Add better accounts rather than loosening titles. |
| A company looks wrong | If you are not sure it really runs a call centre, leave it out. |

## 7. Hard rules

- A contact with no phone never ships.
- Every fact in an opener has a source. Unconfirmed means "needs check", never a guess.
- Keys live in environment variables only.
- Ask before spending credits.

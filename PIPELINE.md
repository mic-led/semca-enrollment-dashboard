# SEMCA Dashboard Pipeline — How it actually works

## The two files

- **`SEMCA_Enrollment_Analysis.html`** — the page. Static, hand-maintained, never rewritten by the pipeline.
- **`dashboard-data.js`** — every data-driven value on the page (year totals, chart datasets,
  projections, Data Check anomalies, de-identified raw records, school calendar, and a few HTML
  fragments such as the summary table rows). Written by `semca_analysis.py` on every run and
  loaded by the page's `<head>` before any other script. **Never edit it by hand.**

Before 2026-09-21 the pipeline spliced ~11 marked regions into the HTML; everything outside those
regions had drifted and ~20 charts/tables on the live site were showing months-old numbers.
Moving all data into one generated file fixed that class of bug for good.

## The flow

1. **Cron fires** in GitHub Actions at `0 */3 * * *` UTC (every 3 hours on the hour, UTC)
2. **Workflow checks out two repos**: `semca-enrollment-dashboard` (code + HTML) and `semca-enrollment-data` (private CSV backup) into `./JotForm_Data`
3. **`patch_data.py` runs**, which internally:
   - Calls `jotform_sync.py` → pulls fresh CSVs from JotForm API into `./JotForm_Data` (PII stripped, names/emails/phones hashed with `PII_SALT`)
   - Calls `semca_analysis.py` → computes everything and writes `dashboard-data.js`
4. **Commits updated CSVs** back to the private data repo (always — even if no change)
5. **Commits `dashboard-data.js`** to the dashboard repo (ONLY if it changed)
6. **GitHub Pages auto-deploys** within ~1 min; the page polls the commits API every 10 min and reloads itself

## Adding a new data constant

1. Emit it in the HTML template inside `semca_analysis.py` as `const NAME = {json.dumps(value)};`
2. Add `"NAME"` to `DATA_CONSTS` near the bottom of `semca_analysis.py`
3. Use `NAME` in the page — do **not** declare it there

`semca_analysis.py` still renders its internal HTML template (that is how the constants are
collected in one consistent pass), but that render is only written to disk when
`SEMCA_OUTPUT_PATH` is set, for debugging. It is never deployed.

## Year-over-year cycle (no code changes needed)

- `SCHOOL_CALENDAR` in `semca_analysis.py` holds each school year's dates from SEMCA's official
  calendar PDF. Add a row when the new calendar is published; unpublished years fall back to `CAL_DEFAULTS`.
- `active_cycle_complete` (today ≥ first day of classes) flips the active year from "in progress"
  (projections, live tags) to "complete" (final figures, next-year projection bar/pill) everywhere.
- Year-specific form labels (`Trade/Level for Fall 2027`, `…27/28 School Year?`) are pattern-matched
  in the sync, the analysis and the raw-data allowlist.

## Local preview

```bash
JOTFORM_CSV_DIR=~/Desktop/JotForm_Data python3 semca_analysis.py   # writes ./dashboard-data.js
python3 -m http.server 8767                                          # open SEMCA_Enrollment_Analysis.html
```
Local Desktop CSVs may be stale or unstripped; the raw-data allowlist means no PII reaches the page either way.

## Things that have confused me (and will again)

### "Data as of" timestamp is misleading
- The pill in the corner of the dashboard reads `commit.committer.date` from the GitHub API for the LATEST commit on main
- **It is not the data refresh time.** It's the last commit time — which could be ANY commit (a code change, a config tweak, a manual push)
- If a scheduled run happens but no new applications came in, no HTML commit is made, and the pill keeps showing the previous timestamp
- The displayed time is in the user's browser local timezone but **nothing labels it** — easy to mistake ET for UTC

### Time zones
- GitHub Actions cron is **always UTC** — no way to change this
- Cron schedule `0 */3 * * *` UTC = 0, 3, 6, 9, 12, 15, 18, 21 UTC
- In Eastern Time (UTC-4 in DST): 8 PM, 11 PM, 2 AM, 5 AM, 8 AM, 11 AM, 2 PM, 5 PM ET
- **Scheduled runs are routinely delayed 5-30 minutes** by GitHub due to runner availability — this is documented and unavoidable on free tier

### Counting applications
- `wc -l` on a CSV is wrong — JotForm responses contain newlines inside quoted text fields
- Only `csv.DictReader` gives the real row count
- `len(rows)` in `semca_analysis.py` (load_csv → csv.DictReader) is the source of truth

## Known issues worth fixing

1. ~~Last-sync timestamp should reflect actual sync time~~ — done: `SEMCA_META.syncTime` in `dashboard-data.js` feeds the `data-sync-time` meta tag the pill reads
2. **Display the timezone** — "Data as of 2:24 PM ET" instead of bare "12:24"
3. **The "Classes Begin" line in projections** uses a logistic S-curve, but SEMCA's actual application pattern accelerates at the end (J-curve), not the middle. Logistic weight cap of 60% may be too high.

## Repo layout

- **`mic-led/semca-enrollment-dashboard`** (public) — code, HTML, workflow
- **`mic-led/semca-enrollment-data`** (private) — CSV backup, written by workflow each run
- **GitHub Pages** serves the HTML from main branch of the public repo
- **Squarespace** embeds an iframe pointing to the Pages URL
- **`DATA_REPO_PAT` secret** — classic PAT with `repo` scope, used by workflow to clone/push the private data repo

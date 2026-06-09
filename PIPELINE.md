# SEMCA Dashboard Pipeline — How it actually works

## The flow

1. **Cron fires** in GitHub Actions at `0 */3 * * *` UTC (every 3 hours on the hour, UTC)
2. **Workflow checks out two repos**: `semca-enrollment-dashboard` (code + HTML) and `semca-enrollment-data` (private CSV backup) into `./JotForm_Data`
3. **`patch_data.py` runs**, which internally:
   - Calls `jotform_sync.py` → pulls fresh CSVs from JotForm API into `./JotForm_Data`
   - Calls `semca_analysis.py` → regenerates HTML data sections from CSVs
   - Splices new data into the live `SEMCA_Enrollment_Analysis.html`
4. **Commits updated CSVs** back to the private data repo (always — even if no change)
5. **Commits updated HTML** to the dashboard repo (ONLY if HTML diff exists)
6. **GitHub Pages auto-deploys** the new HTML within ~1 min

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

1. **Last-sync timestamp should reflect actual sync time, not last commit**
   - Fix: have `patch_data.py` write `<!-- last_sync: 2026-06-09T18:00:00Z -->` into the HTML on every run, and have the JS read that instead of querying GitHub's commits API
   - This way the timestamp updates even when no new data came in
2. **Display the timezone** — "Data as of 2:24 PM ET" instead of bare "12:24"
3. **The "Classes Begin" line in projections** uses a logistic S-curve, but SEMCA's actual application pattern accelerates at the end (J-curve), not the middle. Logistic weight cap of 60% may be too high.

## Repo layout

- **`mic-led/semca-enrollment-dashboard`** (public) — code, HTML, workflow
- **`mic-led/semca-enrollment-data`** (private) — CSV backup, written by workflow each run
- **GitHub Pages** serves the HTML from main branch of the public repo
- **Squarespace** embeds an iframe pointing to the Pages URL
- **`DATA_REPO_PAT` secret** — classic PAT with `repo` scope, used by workflow to clone/push the private data repo

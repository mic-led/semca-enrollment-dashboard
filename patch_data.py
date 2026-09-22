"""
Refresh the dashboard's data.

The page (SEMCA_Enrollment_Analysis.html) is static and never rewritten here.
All data-driven content lives in dashboard-data.js, which semca_analysis.py
regenerates from the JotForm CSVs. This script just orchestrates:

Step 1: Sync JotForm CSVs (runs jotform_sync.py if API key is available).
        If sync fails, checks CSV age and warns if data is stale.
Step 2: Runs semca_analysis.py, which writes dashboard-data.js.
"""
import os
import subprocess
import sys

CSV_DIR      = os.environ.get("JOTFORM_CSV_DIR", os.path.expanduser("~/Desktop/JotForm_Data"))
DATA_JS_PATH = os.environ.get("SEMCA_DATA_JS_PATH", "./dashboard-data.js")
MAX_CSV_AGE_HOURS = 25  # warn if CSVs are older than this


def csv_age_hours():
    """Return age in hours of the newest CSV in CSV_DIR, or None if no CSVs exist."""
    try:
        csvs = [os.path.join(CSV_DIR, f) for f in os.listdir(CSV_DIR) if f.endswith(".csv")]
    except FileNotFoundError:
        return None
    if not csvs:
        return None
    from datetime import datetime
    newest_mtime = max(os.path.getmtime(f) for f in csvs)
    return (datetime.now().timestamp() - newest_mtime) / 3600


# ── Step 1: Sync JotForm data ─────────────────────────────────────────────────
print("Syncing JotForm data ...")
sync_env = dict(os.environ)
sync_env["JOTFORM_CSV_DIR"] = CSV_DIR
sync_result = subprocess.run([sys.executable, "jotform_sync.py"], env=sync_env)

if sync_result.returncode != 0:
    age = csv_age_hours()
    if age is None:
        print("ERROR: JotForm sync failed and no local CSVs found. Cannot continue.")
        sys.exit(1)
    elif age > MAX_CSV_AGE_HOURS:
        print(f"WARNING: JotForm sync failed. Local CSVs are {age:.1f} hours old — data may be stale.")
        print("         Set JOTFORM_API_KEY to enable live sync, or accept stale data.")
    else:
        print(f"  Sync skipped (no API key). Local CSVs are {age:.1f}h old — recent enough.")
else:
    age = csv_age_hours()
    print(f"  Sync complete. CSVs updated ({age:.1f}h old)." if age is not None else "  Sync complete.")

# ── Step 2: Regenerate dashboard-data.js ─────────────────────────────────────
print("Generating dashboard-data.js via semca_analysis.py ...")
env = dict(os.environ)
env["JOTFORM_CSV_DIR"]     = CSV_DIR
env["SEMCA_DATA_JS_PATH"]  = DATA_JS_PATH
env.pop("SEMCA_OUTPUT_PATH", None)   # never write the debug HTML render in the pipeline
result = subprocess.run([sys.executable, "semca_analysis.py"], env=env)
if result.returncode != 0:
    print("ERROR: semca_analysis.py failed")
    sys.exit(1)
if not os.path.exists(DATA_JS_PATH):
    print(f"ERROR: {DATA_JS_PATH} was not written")
    sys.exit(1)
print(f"Done. {DATA_JS_PATH} refreshed ({os.path.getsize(DATA_JS_PATH)/1e6:.2f} MB).")

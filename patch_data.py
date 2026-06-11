"""
Patch SEMCA_Enrollment_Analysis.html with fresh JotForm data
without overwriting UI improvements.

Step 1: Sync JotForm CSVs (runs jotform_sync.py if API key is available).
        If sync fails, checks CSV age and warns if data is stale.
Step 2: Runs semca_analysis.py to a temp file, extracts the marked
        data regions, and splices them back into the live HTML.
"""
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

HTML_PATH = os.environ.get("SEMCA_HTML_PATH", "./SEMCA_Enrollment_Analysis.html")
TMP_PATH  = "./semca_generated_tmp.html"
CSV_DIR   = os.environ.get("JOTFORM_CSV_DIR", os.path.expanduser("~/Desktop/JotForm_Data"))
MAX_CSV_AGE_HOURS = 25  # warn if CSVs are older than this

START_FALL        = "// SEMCA_FALL_MAIN_START"
END_FALL          = "// SEMCA_FALL_MAIN_END"
START_SEASONAL    = "// SEMCA_SEASONAL_DATA_START"
END_SEASONAL      = "// SEMCA_SEASONAL_DATA_END"
START_TRADE       = "// SEMCA_TRADE_DATA_START"
END_TRADE         = "// SEMCA_TRADE_DATA_END"
START_FORECAST    = "<!-- SEMCA_FORECAST_START -->"
END_FORECAST      = "<!-- SEMCA_FORECAST_END -->"
START_SUMMARY_ROW = "<!-- SEMCA_SUMMARY_ROW_START -->"
END_SUMMARY_ROW   = "<!-- SEMCA_SUMMARY_ROW_END -->"
START_INSIGHT     = "<!-- SEMCA_INSIGHT_START -->"
END_INSIGHT       = "<!-- SEMCA_INSIGHT_END -->"
START_RATIO       = "<!-- SEMCA_RATIO_START -->"
END_RATIO         = "<!-- SEMCA_RATIO_END -->"


def csv_age_hours():
    """Return age in hours of the newest CSV in CSV_DIR, or None if no CSVs exist."""
    try:
        csvs = [os.path.join(CSV_DIR, f) for f in os.listdir(CSV_DIR) if f.endswith(".csv")]
    except FileNotFoundError:
        return None
    if not csvs:
        return None
    newest_mtime = max(os.path.getmtime(f) for f in csvs)
    age = (datetime.now().timestamp() - newest_mtime) / 3600
    return age


def extract_region(text, start_marker, end_marker):
    """Return content between markers (exclusive of the marker lines themselves)."""
    pattern = re.compile(
        re.escape(start_marker) + r"\n(.*?)\n" + re.escape(end_marker),
        re.DOTALL,
    )
    m = pattern.search(text)
    if not m:
        raise ValueError(f"Marker not found: {start_marker!r}")
    return m.group(1)


def replace_region(text, start_marker, end_marker, new_content):
    """Replace content between markers (markers themselves are preserved)."""
    pattern = re.compile(
        r"(" + re.escape(start_marker) + r"\n)(.*?)(\n" + re.escape(end_marker) + r")",
        re.DOTALL,
    )
    result, n = pattern.subn(lambda m: m.group(1) + new_content + m.group(3), text)
    if n == 0:
        raise ValueError(f"Marker not found in live HTML: {start_marker!r}")
    return result


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

# ── Step 2: Generate and patch ────────────────────────────────────────────────
print("Generating fresh data via semca_analysis.py ...")
env = dict(os.environ)
env["SEMCA_OUTPUT_PATH"] = TMP_PATH
env["JOTFORM_CSV_DIR"]   = CSV_DIR
result = subprocess.run([sys.executable, "semca_analysis.py"], env=env)
if result.returncode != 0:
    print("ERROR: semca_analysis.py failed")
    sys.exit(1)

with open(TMP_PATH, "r", encoding="utf-8") as f:
    generated = f.read()
with open(HTML_PATH, "r", encoding="utf-8") as f:
    live = f.read()

fall_data        = extract_region(generated, START_FALL,        END_FALL)
seasonal_data    = extract_region(generated, START_SEASONAL,    END_SEASONAL)
trade_data       = extract_region(generated, START_TRADE,       END_TRADE)
forecast_data    = extract_region(generated, START_FORECAST,    END_FORECAST)
summary_row_data = extract_region(generated, START_SUMMARY_ROW, END_SUMMARY_ROW)
insight_data     = extract_region(generated, START_INSIGHT,     END_INSIGHT)
ratio_data       = extract_region(generated, START_RATIO,       END_RATIO)

live = replace_region(live, START_FALL,        END_FALL,        fall_data)
live = replace_region(live, START_SEASONAL,    END_SEASONAL,    seasonal_data)
live = replace_region(live, START_TRADE,       END_TRADE,       trade_data)
live = replace_region(live, START_FORECAST,    END_FORECAST,    forecast_data)
live = replace_region(live, START_SUMMARY_ROW, END_SUMMARY_ROW, summary_row_data)
live = replace_region(live, START_INSIGHT,     END_INSIGHT,     insight_data)
live = replace_region(live, START_RATIO,       END_RATIO,       ratio_data)

sync_time_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
live = re.sub(r'<meta name="data-sync-time" content="[^"]*">',
              f'<meta name="data-sync-time" content="{sync_time_iso}">', live)

today_str = datetime.now().strftime("%B %d, %Y")
live = re.sub(r"Generated \w+ \d+, \d{4}", f"Generated {today_str}", live)
live = re.sub(r"Enrollment Trend Analysis &bull; \w+ \d+, \d{4}",
              f"Enrollment Trend Analysis &bull; {today_str}", live)
live = re.sub(r"All figures as of \w+ \d+, \d{4}\.",
              f"All figures as of {today_str}.", live)

for var in ("CSV_DATA", "CONV_DATA"):
    m = re.search(rf"const {var} = (\[.*?\]);", generated, re.DOTALL)
    if m:
        live = re.sub(rf"const {var} = \[.*?\];", f"const {var} = {m.group(1)};", live, flags=re.DOTALL)
        print(f"  Updated {var}")
    else:
        print(f"  WARNING: {var} not found in generated HTML")

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(live)

os.remove(TMP_PATH)
print(f"Patched {HTML_PATH} with fresh enrollment data ({today_str}).")

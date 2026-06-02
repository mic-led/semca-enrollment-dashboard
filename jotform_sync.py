import requests
import json
import csv
import os
import re
from datetime import datetime

SSN_LABEL_KEYWORDS = {"social security", "ssn", "social sec", "ss number", "sin number"}
SSN_PATTERN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")

def is_ssn_field(label):
    return any(kw in label.lower() for kw in SSN_LABEL_KEYWORDS)

def redact_ssn(value):
    if isinstance(value, str):
        return SSN_PATTERN.sub("***-**-****", value)
    return value

# Paths — override with env vars for server deployments
SUMMARY_PATH = os.environ.get("JOTFORM_SUMMARY_PATH", os.path.expanduser("~/jotform_summary.json"))
CSV_DIR      = os.environ.get("JOTFORM_CSV_DIR",      os.path.expanduser("~/Desktop/JotForm_Data"))
BASE_URL     = "https://semcaschool.jotform.com/API/v1"

# Credentials — use env vars on servers, fall back to keyring on local Mac
API_KEY = os.environ.get("JOTFORM_API_KEY", "")
TEAM_ID = os.environ.get("JOTFORM_TEAM_ID", "")
if not API_KEY:
    try:
        import keyring
        API_KEY = keyring.get_password("jotform", "api_key") or ""
        TEAM_ID = keyring.get_password("jotform", "team_id") or ""
    except Exception:
        pass

if not API_KEY:
    print("No API key found. Set the JOTFORM_API_KEY environment variable.")
    exit(1)

HEADERS = {"APIKEY": API_KEY}
if TEAM_ID:
    HEADERS["jf-team-id"] = TEAM_ID

os.makedirs(CSV_DIR, exist_ok=True)

SKIP_STATUSES = {"ARCHIVED", "DELETED"}

print(f"Syncing at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
r = requests.get(f"{BASE_URL}/user/forms", headers=HEADERS, params={"limit": 100})
all_forms = r.json().get("content", [])

forms = [f for f in all_forms if f.get("status", "").upper() not in SKIP_STATUSES]
skipped = [f["title"] for f in all_forms if f.get("status", "").upper() in SKIP_STATUSES]
if skipped:
    print(f"  Skipping {len(skipped)} archived/deleted form(s): {', '.join(skipped)}")

summary = []

for form in forms:
    form_id = form["id"]
    form_title = form["title"]
    safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in form_title).strip()
    csv_path = os.path.join(CSV_DIR, f"{safe_title}.csv")

    print(f"  Syncing: {form_title}")

    # Fetch completed submissions only (status=ACTIVE excludes drafts/incomplete)
    r = requests.get(f"{BASE_URL}/form/{form_id}/submissions", headers=HEADERS, params={"limit": 1000, "filter[status]": "ACTIVE"})
    submissions = r.json().get("content", [])

    # Build columns, excluding SSN fields
    columns = ["submission_id", "date"]
    for sub in submissions:
        for key, field in sub["answers"].items():
            label = field.get("text", f"field_{key}")
            if label and label not in columns and not is_ssn_field(label):
                columns.append(label)

    # Write CSV (full overwrite with latest data)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for sub in submissions:
            row = {"submission_id": sub["id"], "date": sub["created_at"]}
            for key, field in sub["answers"].items():
                label = field.get("text", f"field_{key}")
                if label and not is_ssn_field(label):
                    row[label] = redact_ssn(field.get("answer", ""))
            writer.writerow(row)

    summary.append({
        "form_id": form_id,
        "title": form_title,
        "submission_count": len(submissions),
        "last_synced": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "csv": csv_path,
        "columns": columns
    })

    print(f"    {len(submissions)} submissions saved to {csv_path}")

# Save summary (no student data)
summary_safe = [{k: v for k, v in f.items() if k != "csv"} for f in summary]
with open(SUMMARY_PATH, "w") as f:
    json.dump(summary_safe, f, indent=2)

print(f"\nAll CSVs saved to: {CSV_DIR}")

# Build summary text
lines = ["--- SHARE THIS WITH CLAUDE ---"]
for form in summary:
    lines.append(f"\nForm: {form['title']} ({form['submission_count']} submissions) | Last synced: {form['last_synced']}")
    lines.append(f"Columns: {', '.join(form['columns'])}")
summary_text = "\n".join(lines)

print(f"\n{summary_text}")

# Copy to clipboard
try:
    import subprocess
    subprocess.run("pbcopy", input=summary_text.encode(), check=True)
    print("\nSummary copied to clipboard. Paste it directly into Claude.")
except Exception:
    pass  # pbcopy not available outside macOS (e.g. CI)

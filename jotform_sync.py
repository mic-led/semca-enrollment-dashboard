import requests
import json
import csv
import hmac
import hashlib
import os
import re
import glob
from datetime import datetime

# ─── PII policy ────────────────────────────────────────────────────────────────
# The private data repo (mic-led/semca-enrollment-data) should never contain
# plaintext names, emails, phone numbers, addresses, or Social Security numbers.
# This sync projects each JotForm submission down to the minimum set of fields
# the dashboard actually reads, and emits three salted HMAC-SHA256 hashes so we
# can still detect duplicates and join applications to registrations.
#
# PII_SALT must be set as an env var (locally) and a GitHub Actions secret (in
# CI). Same salt across all runs, or hashes stop matching and dedup breaks.

SSN_LABEL_KEYWORDS = {"social security", "ssn", "social sec", "ss number", "sin number"}

# Labels the dashboard actually reads. Everything else gets dropped.
# Year-specific variants ("Trade/Level for Fall 2027", "...For The 27/28 School Year?")
# are matched by KEEP_LABEL_PATTERNS so new forms keep working without edits here.
KEEP_LABEL_PATTERNS = (
    re.compile(r"^Trade/Level for (Fall|Winter) \d{4}$"),
    re.compile(r"^What Campus Location Would You Like For The \d{2}/\d{2} School Year\?$"),
)
def is_kept_label(label):
    return label in KEEP_LABELS or any(p.match(label) for p in KEEP_LABEL_PATTERNS)

KEEP_LABELS = {
    # Applications
    "What is your preferred trade?",
    "What is your preferred school location?",
    "How did you first hear about SEMCA?",
    "What is your race? (select all that apply)",
    "What is your highest level of education?",
    # Registrations — trade aliases
    "Trade Registering For:",
    "Trade Registering For",
    "Trade/Level",
    "Trade/Level for Fall 2022",
    "Trade/Level for Fall 2023",
    "Trade/Level for Fall 2024",
    "Trade/Level for Fall 2025",
    "Trade/Level for Fall 2026",
    "Cornerstone Schools Trade Registering For:",
    "Chance for Life Trade Registering For",
    "Holly Area Schools Trade Registering For:",
    # Registrations — location aliases
    "What location?",
    "What Campus Location Would You Like For The 23/24 School Year?",
    "What Campus Location Would You Like For The 24/25 School Year?",
    "What Campus Location Would You Like For The 25/26 School Year?",
    "What Campus Location Would You Like For The 26/27 School Year?",
    "What is your CURRENT Campus Location?",
}

# Labels used only to derive hashes — never written to CSV in plaintext.
NAME_LABELS  = {"Name", "Applicant Name", "Applicant's Name", "Full Name", "Student Name"}
EMAIL_LABELS = {"Email", "Applicant's Email", "Email Address", "E-mail"}
PHONE_LABELS = {"Phone Number", "Phone", "Cell Phone", "Cell Phone Number", "Applicant Phone Number", "Applicant's Cell Phone Number"}

HASH_COLUMNS = ["name_hash", "phone_hash", "email_hash"]

def is_ssn_field(label):
    return any(kw in label.lower() for kw in SSN_LABEL_KEYWORDS)

def _get_salt():
    salt = os.environ.get("PII_SALT", "").encode("utf-8")
    if not salt:
        print("ERROR: PII_SALT env var is required. Set it locally and as a GH Actions secret.")
        exit(2)
    return salt

def _hash(value, salt):
    """Deterministic salted hash. Returns empty string if value is blank."""
    if not value:
        return ""
    v = value.strip().lower()
    if not v:
        return ""
    return hmac.new(salt, v.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

def _normalize_phone(raw):
    """Keep only digits, use last 10 so 555-1234 vs +1 555 1234 collide."""
    digits = re.sub(r"\D", "", raw or "")
    return digits[-10:] if len(digits) >= 10 else digits

def _extract_answer(field):
    """JotForm answers can be dicts (composite fields like Name/Address) or strings."""
    ans = field.get("answer", "")
    if isinstance(ans, dict):
        # Composite: join non-empty values in a stable order
        return " ".join(str(v).strip() for k, v in sorted(ans.items()) if str(v).strip())
    return str(ans).strip() if ans else ""

# ─── Paths + credentials ───────────────────────────────────────────────────────
SUMMARY_PATH = os.environ.get("JOTFORM_SUMMARY_PATH", os.path.expanduser("~/jotform_summary.json"))
CSV_DIR      = os.environ.get("JOTFORM_CSV_DIR",      os.path.expanduser("~/Desktop/JotForm_Data"))
BASE_URL     = "https://semcaschool.jotform.com/API/v1"

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

SALT = _get_salt()

HEADERS = {"APIKEY": API_KEY}
if TEAM_ID:
    HEADERS["jf-team-id"] = TEAM_ID

os.makedirs(CSV_DIR, exist_ok=True)

SKIP_STATUSES = {"ARCHIVED", "DELETED"}

# ─── Fetch + write ─────────────────────────────────────────────────────────────
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

    r = requests.get(f"{BASE_URL}/form/{form_id}/submissions", headers=HEADERS, params={"limit": 1000, "filter[status]": "ACTIVE"})
    submissions = r.json().get("content", [])

    # Determine which of KEEP_LABELS actually appear in this form
    present_labels = set()
    for sub in submissions:
        for _, field in sub["answers"].items():
            label = field.get("text", "")
            if is_kept_label(label):
                present_labels.add(label)

    columns = ["submission_id", "date"] + sorted(present_labels) + HASH_COLUMNS

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for sub in submissions:
            row = {"submission_id": sub["id"], "date": sub["created_at"]}
            # Extract PII into local vars, hash, then discard
            name_val, phone_val, email_val = "", "", ""
            for _, field in sub["answers"].items():
                label = field.get("text", "")
                if not label or is_ssn_field(label):
                    continue
                val = _extract_answer(field)
                if is_kept_label(label):
                    row[label] = val
                elif label in NAME_LABELS and not name_val:
                    name_val = val
                elif label in EMAIL_LABELS and not email_val:
                    email_val = val
                elif label in PHONE_LABELS and not phone_val:
                    phone_val = val
            row["name_hash"]  = _hash(name_val, SALT)
            row["phone_hash"] = _hash(_normalize_phone(phone_val), SALT)
            row["email_hash"] = _hash(email_val, SALT)
            writer.writerow(row)

    summary.append({
        "form_id": form_id,
        "title": form_title,
        "submission_count": len(submissions),
        "last_synced": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "csv": csv_path,
        "columns": columns,
    })

    print(f"    {len(submissions)} submissions saved to {csv_path}")

# ─── Legacy scrub ─────────────────────────────────────────────────────────────
# Forms JotForm reports as ARCHIVED/DELETED are skipped above, so a CSV written before the
# PII policy keeps its plaintext identity columns forever. Rewrite any CSV in CSV_DIR that
# lacks the hash columns down to the same de-identified schema, hashing from its plaintext
# with the same salt/normalisation so the hashes join with freshly synced forms.
def _first(row, labels):
    for lbl in labels:
        v = row.get(lbl)
        if v and str(v).strip():
            return str(v)
    return ""

def scrub_legacy_csv(path):
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        cols = reader.fieldnames or []
        rows = list(reader)
    if not cols or all(hc in cols for hc in HASH_COLUMNS):
        return False
    kept = [c for c in cols if c not in ("submission_id", "date") and is_kept_label(c)]
    out_cols = ["submission_id", "date"] + sorted(kept) + HASH_COLUMNS
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=out_cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            o = {c: (r.get(c) or "") for c in out_cols if c not in HASH_COLUMNS}
            o["name_hash"]  = _hash(_first(r, NAME_LABELS), SALT)
            o["phone_hash"] = _hash(_normalize_phone(_first(r, PHONE_LABELS)), SALT)
            o["email_hash"] = _hash(_first(r, EMAIL_LABELS), SALT)
            w.writerow(o)
    return True

_scrubbed = [os.path.basename(pth) for pth in sorted(glob.glob(os.path.join(CSV_DIR, "*.csv"))) if scrub_legacy_csv(pth)]
if _scrubbed:
    print(f"\n  Scrubbed {len(_scrubbed)} legacy CSV(s) of plaintext identity columns: " + ", ".join(_scrubbed[:6]) + (" …" if len(_scrubbed) > 6 else ""))

summary_safe = [{k: v for k, v in f.items() if k != "csv"} for f in summary]
with open(SUMMARY_PATH, "w") as f:
    json.dump(summary_safe, f, indent=2)

print(f"\nAll CSVs saved to: {CSV_DIR}")

lines = ["--- SHARE THIS WITH CLAUDE ---"]
for form in summary:
    lines.append(f"\nForm: {form['title']} ({form['submission_count']} submissions) | Last synced: {form['last_synced']}")
    lines.append(f"Columns: {', '.join(form['columns'])}")
summary_text = "\n".join(lines)

print(f"\n{summary_text}")

try:
    import subprocess
    subprocess.run("pbcopy", input=summary_text.encode(), check=True)
    print("\nSummary copied to clipboard. Paste it directly into Claude.")
except Exception:
    pass

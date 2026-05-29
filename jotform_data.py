import requests
import csv
import os

API_KEY = input("Paste your JotForm API key: ").strip()
TEAM_ID = input("Paste your JotForm Team ID (press Enter to skip): ").strip()

BASE_URL = "https://semcaschool.jotform.com/API/v1"
HEADERS = {"APIKEY": API_KEY}
if TEAM_ID:
    HEADERS["jf-team-id"] = TEAM_ID

print("\n--- YOUR FORMS ---")
r = requests.get(f"{BASE_URL}/user/forms", headers=HEADERS)
forms = r.json()["content"]
for i, form in enumerate(forms):
    print(f"[{i}] {form['title']} (ID: {form['id']}) — {form['count']} submissions")

print()
choice = input("Enter the number of the form to export: ").strip()
if not choice.isdigit():
    print("No form selected.")
    input("\nPress Enter to close...")
    exit()

form = forms[int(choice)]
form_id = form['id']
form_title = form['title'].replace(" ", "_")

print(f"\nFetching submissions for: {form['title']}...")
r = requests.get(f"{BASE_URL}/form/{form_id}/submissions", headers=HEADERS, params={"limit": 1000})
submissions = r.json().get("content", [])

if not submissions:
    print("No submissions found.")
    input("\nPress Enter to close...")
    exit()

# Collect all column names from answers
columns = ["submission_id", "date"]
field_labels = {}
for sub in submissions:
    for key, field in sub["answers"].items():
        label = field.get("text", f"field_{key}")
        if label not in field_labels.values():
            field_labels[key] = label
            if label not in columns:
                columns.append(label)

# Save to CSV
output_path = os.path.expanduser(f"~/Desktop/{form_title}_submissions.csv")
with open(output_path, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    for sub in submissions:
        row = {"submission_id": sub["id"], "date": sub["created_at"]}
        for key, field in sub["answers"].items():
            label = field.get("text", f"field_{key}")
            row[label] = field.get("answer", "")
        writer.writerow(row)

print(f"\nData saved to: {output_path}")
print(f"\n--- SHARE THIS WITH CLAUDE (no student data) ---")
print(f"Form: {form['title']}")
print(f"Total rows: {len(submissions)}")
print(f"Columns: {', '.join(columns)}")

input("\nPress Enter to close...")

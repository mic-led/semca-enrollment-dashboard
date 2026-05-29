#!/usr/bin/env python3
"""
SEMCA Live Counts Proxy
-----------------------
Runs as a small web server that:
  - Serves the dashboard HTML at  GET /
  - Exposes live JotForm counts at GET /api/counts

The browser calls /api/counts (same origin, no CORS issues).
This server calls the JotForm API server-side and returns the result.

Required env vars:
  JOTFORM_API_KEY      — JotForm API key
  JOTFORM_TEAM_ID      — JotForm team ID (if using a team account)

Optional env vars:
  JOTFORM_SUMMARY_PATH — path to jotform_summary.json  (default: ~/jotform_summary.json)
  SEMCA_OUTPUT_PATH    — path to the dashboard HTML     (default: ~/Desktop/SEMCA_Enrollment_Analysis.html)
  PORT                 — port to listen on              (default: 5000)

Run:
  python3 proxy.py

Then open http://localhost:5000 in your browser.
"""

import json
import os
import requests
from flask import Flask, jsonify, send_file

app = Flask(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
API_KEY  = os.environ.get("JOTFORM_API_KEY", "")
TEAM_ID  = os.environ.get("JOTFORM_TEAM_ID", "")
if not API_KEY:
    try:
        import keyring
        API_KEY = keyring.get_password("jotform", "api_key") or ""
        TEAM_ID = keyring.get_password("jotform", "team_id") or ""
    except Exception:
        pass

BASE_URL     = "https://semcaschool.jotform.com/API/v1"
SUMMARY_PATH = os.environ.get("JOTFORM_SUMMARY_PATH", os.path.expanduser("~/jotform_summary.json"))
OUTPUT_PATH  = os.environ.get("SEMCA_OUTPUT_PATH",    os.path.expanduser("~/Desktop/SEMCA_Enrollment_Analysis.html"))

# ── Load form IDs from summary file ──────────────────────────────────────────
def _load_form_ids():
    if not os.path.exists(SUMMARY_PATH):
        return {}
    with open(SUMMARY_PATH) as f:
        entries = json.load(f)
    return {e["title"]: e["form_id"] for e in entries}

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_file(OUTPUT_PATH)

@app.route("/api/counts")
def counts():
    if not API_KEY:
        return jsonify({"error": "No API key configured"}), 500

    form_ids = _load_form_ids()
    headers  = {"APIKEY": API_KEY}
    if TEAM_ID:
        headers["jf-team-id"] = TEAM_ID

    # These titles must match the form names in JotForm exactly
    active_year = _detect_active_year(form_ids)
    targets = {
        "app":       form_ids.get(f"{active_year} SEMCA Application"),
        "new_reg":   form_ids.get(f"{active_year} SEMCA New Student Class Registration"),
        "abc_reg":   form_ids.get(f"{active_year} ABCSEMI Member Company New Student Class Registration"),
        "partner":   form_ids.get(f"{active_year} Partner Program Registration"),
        "returning": form_ids.get(f"{active_year} SEMCA Returning Student Registration"),
    }

    result = {}
    for key, form_id in targets.items():
        if not form_id:
            result[key] = 0
            continue
        try:
            r = requests.get(
                f"{BASE_URL}/form/{form_id}/submissions",
                headers=headers,
                params={"limit": 1000},
                timeout=10,
            )
            data = r.json()
            result[key] = len(data.get("content", []))
        except Exception:
            result[key] = None

    return jsonify(result)

def _detect_active_year(form_ids):
    """Pick the most recent Fall year that has a registered application form."""
    for year in range(2030, 2021, -1):
        if f"Fall {year} SEMCA Application" in form_ids:
            return f"Fall {year}"
    return "Fall 2026"

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not API_KEY:
        print("WARNING: No JOTFORM_API_KEY set. /api/counts will fail.")
    port = int(os.environ.get("PORT", 5000))
    print(f"Starting proxy on http://0.0.0.0:{port}")
    print(f"  Dashboard: {OUTPUT_PATH}")
    print(f"  Summary:   {SUMMARY_PATH}")
    app.run(host="0.0.0.0", port=port)

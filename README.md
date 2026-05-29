# SEMCA Enrollment Dashboard

Automated enrollment analytics dashboard for SEMCA, pulling live data from JotForm.

## How it works

1. `jotform_sync.py` — pulls all form submissions from JotForm and saves them as CSVs
2. `semca_analysis.py` — reads those CSVs and generates the dashboard HTML
3. `proxy.py` — serves the dashboard and proxies live JotForm counts to the browser (fixes CORS)

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set environment variables
```bash
export JOTFORM_API_KEY=your_api_key_here
export JOTFORM_TEAM_ID=your_team_id_here
export JOTFORM_CSV_DIR=/path/to/store/csvs
export JOTFORM_SUMMARY_PATH=/path/to/jotform_summary.json
export SEMCA_OUTPUT_PATH=/path/to/dashboard.html
```

### 3. Run the initial sync and build
```bash
python3 jotform_sync.py
python3 semca_analysis.py
```

### 4. Start the web server
```bash
python3 proxy.py
```

The dashboard will be available at `http://localhost:5000` (or set `PORT` to change the port).

## Keeping data fresh (cron job)

Add this to your server's crontab to sync and rebuild every hour:
```
0 * * * * cd /path/to/repo && python3 jotform_sync.py && python3 semca_analysis.py
```

## Updating

When the dashboard owner pushes changes:
```bash
git pull
python3 semca_analysis.py  # rebuild with latest code
```

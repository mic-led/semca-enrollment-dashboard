"""
Patch SEMCA_Enrollment_Analysis.html with fresh JotForm data
without overwriting UI improvements.

Runs semca_analysis.py to a temp file, extracts the three marked
data regions, and splices them back into the live HTML.
"""
import os
import re
import subprocess
import sys

HTML_PATH = os.environ.get("SEMCA_HTML_PATH", "./SEMCA_Enrollment_Analysis.html")
TMP_PATH  = "./semca_generated_tmp.html"

START_FALL     = "// SEMCA_FALL_MAIN_START"
END_FALL       = "// SEMCA_FALL_MAIN_END"
START_SEASONAL = "// SEMCA_SEASONAL_DATA_START"
END_SEASONAL   = "// SEMCA_SEASONAL_DATA_END"
START_TRADE    = "// SEMCA_TRADE_DATA_START"
END_TRADE      = "// SEMCA_TRADE_DATA_END"


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


print("Generating fresh data via semca_analysis.py ...")
env = dict(os.environ)
env["SEMCA_OUTPUT_PATH"] = TMP_PATH
result = subprocess.run([sys.executable, "semca_analysis.py"], env=env)
if result.returncode != 0:
    print("ERROR: semca_analysis.py failed")
    sys.exit(1)

with open(TMP_PATH, "r", encoding="utf-8") as f:
    generated = f.read()
with open(HTML_PATH, "r", encoding="utf-8") as f:
    live = f.read()

fall_data     = extract_region(generated, START_FALL,     END_FALL)
seasonal_data = extract_region(generated, START_SEASONAL, END_SEASONAL)
trade_data    = extract_region(generated, START_TRADE,    END_TRADE)

live = replace_region(live, START_FALL,     END_FALL,     fall_data)
live = replace_region(live, START_SEASONAL, END_SEASONAL, seasonal_data)
live = replace_region(live, START_TRADE,    END_TRADE,    trade_data)

with open(HTML_PATH, "w", encoding="utf-8") as f:
    f.write(live)

os.remove(TMP_PATH)
print(f"Patched {HTML_PATH} with fresh enrollment data.")

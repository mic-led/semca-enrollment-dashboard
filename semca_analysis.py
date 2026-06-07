#!/usr/bin/env python3
"""
SEMCA Enrollment Trend Analysis — Premium Dashboard
"""

import csv
import json
import math
import os
import statistics as _stats
from datetime import datetime, timedelta
from collections import defaultdict

# Credentials — env vars for servers, keyring fallback on local Mac
_LIVE_API_KEY = os.environ.get("JOTFORM_API_KEY", "")
_LIVE_TEAM_ID = os.environ.get("JOTFORM_TEAM_ID", "")
if not _LIVE_API_KEY:
    try:
        import keyring as _keyring
        _LIVE_API_KEY = _keyring.get_password("jotform", "api_key") or ""
        _LIVE_TEAM_ID = _keyring.get_password("jotform", "team_id") or ""
    except Exception:
        pass

# Paths — override with env vars for server deployments
DATA_DIR    = os.environ.get("JOTFORM_CSV_DIR",      os.path.expanduser("~/Desktop/JotForm_Data"))
OUTPUT_PATH = os.environ.get("SEMCA_OUTPUT_PATH",    os.path.expanduser("~/Desktop/SEMCA_Enrollment_Analysis.html"))

# ── Data sources ──────────────────────────────────────────────────────────────

FALL_APPS = {
    "Fall 2022": "Fall 2022 SEMCA Application.csv",
    "Fall 2023": "Fall 2023 SEMCA Application.csv",
    "Fall 2024": "Fall 2024 SEMCA Application.csv",
    "Fall 2025": "Fall 2025 SEMCA Application.csv",
    "Fall 2026": "Fall 2026 SEMCA Application.csv",
}
FALL_NEW_REG = {
    "Fall 2022": "Fall 2022 SEMCA New Student Class Registration.csv",
    "Fall 2023": "Fall 2023 SEMCA New Student Class Registration.csv",
    "Fall 2024": "Fall 2024 SEMCA New Student Class Registration.csv",
    "Fall 2025": "Fall 2025 SEMCA New Student Class Registration.csv",
    "Fall 2026": "Fall 2026 SEMCA New Student Class Registration.csv",
}
FALL_ABC_REG = {
    "Fall 2022": "Fall 2022 ABCSEMI Member Company New Student Class Registration.csv",
    "Fall 2023": "Fall 2023 ABCSEMI Member Company New Student Class Registration.csv",
    "Fall 2024": "Fall 2024 ABCSEMI Member Company New Student Class Registration.csv",
    "Fall 2025": "Fall 2025 ABCSEMI Member Company New Student Class Registration.csv",
    "Fall 2026": "Fall 2026 ABCSEMI Member Company New Student Class Registration.csv",
}
FALL_RETURNING = {
    "Fall 2022": "Fall 2022 SEMCA Returning Student Registration.csv",
    "Fall 2023": "Fall 2023 SEMCA Returning Student Registration.csv",
    "Fall 2024": "Fall 2024 SEMCA Returning Student Registration.csv",
    "Fall 2025": "Fall 2025 SEMCA Returning Student Registration.csv",
    "Fall 2026": "Fall 2026 SEMCA Returning Student Registration.csv",
}
WINTER_APPS = {
    "Winter 2025": "Winter 2025 SEMCA Application.csv",
    "Winter 2026": "Winter 2026 SEMCA Application.csv",
}
WINTER_NEW_REG = {
    "Winter 2025": "Winter 2025 SEMCA New Student Class Registration.csv",
    "Winter 2026": "Winter 2026 SEMCA New Student Class Registration.csv",
}
WINTER_ABC_REG = {
    "Winter 2025": "Winter 2025 ABCSEMI Member Company New Student Class Registration.csv",
    "Winter 2026": "Winter 2026 ABCSEMI Member Company New Student Class Registration.csv",
}
# Partner program registrations (Cornerstone, Chance for Life, Holly, etc.)
FALL_PARTNER_REG = {
    "Fall 2026": "Fall 2026 Partner Program Registration.csv",
}
WINTER_PARTNER_REG = {
    "Winter 2026": "Partner Program Registration.csv",
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_csv(filename):
    if not filename:
        return []
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path) or os.path.isdir(path):
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return list(csv.DictReader(f))

def parse_date(s):
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            pass
    return None

def normalize_trade(raw):
    raw = raw.strip()
    if "Electrical" in raw: return "Electrical"
    if "Carpentry" in raw: return "Carpentry"
    if "HVAC" in raw: return "HVACR"
    if "Welding" in raw: return "Welding"
    if "Plumbing" in raw: return "Plumbing"
    if "Intro" in raw or "Introduction" in raw or "Pre-Apprenticeship" in raw or "Heavy Construction" in raw: return "Intro / Pre-App"
    if "Construction Craft" in raw or "Laborer" in raw: return "CCL"
    return "Unknown" if not raw else raw

def normalize_location(raw):
    raw = raw.strip()
    if "Sterling" in raw: return "Sterling Heights"
    if "Madison" in raw or "Troy" in raw: return "Madison Heights"
    if "Westland" in raw: return "Westland"
    if "Monroe" in raw: return "Monroe"
    if "Lapeer" in raw: return "Lapeer"
    if "Holly" in raw: return "Holly"
    return "Not Specified"

def cumulative_by_week(rows, date_field="date"):
    dates = sorted([d for d in (parse_date(r.get(date_field, "")) for r in rows) if d])
    if not dates:
        return {}, None
    start = dates[0]
    weekly = defaultdict(int)
    for d in dates:
        weekly[max(0, (d - start).days // 7)] += 1
    result, total = {}, 0
    for w in range(max(weekly.keys()) + 1):
        total += weekly.get(w, 0)
        result[w] = total
    return result, start

def pct_change(old, new):
    if old == 0: return "N/A"
    v = round((new - old) / old * 100, 1)
    return f"+{v}%" if v >= 0 else f"{v}%"

def _linear_trend(x_vals, y_vals):
    """OLS linear regression. Returns (predict_fn, residual_std) or (None, 0)."""
    n = len(x_vals)
    if n < 2:
        return None, 0
    sx  = sum(x_vals);  sy  = sum(y_vals)
    sxy = sum(x * y for x, y in zip(x_vals, y_vals))
    sxx = sum(x * x for x in x_vals)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None, 0
    slope     = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    predict   = lambda x: slope * x + intercept
    residuals = [y - predict(x) for x, y in zip(x_vals, y_vals)]
    res_std   = _stats.stdev(residuals) if len(residuals) > 1 else 0
    return predict, res_std


def _logistic(t, k, t0):
    """Normalized logistic sigmoid: returns fraction of total enrolled by week t."""
    try:
        return 1.0 / (1.0 + math.exp(-k * (t - t0)))
    except OverflowError:
        return 0.0 if k * (t - t0) < 0 else 1.0


def _fit_logistic_params(cum_dict, final):
    """
    Fit logistic k (growth rate) and t0 (inflection week) to a completed year.
    Transforms the cumulative curve via logit then fits a line: logit(p) = k*t - k*t0.
    Only uses weeks where 5% < p < 95% to avoid logit singularities.
    Returns (k, t0) or None.
    """
    if final == 0:
        return None
    xs, ys = [], []
    for w in sorted(cum_dict.keys()):
        p = cum_dict[w] / final
        if 0.05 < p < 0.95:
            try:
                xs.append(w)
                ys.append(math.log(p / (1 - p)))
            except (ValueError, ZeroDivisionError):
                continue
    if len(xs) < 2:
        return None
    n   = len(xs)
    sx  = sum(xs);  sy  = sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    k         = (n * sxy - sx * sy) / denom
    intercept = (sy - k * sx) / n
    if k <= 0:
        return None  # enrollment must be increasing
    return k, -intercept / k


def _logistic_projection(current_cum_dict, hist_cumulative, hist_final, hist_labels):
    """
    Logistic S-curve projection.

    Fits k and t0 to each prior year's full cumulative curve using logit-linear OLS.
    Takes a recency-weighted average of the parameters, then projects:
        L = current_total / logistic(current_week, k_avg, t0_avg)

    Advantage over velocity model: the logistic enforces the correct S-shaped
    functional form (slow start → acceleration → plateau before Sept 3).
    The parameter t0 tells you where peak weekly enrollment typically falls;
    if you are pre-inflection you still have most enrollment ahead of you.

    Returns (point_est, low, high, (k_avg, t0_avg), detail) or None.
    """
    if not current_cum_dict:
        return None
    current_week  = max(current_cum_dict.keys())
    current_total = current_cum_dict.get(current_week, 0)
    if current_total == 0 or current_week < 1:
        return None

    max_hist = max((hist_final.get(l, 0) for l in hist_labels), default=0)
    cap      = max_hist * 1.4

    params_list = []
    for i, label in enumerate(hist_labels):
        hcum  = hist_cumulative.get(label, {})
        final = hist_final.get(label, 0)
        if final == 0 or not hcum:
            continue
        result = _fit_logistic_params(hcum, final)
        if result is None:
            continue
        params_list.append((*result, i + 1, label))  # (k, t0, weight, label)

    if not params_list:
        return None

    total_w = sum(w for _, _, w, _ in params_list)
    k_avg   = sum(k * w for k, _, w, _ in params_list) / total_w
    t0_avg  = sum(t * w for _, t, w, _ in params_list) / total_w

    p_at_W = _logistic(current_week, k_avg, t0_avg)
    if p_at_W <= 0 or p_at_W >= 1:
        return None

    point_est = round(current_total / p_at_W)
    point_est = max(point_est, current_total)
    if cap > 0:
        point_est = min(point_est, int(cap))

    individual = []
    for k, t0, _, label in params_list:
        p = _logistic(current_week, k, t0)
        if 0 < p < 1:
            L = max(round(current_total / p), current_total)
            if cap > 0:
                L = min(L, int(cap))
            individual.append((L, label))

    if individual:
        all_L = [L for L, _ in individual]
        low   = max(round(min(all_L)), current_total)
        high  = min(round(max(all_L)), int(cap) if cap > 0 else round(point_est * 1.3))
    else:
        low = high = point_est

    detail = [(label, L) for L, label in individual]
    return point_est, low, high, (k_avg, t0_avg), detail


def _velocity_projection(current_cum_dict, hist_cumulative, hist_final, hist_labels):
    """
    Velocity-shape projection using OLS curve fitting.

    For each completed year, we build a normalized velocity curve:
        norm_vel[y][w] = (new submissions in week w) / final_total[y]

    We then find the scale factor k that makes k * norm_vel[y] best fit the
    current year's observed weekly submissions (OLS over all weeks 0..W):
        k_y = Σ(norm_vel[y][w] * current_delta[w]) / Σ(norm_vel[y][w]²)

    k_y is the projected final total IF the current year follows year y's shape.
    We take a recency-weighted blend of k_y across all prior years.

    Advantage over single-point completion rate: uses the entire velocity history
    up to the current week, so one anomalous early week doesn't dominate the
    estimate. Phase detection (acceleration vs. deceleration) emerges naturally —
    if this year's velocity profile more closely matches a high-enrollment year,
    the OLS fit will reflect that.
    """
    if not current_cum_dict:
        return None

    current_week  = max(current_cum_dict.keys())
    current_total = current_cum_dict.get(current_week, 0)
    if current_total == 0:
        return None

    # Weekly new submissions for current year (velocity observations)
    current_delta = {}
    prev = 0
    for w in range(current_week + 1):
        v = current_cum_dict.get(w, prev)
        current_delta[w] = v - prev
        prev = v

    results = []
    for i, label in enumerate(hist_labels):
        hcum  = hist_cumulative.get(label, {})
        final = hist_final.get(label, 0)
        if final == 0 or not hcum:
            continue

        # Normalized velocity curve for this historical year
        norm_vel, prev = {}, 0
        for w in range(max(hcum.keys()) + 1):
            v = hcum.get(w, prev)
            norm_vel[w] = (v - prev) / final
            prev = v

        # OLS: k = Σ(nv * cd) / Σ(nv²)  over weeks 0..current_week
        numer = sum(norm_vel.get(w, 0) * current_delta.get(w, 0) for w in range(current_week + 1))
        denom = sum(norm_vel.get(w, 0) ** 2                       for w in range(current_week + 1))
        if denom <= 0:
            continue

        k = numer / denom
        # Clamp each year's estimate: must be >= current count and <= 40% above best ever.
        # This prevents years with near-zero early velocity from exploding the weighted average.
        max_hist_k = max((hist_final.get(l, 0) for l in hist_labels), default=0)
        k = max(k, current_total)
        if max_hist_k > 0:
            k = min(k, max_hist_k * 1.4)
        results.append((k, i + 1, label))  # weight = index+1 (recent years higher)

    if not results:
        return None

    # IQR trimming: remove outlier per-year estimates before blending
    if len(results) >= 4:
        k_vals  = sorted(k for k, _, _ in results)
        mid     = len(k_vals) // 2
        lower   = k_vals[:mid];  upper = k_vals[mid:]
        q1 = (lower[len(lower)//2-1] + lower[len(lower)//2]) / 2 if len(lower) % 2 == 0 else lower[len(lower)//2]
        q3 = (upper[len(upper)//2-1] + upper[len(upper)//2]) / 2 if len(upper) % 2 == 0 else upper[len(upper)//2]
        iqr     = q3 - q1
        trimmed = [(k, w, lbl) for k, w, lbl in results if (q1 - 1.5*iqr) <= k <= (q3 + 1.5*iqr)]
        if len(trimmed) >= 2:
            results = trimmed

    total_w   = sum(w for _, w, _ in results)
    w_proj    = sum(k * w for k, w, _ in results) / total_w
    point_est = round(w_proj)

    all_k    = [k for k, _, _ in results]
    max_hist = max((hist_final.get(l, 0) for l in hist_labels), default=point_est)
    low  = max(round(min(all_k)), current_total)
    high = min(round(max(all_k)), max(round(max_hist * 1.4), point_est + 10))

    detail = [(lbl, round(k)) for k, _, lbl in results]
    avg_rate = round(current_total / point_est * 100, 1) if point_est > 0 else 0
    return point_est, low, high, avg_rate, detail


def _avg_velocity_profile(hist_cumulative, hist_final, hist_labels):
    """
    Recency-weighted average normalized cumulative profile from completed years.
    Returns {week: fraction} where fraction = running_total / final_total.
    Used to shape the dashed projection line so divots and accelerations in
    prior years are reflected rather than smoothed away by a logistic curve.
    """
    profiles = []
    for i, label in enumerate(hist_labels):
        hcum  = hist_cumulative.get(label, {})
        final = hist_final.get(label, 0)
        if final == 0 or not hcum:
            continue
        max_w = max(hcum.keys())
        norm_cum, val = {}, 0
        for w in range(max_w + 1):
            if w in hcum:
                val = hcum[w]
            norm_cum[w] = val / final
        profiles.append((norm_cum, i + 1, max_w))  # weight = recency rank

    if not profiles:
        return {}

    total_w  = sum(w for _, w, _ in profiles)
    max_week = max(mw for _, _, mw in profiles)
    avg_cum  = {}
    for w in range(max_week + 1):
        wsum = wtot = 0.0
        for norm_cum, weight, mw in profiles:
            p = norm_cum.get(min(w, mw), 1.0)  # after year's last week → use 1.0
            wsum += p * weight
            wtot += weight
        avg_cum[w] = wsum / wtot if wtot > 0 else 0.0
    return avg_cum


def _backtest_mape(current_week, hist_cumulative, hist_final, hist_labels):
    """Walk-forward backtest: how wrong has the model historically been at this week?"""
    if current_week == 0 or len(hist_labels) < 2:
        return None
    errors = []
    for i in range(1, len(hist_labels)):
        y            = hist_labels[i]
        prior_labels = hist_labels[:i]
        actual       = hist_final.get(y, 0)
        if actual == 0:
            continue
        y_full_cum = hist_cumulative.get(y, {})
        if not y_full_cum:
            continue
        w_at = min(current_week, max(y_full_cum.keys()))
        cum_snap, running = {}, 0
        for w in range(w_at + 1):
            if w in y_full_cum:
                running = y_full_cum[w]
            cum_snap[w] = running
        current_total_snap = cum_snap.get(w_at, 0)
        years_p  = [int(lbl.split()[-1]) for lbl in prior_labels]
        finals_p = [hist_final.get(lbl, 0) for lbl in prior_labels]
        predict_fn, _ = _linear_trend(years_p, finals_p)
        y_year_num = int(y.split()[-1])
        trend_est = max(round(predict_fn(y_year_num)), current_total_snap) if predict_fn else None
        vel = _velocity_projection(cum_snap, hist_cumulative, hist_final, prior_labels)
        log = _logistic_projection(cum_snap, hist_cumulative, hist_final, prior_labels)
        if trend_est is None and vel is None and log is None:
            continue
        # Trend-only path: mirrors compute_blended_projection's early-return
        if vel is None and log is None:
            if trend_est is not None and trend_est > 0:
                errors.append(abs(trend_est - actual) / actual * 100)
            continue
        vel_base  = min((current_week + 1) / 10, 0.85)
        log_share = min(max(current_week - 1, 0) / 8, 0.60)
        vel_w = vel_base * (1 - log_share);  log_w = vel_base * log_share;  trend_w = 1.0 - vel_base
        vel_est = vel[0] if vel else None;  log_est = log[0] if log else None
        if trend_est is None: vel_w += trend_w; trend_w = 0
        if vel_est is None:   log_w += vel_w;   vel_w = 0
        if log_est is None:   vel_w += log_w;   log_w = 0
        total_active_w = trend_w + vel_w + log_w
        if total_active_w == 0: continue
        _t = trend_est or 0
        _v = vel_est   or 0
        _l = log_est   or 0
        point_est = round((trend_w * _t + vel_w * _v + log_w * _l) / total_active_w)
        if point_est > 0:
            errors.append(abs(point_est - actual) / actual * 100)
    return sum(errors) / len(errors) if errors else None


def compute_blended_projection(current_cum_dict, hist_cumulative, hist_final,
                                hist_labels, target_year_num):
    """
    Three-model blend: Trend + Velocity (OLS) + Logistic (S-curve).

    Weight schedule:
      - Trend:    dominates early, fades as real data accumulates
      - Velocity: earns weight from week 1, caps at ~30% of total weight
      - Logistic: starts near 0 (can't fit a curve to 2 points), grows to ~50%+
                  by week 8-10 when the S-curve shape becomes identifiable

    Returns 14-tuple:
      (point_est, low, high, avg_rate, confidence, detail,
       trend_est, vel_est, log_est,
       trend_w_pct, vel_w_pct, log_w_pct,
       log_params, avg_cum_profile)
    or None.
    """
    current_week  = max(current_cum_dict.keys()) if current_cum_dict else 0
    current_total = current_cum_dict.get(current_week, 0) if current_cum_dict else 0

    # ── Trend model ───────────────────────────────────────────────────────────
    years  = [int(lbl.split()[-1]) for lbl in hist_labels]
    finals = [hist_final.get(lbl, 0) for lbl in hist_labels]
    predict_fn, res_std = _linear_trend(years, finals)
    trend_est = max(round(predict_fn(target_year_num)), current_total) if predict_fn else None

    # ── Velocity model ────────────────────────────────────────────────────────
    vel = _velocity_projection(current_cum_dict, hist_cumulative, hist_final, hist_labels)

    # ── Logistic model ────────────────────────────────────────────────────────
    log = _logistic_projection(current_cum_dict, hist_cumulative, hist_final, hist_labels)

    if trend_est is None and vel is None and log is None:
        return None

    # ── Blend weights ─────────────────────────────────────────────────────────
    # Velocity grows from 0% → 85% over 10 weeks (existing schedule)
    vel_base     = min((current_week + 1) / 10, 0.85)
    trend_base   = 1.0 - vel_base
    # Logistic share of the velocity budget: starts 0, grows to 60% by week 8+
    log_share    = min(max(current_week - 1, 0) / 8, 0.60)
    vel_w        = vel_base * (1 - log_share)
    log_w        = vel_base * log_share
    trend_w      = trend_base

    # ── Historical velocity profile (for projection line shaping) ─────────────
    avg_cum_profile = _avg_velocity_profile(hist_cumulative, hist_final, hist_labels)

    # ── Trend-only fallback ───────────────────────────────────────────────────
    if (vel is None and log is None) or current_total == 0:
        low  = max(round(trend_est - 1.5 * res_std), current_total)
        high = round(trend_est + 1.5 * res_std)
        _mape = _backtest_mape(current_week, hist_cumulative, hist_final, hist_labels)
        return trend_est, low, high, None, "Medium", [], trend_est, None, None, 100, 0, 0, None, avg_cum_profile, low, high, None, None, None, None, _mape

    vel_est = vel[0] if vel else None
    log_est = log[0] if log else None

    # If one current-data model is missing, shift its weight to the other
    if vel_est is None:
        log_w += vel_w;  vel_w = 0
    if log_est is None:
        vel_w += log_w;  log_w = 0

    vel_est = vel_est or current_total
    log_est = log_est or current_total

    # ── Blended point estimate ────────────────────────────────────────────────
    point_est = round(trend_w * trend_est + vel_w * vel_est + log_w * log_est)

    # ── Blended confidence band ───────────────────────────────────────────────
    trend_low   = max(round(trend_est - 1.5 * res_std), current_total)
    trend_high  = round(trend_est + 1.5 * res_std)
    vel_low     = vel[1] if vel else vel_est
    vel_high    = vel[2] if vel else vel_est
    log_low     = log[1] if log else log_est
    log_high    = log[2] if log else log_est
    low  = max(round(trend_w * trend_low  + vel_w * vel_low  + log_w * log_low),  current_total)
    high = round(trend_w * trend_high + vel_w * vel_high + log_w * log_high)

    # ── Confidence: historical MAPE from walk-forward backtest ───────────────────
    _mape = _backtest_mape(current_week, hist_cumulative, hist_final, hist_labels)
    if _mape is None:
        confidence = "Medium"
    elif _mape < 10:
        confidence = "High"
    elif _mape < 25:
        confidence = "Medium"
    else:
        confidence = "Low"

    avg_rate   = vel[3] if vel else None
    detail     = vel[4] if vel else []
    log_params = log[3] if log else None

    return (point_est, low, high, avg_rate, confidence, detail,
            trend_est, vel_est, log_est,
            round(trend_w * 100), round(vel_w * 100), round(log_w * 100),
            log_params, avg_cum_profile,
            trend_low, trend_high, vel_low, vel_high, log_low, log_high, _mape)

# ── Load data ─────────────────────────────────────────────────────────────────

print("Loading data...")
fall_years = list(FALL_APPS.keys())
winter_years = list(WINTER_APPS.keys())

fall_app_totals, fall_app_trades, fall_app_locations, fall_app_cumulative, fall_app_start = {}, {}, {}, {}, {}
for label, fname in FALL_APPS.items():
    rows = load_csv(fname)
    fall_app_totals[label] = len(rows)
    fall_app_trades[label] = dict(defaultdict(int, {normalize_trade(r.get("What is your preferred trade?","")): 0 for r in rows}))
    fall_app_locations[label] = dict(defaultdict(int, {normalize_location(r.get("What is your preferred school location?","")): 0 for r in rows}))
    for r in rows:
        fall_app_trades[label][normalize_trade(r.get("What is your preferred trade?",""))] = fall_app_trades[label].get(normalize_trade(r.get("What is your preferred trade?","")),0) + 1
        fall_app_locations[label][normalize_location(r.get("What is your preferred school location?",""))] = fall_app_locations[label].get(normalize_location(r.get("What is your preferred school location?","")),0) + 1
    fall_app_cumulative[label], fall_app_start[label] = cumulative_by_week(rows)
    print(f"  {label}: {len(rows)} apps")

fall_new_reg_totals, fall_new_reg_cumulative, fall_new_reg_start = {}, {}, {}
for label, fname in FALL_NEW_REG.items():
    rows = load_csv(fname)
    fall_new_reg_totals[label] = len(rows)
    fall_new_reg_cumulative[label], fall_new_reg_start[label] = cumulative_by_week(rows)

fall_abc_totals = {label: len(load_csv(fname)) for label, fname in FALL_ABC_REG.items()}

RETURNING_LEVEL_COL = {
    "Fall 2022": "Trade/Level",
    "Fall 2023": "Trade/Level for Fall 2023",
    "Fall 2024": "Trade/Level for Fall 2024",
    "Fall 2025": "Trade/Level for Fall 2025",
    "Fall 2026": "Trade/Level for Fall 2026",
}

fall_returning_totals, fall_returning_cumulative, fall_returning_start = {}, {}, {}
fall_returning_levels = {}   # {year: {"Electrical 2": n, "Electrical 3": n, "Electrical 4": n}}
for label, fname in FALL_RETURNING.items():
    rows = load_csv(fname)
    fall_returning_totals[label] = len(rows)
    fall_returning_cumulative[label], fall_returning_start[label] = cumulative_by_week(rows)
    col = RETURNING_LEVEL_COL.get(label, "")
    level_counts = {}
    for row in rows:
        v = row.get(col, "").strip()
        if v:
            level_counts[v] = level_counts.get(v, 0) + 1
    fall_returning_levels[label] = level_counts


winter_app_totals, winter_app_cumulative, winter_app_start = {}, {}, {}
for label, fname in WINTER_APPS.items():
    rows = load_csv(fname)
    winter_app_totals[label] = len(rows)
    winter_app_cumulative[label], winter_app_start[label] = cumulative_by_week(rows)
winter_new_reg_totals = {label: len(load_csv(fname)) for label, fname in WINTER_NEW_REG.items()}
winter_abc_totals = {label: len(load_csv(fname)) for label, fname in WINTER_ABC_REG.items()}

fall_total_new_reg = {y: fall_new_reg_totals.get(y,0) + fall_abc_totals.get(y,0) for y in fall_years}
winter_total_new_reg = {y: winter_new_reg_totals.get(y,0) + winter_abc_totals.get(y,0) for y in winter_years}

# ── Merged registration dataset ───────────────────────────────────────────────
# Combine all three reg types per year into one list with a Registration_Type column.

REG_TYPE_NEW     = "New Student"
REG_TYPE_ABC     = "New Student (ABC Member)"
REG_TYPE_PARTNER = "New Student (Partner Program)"
REG_TYPE_RETURN  = "Returning Student"

def extract_trade_from_reg(row):
    for f in ("Trade Registering For:", "Trade Registering For", "Trade/Level for Fall 2026",
              "Trade/Level for Fall 2025", "Trade/Level for Fall 2024",
              "Trade/Level for Fall 2023", "Trade/Level for Fall 2022",
              "Trade/Level", "Cornerstone Schools Trade Registering For:",
              "Chance for Life Trade Registering For", "Holly Area Schools Trade Registering For:"):
        v = row.get(f, "").strip()
        if v: return normalize_trade(v)
    return "Unknown"

def extract_location_from_reg(row):
    for f in ("What location?", "What Campus Location Would You Like For The 26/27 School Year?",
              "What Campus Location Would You Like For The 25/26 School Year?",
              "What Campus Location Would You Like For The 24/25 School Year?",
              "What Campus Location Would You Like For The 23/24 School Year?",
              "What is your CURRENT Campus Location?"):
        v = row.get(f, "").strip()
        if v: return normalize_location(v)
    return "Not Specified"

# New-student merged registrations (New + ABC + Partner only — Returning is separate)
new_student_registrations = []  # merged new-student records across all years

fall_combined_reg_cumulative = {}
fall_combined_reg_start = {}
fall_reg_type_counts = {}  # {year: {type: count}}

for label in fall_years:
    rows_new     = load_csv(FALL_NEW_REG[label])
    rows_abc     = load_csv(FALL_ABC_REG[label])
    rows_partner = load_csv(FALL_PARTNER_REG.get(label, ""))

    fall_reg_type_counts[label] = {
        REG_TYPE_NEW:     len(rows_new),
        REG_TYPE_ABC:     len(rows_abc),
        REG_TYPE_PARTNER: len(rows_partner),
    }

    for reg_type, rows in [
        (REG_TYPE_NEW,     rows_new),
        (REG_TYPE_ABC,     rows_abc),
        (REG_TYPE_PARTNER, rows_partner),
    ]:
        for row in rows:
            new_student_registrations.append({
                "Year":              label,
                "Registration_Type": reg_type,
                "Date":              row.get("date", ""),
                "Trade":             extract_trade_from_reg(row),
                "Campus":            extract_location_from_reg(row),
            })

    all_new_rows = rows_new + rows_abc + rows_partner
    fall_combined_reg_cumulative[label], fall_combined_reg_start[label] = cumulative_by_week(all_new_rows)

CHART_TRADES = ["Electrical", "Carpentry", "HVACR", "Plumbing"]

fall_trade_cumulative = {t: {} for t in CHART_TRADES}
fall_trade_start      = {t: {} for t in CHART_TRADES}
fall_trade_totals     = {t: {} for t in CHART_TRADES}

for label in fall_years:
    rows_new     = load_csv(FALL_NEW_REG[label])
    rows_abc     = load_csv(FALL_ABC_REG[label])
    rows_partner = load_csv(FALL_PARTNER_REG.get(label, ""))
    all_rows = rows_new + rows_abc + rows_partner
    for _trade in CHART_TRADES:
        _rows = [r for r in all_rows if extract_trade_from_reg(r) == _trade]
        fall_trade_totals[_trade][label] = len(_rows)
        fall_trade_cumulative[_trade][label], fall_trade_start[_trade][label] = cumulative_by_week(_rows)

# Backward-compat aliases used by retention/funnel code below
fall_elec1_totals     = fall_trade_totals["Electrical"]
fall_elec1_cumulative = fall_trade_cumulative["Electrical"]
fall_elec1_start      = fall_trade_start["Electrical"]

# Stacked type counts for chart (new students only)
fall_reg_new_counts     = [fall_reg_type_counts.get(y, {}).get(REG_TYPE_NEW,     0) for y in fall_years]
fall_reg_abc_counts     = [fall_reg_type_counts.get(y, {}).get(REG_TYPE_ABC,     0) for y in fall_years]
fall_reg_partner_counts = [fall_reg_type_counts.get(y, {}).get(REG_TYPE_PARTNER, 0) for y in fall_years]
fall_reg_new_totals     = [
    fall_reg_type_counts.get(y, {}).get(REG_TYPE_NEW,     0)
    + fall_reg_type_counts.get(y, {}).get(REG_TYPE_ABC,     0)
    + fall_reg_type_counts.get(y, {}).get(REG_TYPE_PARTNER, 0)
    for y in fall_years
]

# Update fall_total_new_reg to include partner
fall_total_new_reg = {y: fall_reg_new_totals[i] for i, y in enumerate(fall_years)}

# ── Chart helpers ─────────────────────────────────────────────────────────────

COLORS = {
    # Sequential blue → highlight orange for the current complete year → red for in-progress
    "Fall 2022": "#bfdbfe",  # light blue (oldest, de-emphasized)
    "Fall 2023": "#60a5fa",  # medium blue
    "Fall 2024": "#2563eb",  # strong blue
    "Fall 2025": "#e69f00",  # Okabe-Ito orange (highlight — current complete year)
    "Fall 2026": "#d55e00",  # Okabe-Ito vermillion (in progress)
    "Winter 2025": "#009e73",  # Okabe-Ito bluish green
    "Winter 2026": "#cc79a7",  # Okabe-Ito reddish purple
}
# Okabe-Ito inspired palette — proven for categorical distinctiveness & accessibility
TRADE_COLORS = {
    "Electrical":      "#0072b2",  # Okabe-Ito blue
    "Carpentry":       "#56b4e9",  # Okabe-Ito sky blue
    "HVACR":           "#e69f00",  # Okabe-Ito orange
    "Welding":         "#009e73",  # Okabe-Ito bluish green
    "Intro / Pre-App": "#cc79a7",  # Okabe-Ito reddish purple
    "CCL":             "#d55e00",  # Okabe-Ito vermillion
    "Plumbing":        "#7b2d8b",  # purple (F0E442 yellow illegible on white)
    "Unknown":         "#cbd5e1",
}
LOC_COLORS = {
    "Sterling Heights": "#0072b2",
    "Madison Heights":  "#56b4e9",
    "Westland":         "#e69f00",
    "Monroe":           "#009e73",
    "Lapeer":           "#cc79a7",
    "Holly":            "#d55e00",
    "Not Specified":    "#e2e8f0",
}

def build_cumulative_datasets(cumulative_dict, year_list, start_dates=None, min_weeks=0):
    all_weeks = set()
    for y in year_list:
        all_weeks.update(cumulative_dict.get(y, {}).keys())
    max_weeks = max(max(all_weeks) + 1 if all_weeks else 1, min_weeks)

    # Use the most recent year's actual form-open date for calendar labels
    ref_start = None
    if start_dates:
        ref_start = next((start_dates[y] for y in reversed(year_list) if start_dates.get(y)), None)
    if ref_start:
        labels = [(ref_start + timedelta(weeks=i)).strftime("%-m/%-d") for i in range(max_weeks)]
    else:
        labels = [f"Wk {i+1}" for i in range(max_weeks)]

    datasets = []
    for y in year_list:
        cum = cumulative_dict.get(y, {})
        if not cum: continue
        last_known_week = max(cum.keys())
        data, val = [], 0
        for w in range(max_weeks):
            if w in cum: val = cum[w]
            data.append(val)
        datasets.append({
            "label": y, "data": data,
            "lastKnownWeek": last_known_week,
            "borderColor": COLORS.get(y, "#888"),
            "backgroundColor": COLORS.get(y, "#888") + "40",
            "fill": True, "tension": 0.4, "pointRadius": 3, "borderWidth": 2.5,
        })
    return labels, datasets

all_trades_counter = defaultdict(int)
for td in fall_app_trades.values():
    for t, c in td.items():
        all_trades_counter[t] += c
all_trades = [t for t, _ in sorted(all_trades_counter.items(), key=lambda x: -x[1]) if t != "Unknown"]
all_locs = ["Sterling Heights", "Madison Heights", "Westland", "Monroe", "Lapeer", "Holly", "Not Specified"]

def school_start_week(start_date, year_label):
    """Return week index (0-based) of Sept 3 relative to form open date, or -1 if unknown."""
    if not start_date:
        return -1
    year = int(year_label.split()[-1])
    school_date = datetime(year, 9, 3)
    days = (school_date - start_date).days
    return days // 7 if days >= 0 else -1

app_school_start_idx     = school_start_week(fall_app_start.get("Fall 2026"), "Fall 2026")
new_reg_school_start_idx = school_start_week(fall_combined_reg_start.get("Fall 2026"), "Fall 2026")
ret_school_start_idx     = school_start_week(fall_returning_start.get("Fall 2026"), "Fall 2026")

app_cum_labels, app_cum_datasets = build_cumulative_datasets(fall_app_cumulative, fall_years, fall_app_start)
new_reg_cum_labels, new_reg_cum_datasets = build_cumulative_datasets(fall_combined_reg_cumulative, fall_years, fall_combined_reg_start)
# min_weeks ensures x-axis extends to school-start even when prior-year forms opened late
ret_min_weeks = ret_school_start_idx + 2 if ret_school_start_idx > 0 else 0
ret_cum_labels, ret_cum_datasets = build_cumulative_datasets(fall_returning_cumulative, fall_years, fall_returning_start, min_weeks=ret_min_weeks)

elec1_school_start_idx = school_start_week(fall_elec1_start.get("Fall 2026"), "Fall 2026")
elec1_min_weeks = elec1_school_start_idx + 2 if elec1_school_start_idx > 0 else 0
elec1_cum_labels, elec1_cum_datasets = build_cumulative_datasets(fall_elec1_cumulative, fall_years, fall_elec1_start, min_weeks=elec1_min_weeks)

trade_cum_data = {}
for _trade in CHART_TRADES:
    _idx = school_start_week(fall_trade_start[_trade].get("Fall 2026"), "Fall 2026")
    _min = _idx + 2 if _idx > 0 else 0
    _labels, _datasets = build_cumulative_datasets(
        fall_trade_cumulative[_trade], fall_years, fall_trade_start[_trade], min_weeks=_min
    )
    if _datasets:  # skip trades with no registration data
        trade_cum_data[_trade] = {"labels": _labels, "datasets": _datasets, "schoolStartIdx": _idx}

def stacked_datasets(data_by_year, keys_list, colors_map):
    datasets = []
    for k in keys_list:
        data = [data_by_year.get(y, {}).get(k, 0) for y in fall_years]
        if sum(data) == 0: continue
        datasets.append({"label": k, "data": data, "backgroundColor": colors_map.get(k, "#aaa"), "borderRadius": 3})
    return datasets

trade_datasets = stacked_datasets(fall_app_trades, all_trades, TRADE_COLORS)
loc_datasets = stacked_datasets(fall_app_locations, all_locs, LOC_COLORS)

# Registration type colors (new students only)
REG_TYPE_COLORS = {
    REG_TYPE_NEW:     "#0072b2",  # Okabe-Ito blue
    REG_TYPE_ABC:     "#e69f00",  # Okabe-Ito orange
    REG_TYPE_PARTNER: "#cc79a7",  # Okabe-Ito reddish purple
}

reg_type_stacked_datasets = json.dumps([
    {"label": t, "data": counts, "backgroundColor": REG_TYPE_COLORS[t],
     "borderRadius": 4, "borderSkipped": False}
    for t, counts in [
        (REG_TYPE_NEW,     fall_reg_new_counts),
        (REG_TYPE_ABC,     fall_reg_abc_counts),
        (REG_TYPE_PARTNER, fall_reg_partner_counts),
    ]
])

# Aggregate totals across all years for the doughnut
reg_type_agg_json = json.dumps({
    REG_TYPE_NEW:     sum(fall_reg_new_counts),
    REG_TYPE_ABC:     sum(fall_reg_abc_counts),
    REG_TYPE_PARTNER: sum(fall_reg_partner_counts),
})
reg_type_colors_json = json.dumps(REG_TYPE_COLORS)
reg_partner_total = sum(fall_reg_partner_counts)
reg_partner_years = ", ".join(y for y in fall_years if fall_reg_type_counts.get(y, {}).get(REG_TYPE_PARTNER, 0) > 0) or "none yet"

# Registration type table rows HTML
reg_type_table_rows = ""
for y in fall_years:
    tc  = fall_reg_type_counts.get(y, {})
    n   = tc.get(REG_TYPE_NEW, 0)
    abc = tc.get(REG_TYPE_ABC, 0)
    par = tc.get(REG_TYPE_PARTNER, 0)
    tot = n + abc + par
    row_class = "highlight-row" if "2026" in y else ""
    reg_type_table_rows += f"""<tr class="{row_class}">
      <td><strong>{y}</strong></td>
      <td><span class="chip chip-blue">{n:,}</span></td>
      <td><span class="chip chip-orange">{abc:,}</span></td>
      <td><span class="chip" style="background:#f3e8ff;color:#6b21a8;">{par:,}</span></td>
      <td><strong>{tot:,}</strong></td>
      <td style="font-size:0.75rem;color:var(--text-muted);">
        SEMCA New Student Reg &bull; ABCSEMI Member Reg &bull; Partner Program Reg
      </td>
    </tr>"""

# ── Unified semester list (fall + winter) ordered chronologically ──
_today = datetime.now()

def _sem_start(label):
    yr = int(label.split()[-1])
    return datetime(yr, 1, 5) if "Winter" in label else datetime(yr, 9, 3)

def _sem_totals(label):
    return winter_app_totals.get(label, 0) if "Winter" in label else fall_app_totals.get(label, 0)

def _sem_cumulative(label):
    return winter_app_cumulative.get(label, {}) if "Winter" in label else fall_app_cumulative.get(label, {})

def _sem_start_date(label):
    return winter_app_start.get(label) if "Winter" in label else fall_app_start.get(label)

all_semesters = sorted(fall_years + winter_years, key=_sem_start)

# Active = most recent semester with any data
active_year   = all_semesters[-1]
for _y in reversed(all_semesters):
    if _sem_totals(_y) > 0:
        active_year = _y
        break

_aidx         = all_semesters.index(active_year)
complete_year = all_semesters[_aidx - 1] if _aidx >= 1 else active_year
prior_year    = all_semesters[_aidx - 2] if _aidx >= 2 else all_semesters[0]

# For KPI cards always use most recent complete FALL year
complete_fall = next((y for y in reversed(fall_years) if y != active_year and fall_app_totals.get(y,0) > 0), fall_years[-2])
prior_fall    = fall_years[fall_years.index(complete_fall) - 1] if fall_years.index(complete_fall) >= 1 else fall_years[0]

active_year_num       = int(active_year.split()[-1])
active_semester_start = _sem_start(active_year)
active_is_winter      = "Winter" in active_year
active_year_short     = active_year.replace("Fall ", "F'").replace("Winter ", "W'")
complete_year_short   = complete_fall.replace("Fall ", "F'")
prior_year_short      = prior_fall.replace("Fall ", "F'")

# Pace comparison — current week of active semester vs same type (fall vs fall, winter vs winter)
active_cum     = _sem_cumulative(active_year)
fall_2026_week = max(active_cum.keys()) if active_cum else 0   # keep name for template compat
same_type      = winter_years if active_is_winter else fall_years
compare_years  = [y for y in same_type if y != active_year and _sem_totals(y) > 0][-3:]
pace_at_same_week = {}
for y in compare_years:
    cum = _sem_cumulative(y)
    val = 0
    for ww in range(fall_2026_week, -1, -1):
        if ww in cum:
            val = cum[ww]
            break
    pace_at_same_week[y] = val

# Summary numbers — KPI cards always use fall data; live tracker uses active semester
app_26 = _sem_totals(active_year)             # in-progress (fall or winter)
app_25 = fall_app_totals.get(complete_fall, 0)
app_24 = fall_app_totals.get(prior_fall,    0)
# ── Cohort dropout / retention analysis (E2→E3, E3→E4) ──────────────────────
_ret_years = [y for y in fall_years if y in fall_returning_levels]
def _make_transition(from_year, to_year, from_level, to_level, n_from, n_to):
    if n_from == 0:
        return None
    retained = min(n_to, n_from)
    dropped  = n_from - retained
    return {
        "from_year": from_year, "to_year": to_year,
        "from_level": from_level, "to_level": to_level,
        "n_from": n_from, "n_to": n_to,
        "retained": retained, "dropped": dropped,
        "pct_ret":  round(retained / n_from * 100, 1),
        "pct_drop": round(dropped  / n_from * 100, 1),
        "partial": (to_year == active_year),
    }

cohort_transitions = []
for i in range(len(_ret_years) - 1):
    yr_from = _ret_years[i]
    yr_to   = _ret_years[i + 1]
    lvls_to = fall_returning_levels.get(yr_to, {})

    # Year 1 → Year 2: new Electrical students in yr_from vs Electrical 2 returning in yr_to
    t = _make_transition(yr_from, yr_to, "Electrical 1 (New)", "Electrical 2",
                         fall_elec1_totals.get(yr_from, 0), lvls_to.get("Electrical 2", 0))
    if t: cohort_transitions.append(t)

    # Year 2 → 3 and Year 3 → 4 (returning-to-returning)
    lvls_from = fall_returning_levels.get(yr_from, {})
    for from_lv, to_lv in [("Electrical 2", "Electrical 3"), ("Electrical 3", "Electrical 4")]:
        t = _make_transition(yr_from, yr_to, from_lv, to_lv,
                             lvls_from.get(from_lv, 0), lvls_to.get(to_lv, 0))
        if t: cohort_transitions.append(t)

# ── Cohort funnel: for each starting year track E1→E2→E3→E4 counts ──────────
cohort_funnels = {}
for i, yr_start in enumerate(fall_years):
    yr2 = fall_years[i+1] if i+1 < len(fall_years) else None
    yr3 = fall_years[i+2] if i+2 < len(fall_years) else None
    yr4 = fall_years[i+3] if i+3 < len(fall_years) else None
    cohort_funnels[yr_start] = {
        "e1": fall_elec1_totals.get(yr_start, 0),        "e1_year": yr_start,
        "e2": fall_returning_levels.get(yr2,{}).get("Electrical 2",0) if yr2 else None, "e2_year": yr2, "e2_partial": yr2==active_year,
        "e3": fall_returning_levels.get(yr3,{}).get("Electrical 3",0) if yr3 else None, "e3_year": yr3, "e3_partial": yr3==active_year,
        "e4": fall_returning_levels.get(yr4,{}).get("Electrical 4",0) if yr4 else None, "e4_year": yr4, "e4_partial": yr4==active_year,
    }

# ── Enrollment by level per year (grouped bar data) ──────────────────────────
_level_bar_labels = [y.replace("Fall ", "F'") for y in fall_years]
_level_bar_e1 = [fall_elec1_totals.get(y, 0) for y in fall_years]
_level_bar_e2 = [fall_returning_levels.get(y, {}).get("Electrical 2", 0) for y in fall_years]
_level_bar_e3 = [fall_returning_levels.get(y, {}).get("Electrical 3", 0) for y in fall_years]
_level_bar_e4 = [fall_returning_levels.get(y, {}).get("Electrical 4", 0) for y in fall_years]

# ── Retention trend lines data ────────────────────────────────────────────────
_ret_trend_labels = []
_ret_trend_e1e2, _ret_trend_e2e3, _ret_trend_e3e4 = [], [], []
for ct in cohort_transitions:
    label_str = f"'{ct['from_year'].replace('Fall ','')[2:]}→'{ct['to_year'].replace('Fall ','')[2:]}"
    if ct["from_level"] == "Electrical 1 (New)":
        _ret_trend_labels.append(label_str)
        _ret_trend_e1e2.append(ct["pct_ret"] if not ct["partial"] else None)
    elif ct["from_level"] == "Electrical 2":
        _ret_trend_e2e3.append(ct["pct_ret"] if not ct["partial"] else None)
    elif ct["from_level"] == "Electrical 3":
        _ret_trend_e3e4.append(ct["pct_ret"] if not ct["partial"] else None)

# ── Live-refresh form ID lookup ───────────────────────────────────────────────
_summary_path = os.environ.get("JOTFORM_SUMMARY_PATH", os.path.expanduser("~/jotform_summary.json"))
_form_id_map  = {}
if os.path.exists(_summary_path):
    with open(_summary_path) as _f:
        for _entry in json.load(_f):
            _form_id_map[_entry["title"]] = _entry["form_id"]

_yr = active_year  # e.g. "Fall 2026"
_live_form_ids = {
    "app":       _form_id_map.get(f"{_yr} SEMCA Application", ""),
    "new_reg":   _form_id_map.get(f"{_yr} SEMCA New Student Class Registration", ""),
    "abc_reg":   _form_id_map.get(f"{_yr} ABCSEMI Member Company New Student Class Registration", ""),
    "partner":   _form_id_map.get(f"{_yr} Partner Program Registration", ""),
    "returning": _form_id_map.get(f"{_yr} SEMCA Returning Student Registration", ""),
}

app_22 = fall_app_totals.get(fall_years[0], 0)
app_23 = fall_app_totals.get(fall_years[1], 0) if len(fall_years) > 1 else 0
new_25 = fall_total_new_reg.get(complete_fall, 0)
new_24 = fall_total_new_reg.get(prior_fall,   0)
ret_22 = fall_returning_totals.get(fall_years[0], 0)
ret_24 = fall_returning_totals.get(prior_fall,    0)
ret_25 = fall_returning_totals.get(complete_fall, 0)
ret_26 = fall_returning_totals.get(active_year,   0)
w25_app = winter_app_totals.get("Winter 2025", 0)
w26_app = winter_app_totals.get("Winter 2026", 0)
elec_pct_25 = round(fall_app_trades.get(complete_fall, {}).get("Electrical", 0) / max(app_25, 1) * 100, 1)

# Ring progress
ring_new_pct  = round(new_25 / max(app_25, 1) * 100)
ring_ret_pct  = min(round(ret_25 / max(new_24 + ret_24, 1) * 100), 100)
ring_live_pct = min(round(app_26 / max(app_25, 1) * 100), 100)

# Hero year pills — built after projections (so we can show projected totals for active year)
# placeholder: filled in below after compute_blended_projection calls
hero_pills_html = ""

# Pace banner comparison rows
pace_comparison_html = ""
for _y in reversed(compare_years):
    _val     = pace_at_same_week.get(_y, 0)
    _delta   = app_26 - _val
    _pct_str = pct_change(_val, app_26) if _val > 0 else "—"
    _color   = "#16a34a" if _delta >= 0 else "#dc2626"
    _icon    = "▲" if _delta >= 0 else "▼"
    _short   = _y.replace("Fall ", "F'")
    pace_comparison_html += f"""
    <div style="display:flex;align-items:center;justify-content:space-between;font-size:0.82rem;">
      <span style="color:#92400e;font-weight:600;">{_short} had {_val:,}</span>
      <span style="font-weight:800;color:{_color};">{_icon} {_pct_str}</span>
    </div>"""

# Pre-compute summary table rows HTML
summary_table_rows = ""
for y in fall_years:
    elec_count = fall_app_trades.get(y, {}).get("Electrical", 0)
    total_apps = max(fall_app_totals.get(y, 1), 1)
    elec_pct_val = round(elec_count / total_apps * 100, 1)
    elec_pct_bar = round(elec_count / total_apps * 100)
    row_class = "highlight-row" if "2026" in y else ""
    tag_class = "tag-live" if "2026" in y else "tag-done"
    tag_text = "In Progress" if "2026" in y else "Complete"
    tc = fall_reg_type_counts.get(y, {})
    n_new     = tc.get(REG_TYPE_NEW, 0)
    n_abc     = tc.get(REG_TYPE_ABC, 0)
    n_partner = tc.get(REG_TYPE_PARTNER, 0)
    n_ret     = fall_returning_totals.get(y, 0)
    total_enrolled = n_new + n_abc + n_partner + n_ret
    summary_table_rows += f"""<tr class="{row_class}">
      <td><strong>{y}</strong></td>
      <td>{fall_app_totals.get(y, 0):,}</td>
      <td>{n_new:,}</td>
      <td>{n_abc:,}</td>
      <td>{n_partner:,}</td>
      <td>{n_ret:,}</td>
      <td><strong>{total_enrolled:,}</strong></td>
      <td><div class="pct-bar"><div class="pct-bar-bg"><div class="pct-bar-fill" style="width:{elec_pct_bar}%;"></div></div><span>{elec_pct_val}%</span></div></td>
      <td><span class="tag {tag_class}">{tag_text}</span></td>
    </tr>"""

# ── Statistical Forecast ──────────────────────────────────────────────────────

completed_fall_labels = [y for y in fall_years if y != active_year and fall_app_totals.get(y, 0) > 0]
proj_apps = proj_new_reg = proj_returning = None

if not active_is_winter and completed_fall_labels:
    proj_apps = compute_blended_projection(
        fall_app_cumulative.get(active_year, {}),
        fall_app_cumulative, fall_app_totals, completed_fall_labels, active_year_num
    )
    proj_new_reg = compute_blended_projection(
        fall_combined_reg_cumulative.get(active_year, {}),
        fall_combined_reg_cumulative, fall_total_new_reg, completed_fall_labels, active_year_num
    )
    proj_returning = compute_blended_projection(
        fall_returning_cumulative.get(active_year, {}),
        fall_returning_cumulative, fall_returning_totals, completed_fall_labels, active_year_num
    )

# ── Hero year pills (built after projections so active year shows projected total) ──
_active_fall_idx = fall_years.index(active_year) if (active_year in fall_years) else -1

# Projected totals array for JS (actual for completed years, projected for active year)
_proj_app_list = [fall_app_totals.get(y, 0) for y in fall_years]
_proj_new_list = [fall_total_new_reg.get(y, 0) for y in fall_years]
_proj_ret_list = [fall_returning_totals.get(y, 0) for y in fall_years]
if _active_fall_idx >= 0 and not active_is_winter:
    if proj_apps:      _proj_app_list[_active_fall_idx] = proj_apps[0]
    if proj_new_reg:   _proj_new_list[_active_fall_idx] = proj_new_reg[0]
    if proj_returning: _proj_ret_list[_active_fall_idx] = proj_returning[0]

# ── Cohort dropout table rows ────────────────────────────────────────────────
cohort_rows_html = ""
_prev_transition = None
for ct in cohort_transitions:
    _sep = 'border-top:2px solid #e2e8f0;' if ct["from_level"] != _prev_transition else ''
    _prev_transition = ct["from_level"]
    _partial_note = ' <span style="font-size:0.72rem;color:#94a3b8;">(in progress)</span>' if ct["partial"] else ''
    _drop_color = "#ef4444" if ct["pct_drop"] > 20 else "#f97316" if ct["pct_drop"] > 10 else "#64748b"
    cohort_rows_html += f'''        <tr style="border-bottom:1px solid #f1f5f9;{_sep}">
          <td style="padding:10px 14px;font-weight:600;color:#1e3a5f;">{ct["from_level"]} → {ct["to_level"]}</td>
          <td style="padding:10px 14px;text-align:center;color:#64748b;">{ct["from_year"]} → {ct["to_year"]}{_partial_note}</td>
          <td style="padding:10px 14px;text-align:right;">{ct["n_from"]:,}</td>
          <td style="padding:10px 14px;text-align:right;">{ct["n_to"]:,}</td>
          <td style="padding:10px 14px;text-align:right;font-weight:700;color:{_drop_color};">{ct["dropped"]:,}</td>
          <td style="padding:10px 14px;text-align:right;font-weight:700;color:{_drop_color};">{ct["pct_drop"]}%</td>
          <td style="padding:10px 14px;text-align:right;font-weight:700;color:#16a34a;">{ct["pct_ret"]}%</td>
        </tr>\n'''

# ── Cohort year pills (for funnel selector) ───────────────────────────────────
_cohort_start_years = [y for y in fall_years if cohort_funnels.get(y, {}).get("e1", 0) > 0]
cohort_year_pills_html = ""
for _i, _y in enumerate(_cohort_start_years):
    _active = 'background:#1e3a5f;color:white;border-color:#1e3a5f;' if _i == 0 else 'background:#f8fafc;color:#475569;border-color:#e2e8f0;'
    cohort_year_pills_html += (
        f'      <button class="cohort-yr-pill" data-year="{_y}" onclick="selectCohortYear(this)" '
        f'style="padding:6px 14px;font-size:0.8rem;font-weight:600;border-radius:20px;cursor:pointer;'
        f'border:1.5px solid;transition:all 0.18s;{_active}">{_y}</button>\n'
    )

hero_pills_html = ""
for _y in fall_years:
    _active_cls = 'active' if _y == complete_fall else ''
    _idx        = fall_years.index(_y)
    _live_cls = "live" if _y == active_year else ""
    if _y == active_year:
        _label = f'<span class="live-dot"></span>{_y}'
    else:
        _label = _y
    hero_pills_html += f'<button class="hero-year-pill {_active_cls} {_live_cls}" data-idx="{_idx}">{_label}</button>\n      '


def _forecast_metric_block(label, fa_icon, current, proj_result):
    if proj_result is None:
        return (
            f'<div style="background:#f8fafc;border-radius:10px;padding:20px;border:1.5px solid #e2e8f0;">'
            f'<div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;color:#64748b;font-weight:600;">'
            f'<i class="fa {fa_icon}" style="margin-right:5px;"></i>{label}</div>'
            f'<div style="color:#94a3b8;margin-top:12px;font-size:0.85rem;">Not enough data yet</div>'
            f'</div>'
        )

    (point_est, low, high, avg_rate, confidence, detail,
     trend_est, vel_est, log_est, trend_w_pct, vel_w_pct, log_w_pct,
     _lp, _ap, trend_low, trend_high, vel_low, vel_high, log_low, log_high, mape_val) = proj_result
    pct_done  = min(round(current / point_est * 100) if point_est > 0 else 0, 100)
    conf_map  = {
        "High":   ("#dcfce7", "#15803d", "fa-circle-check"),
        "Medium": ("#fff7ed", "#c2410c", "fa-circle-exclamation"),
        "Low":    ("#fef2f2", "#b91c1c", "fa-circle-xmark"),
    }
    c_bg, c_col, c_ico = conf_map.get(confidence, conf_map["Low"])
    mape_str  = f"{mape_val:.1f}%" if mape_val is not None else "N/A"

    def _ci_bar(lo, pt, hi, col):
        """Mini inline range bar: low ---|---point---|--- high"""
        if lo is None or hi is None or hi <= lo:
            return ""
        span  = hi - lo
        p_pct = min(max(round((pt - lo) / span * 100), 0), 100)
        return (
            f'<div style="position:relative;height:6px;background:#e8edf2;border-radius:3px;margin:4px 0 1px;">'
            f'<div style="position:absolute;left:{p_pct}%;top:-3px;width:2px;height:12px;background:{col};border-radius:1px;transform:translateX(-50%);"></div>'
            f'<div style="position:absolute;left:0;width:{p_pct}%;height:100%;background:{col};opacity:0.25;border-radius:3px 0 0 3px;"></div>'
            f'<div style="position:absolute;left:{p_pct}%;width:{100-p_pct}%;height:100%;background:{col};opacity:0.12;border-radius:0 3px 3px 0;"></div>'
            f'</div>'
        )

    def _model_block(title, col, bg, est, lo, hi, w_pct, warming=False):
        if est is None:
            return f'<div style="background:{bg};border-radius:8px;padding:10px 12px;"><div style="font-size:0.6rem;color:{col};font-weight:700;text-transform:uppercase;letter-spacing:0.4px;">{title} ({w_pct}%)</div><div style="font-size:0.78rem;color:#94a3b8;margin-top:4px;">—</div></div>'
        if warming:
            est_str = "Warming up&hellip;"
            ci_str  = ""
            bar     = ""
        else:
            est_str = f"{est:,}"
            ci_str  = f'<div style="font-size:0.65rem;color:#64748b;margin-top:2px;">{lo:,} &ndash; {hi:,}</div>' if lo is not None and hi is not None else ""
            bar     = _ci_bar(lo, est, hi, col)
        return (
            f'<div style="background:{bg};border-radius:8px;padding:10px 12px;">'
            f'<div style="font-size:0.6rem;color:{col};font-weight:700;text-transform:uppercase;letter-spacing:0.4px;">{title} ({w_pct}%)</div>'
            f'<div style="font-size:1rem;font-weight:800;color:#1e3a5f;margin-top:3px;">{est_str}</div>'
            f'{ci_str}{bar}'
            f'</div>'
        )

    model_row = (
        f'<div style="margin-top:14px;display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">'
        + _model_block("Trend",    "#3b82f6", "#eff6ff", trend_est, trend_low, trend_high, trend_w_pct)
        + _model_block("Velocity", "#ea580c", "#fff7ed", vel_est,   vel_low,   vel_high,   vel_w_pct)
        + _model_block("Logistic", "#16a34a", "#f0fdf4", log_est,   log_low,   log_high,   log_w_pct, warming=(log_w_pct < 5))
        + f'</div>'
    )

    detail_rows = "".join(
        f'<tr><td style="color:#94a3b8;padding:2px 0;">{lbl}</td>'
        f'<td style="font-weight:600;text-align:right;">&#8594; {r:,}</td></tr>'
        for lbl, r in detail
    )

    # ── Two-row range display: planning range (PI) vs model precision (CI) ──
    if mape_val is not None:
        pi_low  = round(point_est * (1 - mape_val / 100))
        pi_high = round(point_est * (1 + mape_val / 100))
    else:
        pi_low, pi_high = low, high

    def _range_row(label, label_color, lo, pt, hi, bar_color, tooltip):
        if lo is None or hi is None or hi <= lo:
            return ""
        outer_lo = min(pi_low, low) - 5
        outer_hi = max(pi_high, high) + 5
        outer_span = max(outer_hi - outer_lo, 1)
        bar_left  = round((lo - outer_lo) / outer_span * 100)
        bar_width = round((hi - lo) / outer_span * 100)
        pt_left   = round((pt - outer_lo) / outer_span * 100)
        return (
            f'<div style="margin-bottom:10px;" title="{tooltip}">'
            f'<div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">'
            f'<span style="font-size:0.66rem;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;'
            f'color:{label_color};width:130px;flex-shrink:0;">{label}</span>'
            f'<span style="font-size:0.72rem;color:#475569;font-weight:600;">{lo:,}</span>'
            f'<div style="flex:1;position:relative;height:8px;background:#f1f5f9;border-radius:4px;">'
            f'<div style="position:absolute;left:{bar_left}%;width:{bar_width}%;height:100%;'
            f'background:{bar_color};opacity:0.28;border-radius:4px;"></div>'
            f'<div style="position:absolute;left:{bar_left}%;width:{bar_width}%;height:100%;'
            f'border:1.5px solid {bar_color};border-radius:4px;box-sizing:border-box;"></div>'
            f'<div style="position:absolute;left:{pt_left}%;top:-3px;width:2px;height:14px;'
            f'background:#1e3a5f;border-radius:1px;transform:translateX(-50%);"></div>'
            f'</div>'
            f'<span style="font-size:0.72rem;color:#475569;font-weight:600;">{hi:,}</span>'
            f'</div>'
            f'</div>'
        )

    # PI is the primary planning range; CI is a secondary footnote
    outer_lo    = min(pi_low, low) - 5
    outer_hi    = max(pi_high, high) + 5
    outer_span  = max(outer_hi - outer_lo, 1)
    pi_bar_left  = round((pi_low  - outer_lo) / outer_span * 100)
    pi_bar_width = round((pi_high - pi_low)   / outer_span * 100)
    pt_left      = round((point_est - outer_lo) / outer_span * 100)
    ci_bar_left  = round((low  - outer_lo) / outer_span * 100)
    ci_bar_width = round((high - low)      / outer_span * 100)

    ci_range_bar = (
        f'<div style="margin-top:18px;padding:16px 18px;background:#f0fdf4;border-radius:10px;border:1.5px solid #bbf7d0;">'
        # Header
        f'<div style="font-size:0.68rem;font-weight:700;color:#15803d;text-transform:uppercase;letter-spacing:0.6px;margin-bottom:6px;">'
        f'<i class="fa fa-triangle-exclamation" style="margin-right:4px;"></i>Plan for this range</div>'
        # Big PI numbers
        f'<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">'
        f'<span style="font-size:1.6rem;font-weight:800;color:#15803d;letter-spacing:-0.5px;">{pi_low:,}</span>'
        f'<span style="color:#86efac;font-size:1.2rem;">—</span>'
        f'<span style="font-size:1.6rem;font-weight:800;color:#15803d;letter-spacing:-0.5px;">{pi_high:,}</span>'
        f'<span style="font-size:0.75rem;color:#16a34a;margin-left:4px;">±MAPE ({mape_str})</span>'
        f'</div>'
        # PI bar
        f'<div style="position:relative;height:10px;background:#dcfce7;border-radius:5px;margin-bottom:14px;">'
        f'<div style="position:absolute;left:{pi_bar_left}%;width:{pi_bar_width}%;height:100%;background:#16a34a;opacity:0.3;border-radius:5px;"></div>'
        f'<div style="position:absolute;left:{pi_bar_left}%;width:{pi_bar_width}%;height:100%;border:2px solid #16a34a;border-radius:5px;box-sizing:border-box;"></div>'
        f'<div style="position:absolute;left:{pt_left}%;top:-4px;width:3px;height:18px;background:#1e3a5f;border-radius:2px;transform:translateX(-50%);"></div>'
        f'</div>'
        # CI footnote
        f'<details style="margin-top:2px;">'
        f'<summary style="font-size:0.68rem;color:#94a3b8;cursor:pointer;user-select:none;list-style:none;">'
        f'<i class="fa fa-chevron-right" style="font-size:0.6rem;margin-right:4px;"></i>'
        f'Model precision (CI): {low:,} – {high:,} <span style="font-style:italic;">(narrower — parameter uncertainty only, not planning range)</span>'
        f'</summary>'
        f'<div style="margin-top:8px;position:relative;height:7px;background:#f1f5f9;border-radius:4px;">'
        f'<div style="position:absolute;left:{ci_bar_left}%;width:{ci_bar_width}%;height:100%;background:#3b82f6;opacity:0.25;border-radius:4px;"></div>'
        f'<div style="position:absolute;left:{ci_bar_left}%;width:{ci_bar_width}%;height:100%;border:1.5px solid #3b82f6;border-radius:4px;box-sizing:border-box;"></div>'
        f'<div style="position:absolute;left:{pt_left}%;top:-3px;width:2px;height:13px;background:#1e3a5f;border-radius:1px;transform:translateX(-50%);"></div>'
        f'</div>'
        f'<div style="font-size:0.65rem;color:#94a3b8;margin-top:4px;">CI reflects model parameter uncertainty only — not how wrong the model can be on a real year.</div>'
        f'</details>'
        f'</div>'
    )

    return (
        f'<div style="background:#f8fafc;border-radius:12px;padding:22px;border:1.5px solid #e2e8f0;">'
        f'<div style="font-size:0.7rem;text-transform:uppercase;letter-spacing:1px;color:#64748b;font-weight:600;margin-bottom:10px;">'
        f'<i class="fa {fa_icon}" style="margin-right:5px;"></i>{label}</div>'
        f'<div style="display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;">'
        f'<span style="font-size:0.88rem;color:#64748b;">{current:,} now</span>'
        f'<span style="color:#cbd5e1;font-size:1rem;">&#8594;</span>'
        f'<span style="font-size:2.4rem;font-weight:800;color:#1e3a5f;letter-spacing:-1px;">{point_est:,}</span>'
        f'<span style="font-size:0.88rem;color:#64748b;">projected</span>'
        f'<span style="font-size:0.72rem;padding:3px 9px;border-radius:20px;font-weight:600;background:{c_bg};color:{c_col};margin-left:4px;">'
        f'<i class="fa {c_ico}" style="margin-right:3px;"></i>{confidence} Confidence</span>'
        f'</div>'
        f'{ci_range_bar}'
        f'{model_row}'
        f'<div style="margin-top:14px;">'
        f'<div style="height:6px;background:#e2e8f0;border-radius:3px;overflow:hidden;">'
        f'<div style="height:100%;width:{pct_done}%;background:linear-gradient(90deg,#3b82f6,#60a5fa);border-radius:3px;"></div>'
        f'</div>'
        f'<div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">{pct_done}% of projected total reached</div>'
        f'</div>'
        f'<details style="margin-top:12px;">'
        f'<summary style="font-size:0.72rem;color:#94a3b8;cursor:pointer;user-select:none;">Velocity model — per-year OLS fits</summary>'
        f'<table style="width:100%;margin-top:6px;font-size:0.72rem;border-collapse:collapse;">{detail_rows}</table>'
        f'</details>'
        f'</div>'
    )


# Extend the active year's cumulative data with the projected trajectory.
# Shape is driven by the recency-weighted historical velocity profile so that
# seasonal divots and surges from prior years are reflected in the dashed line.
def _extend_with_projection(datasets, active_label, proj_final, school_start_idx,
                             log_params=None, avg_cum_profile=None):
    for ds in datasets:
        if ds["label"] != active_label or proj_final is None:
            continue
        lkw      = ds["lastKnownWeek"]
        cur_val  = ds["data"][lkw]
        n        = len(ds["data"])
        ramp_end = school_start_idx if (0 < school_start_idx < n) else n - 1
        if ramp_end <= lkw or proj_final <= cur_val:
            continue

        # Priority 1: historical average velocity profile (preserves divots / surges)
        use_hist     = False
        use_logistic = False
        p_lkw = p_end = denom = 0.0
        max_pw = 0

        if avg_cum_profile:
            max_pw  = max(avg_cum_profile.keys())
            p_lkw   = avg_cum_profile.get(lkw, 0.0)
            ref_end = min(ramp_end, max_pw)
            p_end   = avg_cum_profile.get(ref_end, 1.0)
            denom   = p_end - p_lkw
            use_hist = denom > 0.001  # skip degenerate (flat or inverted) profiles

        # Priority 2: logistic S-curve fallback
        if not use_hist and log_params:
            log_at_lkw = _logistic(lkw,     *log_params)
            log_at_end = _logistic(ramp_end, *log_params)
            if log_at_end > log_at_lkw and log_at_lkw < 0.99:
                use_logistic = True
                log_denom    = log_at_end - log_at_lkw

        for w in range(lkw + 1, n):
            if w <= ramp_end:
                if use_hist:
                    p_w  = avg_cum_profile.get(min(w, max_pw), p_end)
                    frac = max(0.0, min(1.0, (p_w - p_lkw) / denom))
                elif use_logistic:
                    frac = (_logistic(w, *log_params) - log_at_lkw) / log_denom
                else:
                    frac = (w - lkw) / (ramp_end - lkw)
                ds["data"][w] = max(round(cur_val + frac * (proj_final - cur_val)), cur_val)
            else:
                ds["data"][w] = proj_final

if proj_apps:
    _extend_with_projection(app_cum_datasets,     active_year, proj_apps[0],      app_school_start_idx,     proj_apps[12], proj_apps[13])
if proj_new_reg:
    _extend_with_projection(new_reg_cum_datasets, active_year, proj_new_reg[0],   new_reg_school_start_idx, proj_new_reg[12], proj_new_reg[13])
if proj_returning:
    _extend_with_projection(ret_cum_datasets,     active_year, proj_returning[0], ret_school_start_idx,     proj_returning[12], proj_returning[13])

# ── Per-trade projections for the by-trade cumulative chart ──────────────────
if not active_is_winter and completed_fall_labels:
    for _trade in CHART_TRADES:
        if _trade not in trade_cum_data:
            continue
        _proj = compute_blended_projection(
            fall_trade_cumulative[_trade].get(active_year, {}),
            fall_trade_cumulative[_trade],
            fall_trade_totals[_trade],
            completed_fall_labels,
            active_year_num,
        )
        if _proj:
            _extend_with_projection(
                trade_cum_data[_trade]["datasets"],
                active_year,
                _proj[0],
                trade_cum_data[_trade]["schoolStartIdx"],
                _proj[12],
                _proj[13],
            )

if proj_apps is not None or proj_new_reg is not None or proj_returning is not None:
    _apps_block    = _forecast_metric_block("Applications",      "fa-file-pen",    fall_app_totals.get(active_year, 0),      proj_apps)
    _newreg_block  = _forecast_metric_block("New Registrations", "fa-user-plus",   fall_total_new_reg.get(active_year, 0),   proj_new_reg)
    _ret_block     = _forecast_metric_block("Returning Students","fa-rotate-right", fall_returning_totals.get(active_year, 0), proj_returning)
    _n_hist        = len(completed_fall_labels)
    _wk_label      = f"Week {fall_2026_week + 1}"
    _vel_w         = round(min((fall_2026_week + 1) / 10, 0.85) * 100)
    forecast_section_html = (
        f'\n<!-- ── Enrollment Forecast ── -->\n'
        f'<div class="section-header" id="forecast" style="--sh-color:#f4a261;">\n'
        f'  <h2><i class="fa fa-chart-line" style="color:#f4a261;margin-right:8px;"></i>Enrollment Forecast</h2>\n'
        f'  <div class="sh-line"></div>\n'
        f'  <span class="sh-badge">Statistical Model</span>\n'
        f'</div>\n'
        f'<div class="card" style="margin-bottom:20px;">\n'
        f'  <div class="card-header">\n'
        f'    <div>\n'
        f'      <h3>{active_year} Projected Final Totals</h3>\n'
        f'      <div class="ch-sub">Trend + Pace blend &bull; {_n_hist} prior fall cycles &bull; {_wk_label} of {active_year} enrollment &bull; Trend anchors early weeks, pace takes over as data accumulates</div>\n'
        f'    </div>\n'
        f'  </div>\n'
        f'  <div class="card-body">\n'
        f'    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;">\n'
        f'      {_apps_block}\n'
        f'      {_newreg_block}\n'
        f'      {_ret_block}\n'
        f'    </div>\n'
        f'    <div style="margin-top:16px;padding:12px 16px;background:#f1f5f9;border-radius:8px;font-size:0.75rem;color:#64748b;line-height:1.6;">\n'
        f'      <strong style="color:#475569;">How this works:</strong> Three models are blended. The <strong>Trend model</strong> fits a linear regression through prior fall final totals '
        f'and extrapolates the growth trajectory &mdash; stable even with little current data. The <strong>Velocity model</strong> OLS-fits the current year\'s weekly submission pattern '
        f'against each prior year\'s normalized velocity curve. The <strong>Logistic model</strong> fits an S-curve to the cumulative enrollment shape, capturing the natural slow-start and plateau. '
        f'The blend shifts from ~{100 - _vel_w}% trend / {_vel_w}% pace now toward 15% / 85% by week 10. '
        f'Confidence reflects historical accuracy (MAPE) from a walk-forward backtest &mdash; how wrong the model has been at this exact week in prior years.\n'
        f'    </div>\n'
        f'  </div>\n'
        f'</div>\n'
    )
else:
    forecast_section_html = ""

# Pre-compute JSON blobs for JS
winter_data_json = json.dumps([
    {"Semester": y, "Applications": winter_app_totals.get(y, 0), "New Registrations": winter_total_new_reg.get(y, 0)}
    for y in winter_years
])

# CSV export data
csv_rows_json = json.dumps([
    {"Year": y, "Applications": fall_app_totals.get(y,0),
     "New Registrations": fall_total_new_reg.get(y,0),
     "Returning Registrations": fall_returning_totals.get(y,0),
     "Total Enrolled": fall_total_new_reg.get(y,0) + fall_returning_totals.get(y,0),
     "Electrical %": round(fall_app_trades.get(y,{}).get("Electrical",0)/max(fall_app_totals.get(y,1),1)*100,1)}
    for y in fall_years
])

# ── Pre-computed insight values (dynamic so they stay correct as data grows) ──
_growth_pct   = round((app_25 - app_22) / max(app_22, 1) * 100)
_growth_span  = len(completed_fall_labels) - 1
_app_sequence = " &rarr; ".join(
    f"{fall_app_totals.get(y, 0):,} ({y.split()[-1]})"
    for y in fall_years if y != active_year
)
_hvacr_launch  = next((y for y in fall_years if fall_app_trades.get(y, {}).get("HVACR", 0) > 0), None)
_hvacr_count   = fall_app_trades.get(_hvacr_launch, {}).get("HVACR", 0) if _hvacr_launch else 0
_first_fall    = fall_years[0]
_ret_growth_pct = round((ret_25 - ret_22) / ret_22 * 100, 1) if ret_22 else None

# Dynamic winter vs fall chart (academic year pairs: Fall YYYY + Winter YYYY+1)
_acad_years = [y for y in fall_years if y != active_year]
_winter_chart_labels = json.dumps([
    f"{y.split()[-1]}/{str(int(y.split()[-1])+1)[-2:]}" for y in _acad_years
])
_winter_chart_fall   = json.dumps([fall_app_totals.get(y, 0) for y in _acad_years])
_winter_chart_winter = json.dumps([
    winter_app_totals.get(f"Winter {int(y.split()[-1])+1}", None) for y in _acad_years
])

now_str = datetime.now().strftime("%B %d, %Y")

# ══════════════════════════════════════════════════════════════════════════════
# ── Student Intelligence computations ────────────────────────────────────────
# ══════════════════════════════════════════════════════════════════════════════

import ast as _ast

def _parse_multiselect(raw):
    """Parse a JotForm multi-select value into a list of strings."""
    if not raw or not raw.strip():
        return []
    try:
        v = _ast.literal_eval(raw.strip())
        if isinstance(v, list):
            return [str(x).strip() for x in v]
        if isinstance(v, dict):
            return [str(x).strip() for x in v.values()]
        return [str(v).strip()]
    except Exception:
        return [raw.strip()]

# ── 1. Conversion rates (app email → new-reg email match) ────────────────────
_ALL_SEASON_APPS = {**FALL_APPS, **WINTER_APPS}
_ALL_SEASON_NEW_REG = {**FALL_NEW_REG, **WINTER_NEW_REG}
_ALL_SEASON_ABC_REG = {**FALL_ABC_REG, **WINTER_ABC_REG}

_SEASON_ORDER = [
    "Fall 2022", "Fall 2023", "Fall 2024", "Fall 2025", "Fall 2026",
    "Winter 2025", "Winter 2026",
]

_conversion_data = []
for _s in _SEASON_ORDER:
    _app_rows = load_csv(_ALL_SEASON_APPS.get(_s, ""))
    _new_rows  = load_csv(_ALL_SEASON_NEW_REG.get(_s, ""))
    _abc_rows  = load_csv(_ALL_SEASON_ABC_REG.get(_s, ""))
    if not _app_rows:
        continue
    _app_emails = {r.get("Applicant's Email", "").strip().lower()
                   for r in _app_rows if r.get("Applicant's Email", "").strip()}
    _reg_emails = set()
    for _rr in _new_rows + _abc_rows:
        e = _rr.get("Applicant's Email", "").strip().lower()
        if e:
            _reg_emails.add(e)
    _n_apps    = len(_app_rows)
    _n_matched = len(_app_emails & _reg_emails)
    _pct       = round(_n_matched / max(_n_apps, 1) * 100)
    _conversion_data.append({
        "label":   _s,
        "apps":    _n_apps,
        "matched": _n_matched,
        "pct":     _pct,
        "season":  _s.split()[0],  # "Fall" or "Winter"
    })

_conv_json = json.dumps(_conversion_data)

# ── 2. Marketing attribution ──────────────────────────────────────────────────
_HEAR_COL = "How did you first hear about SEMCA?"

_mkt_all_counter  = defaultdict(int)   # overall totals
_mkt_by_year      = {}                 # {year_label: {source: count}}

for _s in _SEASON_ORDER:
    _rows = load_csv(_ALL_SEASON_APPS.get(_s, ""))
    _year_counter = defaultdict(int)
    for _r in _rows:
        _raw = _r.get(_HEAR_COL, "")
        for _src in _parse_multiselect(_raw):
            if _src:
                _mkt_all_counter[_src] += 1
                _year_counter[_src]    += 1
    _mkt_by_year[_s] = dict(_year_counter)

# Top 8 sources by overall count
_top_sources = [s for s, _ in sorted(_mkt_all_counter.items(), key=lambda x: -x[1])[:8]]
_mkt_totals_json = json.dumps([
    {"source": s, "count": _mkt_all_counter[s]} for s in _top_sources
])

# YoY breakdown for top sources (all seasons)
_mkt_yoy_json = json.dumps({
    _s: {src: _mkt_by_year.get(_s, {}).get(src, 0) for src in _top_sources}
    for _s in _SEASON_ORDER if _mkt_by_year.get(_s)
})

# Callout stats
_total_mkt   = sum(_mkt_all_counter.values())
_google_cnt  = _mkt_all_counter.get("Google", 0)
_student_cnt = _mkt_all_counter.get("SEMCA Student", 0)
_employer_cnt= _mkt_all_counter.get("Employer", 0)
_family_cnt  = _mkt_all_counter.get("Family/Friend/Word of Mouth", 0)
_google_student_pct = round((_google_cnt + _student_cnt) / max(_total_mkt, 1) * 100)
_wom_pct = round((_student_cnt + _employer_cnt + _family_cnt) / max(_total_mkt, 1) * 100)

# ── 3. Social survey stats ────────────────────────────────────────────────────
_SURVEY_FILE = "2026 SEMCA Student Social Media Survey.csv"
_survey_rows = load_csv(_SURVEY_FILE)

def _count_multiselect_col(rows, col):
    counter = defaultdict(int)
    for r in rows:
        for v in _parse_multiselect(r.get(col, "")):
            if v:
                counter[v] += 1
    return dict(counter)

def _count_single_col(rows, col):
    counter = defaultdict(int)
    for r in rows:
        v = r.get(col, "").strip()
        if v:
            counter[v] += 1
    return dict(counter)

_sv_age       = _count_single_col(_survey_rows, "How old are you?")
_sv_platforms = _count_multiselect_col(_survey_rows, "Which social media platforms do you use regularly? (Select all)")
_sv_content   = _count_multiselect_col(_survey_rows, "What type of content do you watch the MOST? (Select up to 3)")
_sv_influencer= _count_multiselect_col(_survey_rows, "Who influences your career decisions the most? (Select up to 2)")
_sv_action    = _count_multiselect_col(_survey_rows, "What would make you take action on a job or program opportunity? (Select up to 2)")
_sv_commfmt   = _count_multiselect_col(_survey_rows, "What is your preferred method of communication? (Select all)")
_sv_heard     = _count_single_col(_survey_rows, "How did you FIRST hear about SEMCA?")

_sv_age_order     = ["18-22", "23-27", "28-35", "35+"]
_sv_platform_order= ["Instagram", "YouTube", "TikTok", "Snapchat", "Facebook", "X", "Reddit", "None"]
_sv_action_order  = ["Good pay", "Hands-on work", "Job security", "Someone I know recommends it", "It looks interesting"]
_sv_content_order = ["Funny/Memes", "Construction/Trades", "Sports", "Gaming", "Fitness/Gym", "Cars/Trucks"]
_sv_comm_order    = ["Text", "Email", "Phone call", "Social media"]
_sv_infl_order    = ["Family", "Friends", "No one", "Employer/boss", "Co-workers"]

_sv_n = max(len(_survey_rows), 1)
_sv_text_cnt   = _sv_commfmt.get("Text", 0)
_sv_email_cnt  = _sv_commfmt.get("Email", 0)
_sv_family_cnt = _sv_influencer.get("Family", 0)

# JSON for charts
_sv_age_json      = json.dumps([{"label": k, "count": _sv_age.get(k, 0)} for k in _sv_age_order])
_sv_platform_json = json.dumps([{"label": k, "count": _sv_platforms.get(k, 0)} for k in _sv_platform_order if _sv_platforms.get(k, 0) > 0])
_sv_action_json   = json.dumps([{"label": k, "count": _sv_action.get(k, 0)} for k in _sv_action_order])
_sv_comm_json     = json.dumps([{"label": k, "count": _sv_commfmt.get(k, 0)} for k in _sv_comm_order])
_sv_infl_json     = json.dumps([{"label": k, "count": _sv_influencer.get(k, 0)} for k in _sv_infl_order])

# ── 4. Demographics by year ───────────────────────────────────────────────────
def _normalize_race(raw_val):
    v = raw_val.strip()
    if "Caucasian" in v or "White" in v:           return "White"
    if "African American" in v or "Black" in v:    return "Black/African American"
    if "Hispanic" in v or "Latin" in v:            return "Hispanic/Latino"
    if "Middle Eastern" in v:                      return "Middle Eastern"
    if "Asian" in v:                               return "Asian"
    return "Other"

def _normalize_edu(raw_val):
    v = raw_val.strip()
    if "GED" in v or "High School" in v or "high school" in v: return "HS/GED"
    if "Bachelor" in v or "Master" in v or "Doctorate" in v or "Graduate" in v: return "Bachelor's+"
    if "College" in v or "Associate" in v or "Some" in v:      return "Some College"
    return None

_RACE_COL = "What is your race? (select all that apply)"
_EDU_COL  = "What is your highest level of education?"
_RACE_ORDER = ["White", "Black/African American", "Hispanic/Latino", "Middle Eastern", "Asian", "Other"]
_EDU_ORDER  = ["HS/GED", "Some College", "Bachelor's+"]

_demo_by_year   = {}  # {year: {race: count}}
_edu_all        = defaultdict(int)

for _y in fall_years:
    _rows = load_csv(FALL_APPS[_y])
    _race_counter = defaultdict(int)
    _edu_counter  = defaultdict(int)
    for _r in _rows:
        # Race — multi-select
        _raw_race = _r.get(_RACE_COL, "")
        _race_vals = _parse_multiselect(_raw_race) if _raw_race.strip() else []
        if not _race_vals and _raw_race.strip():
            _race_vals = [_raw_race.strip()]
        # Count the respondent once per normalized primary race (first listed)
        _normed = [_normalize_race(rv) for rv in _race_vals if rv.strip()]
        if _normed:
            _race_counter[_normed[0]] += 1
        # Education — single-select
        _edu_raw = _r.get(_EDU_COL, "").strip()
        _edu_norm = _normalize_edu(_edu_raw)
        if _edu_norm:
            _race_counter  # already processed
            _edu_counter[_edu_norm]  += 1
            _edu_all[_edu_norm]      += 1
    _demo_by_year[_y] = dict(_race_counter)

_demo_race_json = json.dumps({
    y: {r: _demo_by_year.get(y, {}).get(r, 0) for r in _RACE_ORDER}
    for y in fall_years
})
_demo_edu_json = json.dumps([
    {"label": e, "count": _edu_all.get(e, 0)} for e in _EDU_ORDER
])
_demo_labels_json = json.dumps(fall_years)
_demo_race_colors = {
    "White":                  "#0072b2",
    "Black/African American": "#e69f00",
    "Hispanic/Latino":        "#009e73",
    "Middle Eastern":         "#cc79a7",
    "Asian":                  "#56b4e9",
    "Other":                  "#d55e00",
}
_demo_race_colors_json = json.dumps(_demo_race_colors)
_demo_race_order_json  = json.dumps(_RACE_ORDER)
_demo_edu_colors_json  = json.dumps({
    "HS/GED":       "#0072b2",
    "Some College": "#e69f00",
    "Bachelor's+":  "#009e73",
})

# ── HTML ──────────────────────────────────────────────────────────────────────

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SEMCA Enrollment Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<style>
:root {{
  --navy: #1e3a5f;
  --navy-dark: #152a46;
  --navy-light: #2e5082;
  --blue: #3b82f6;
  --blue-light: #93c5fd;
  --orange: #f4a261;
  --orange-dark: #e07b3a;
  --red: #e63946;
  --green: #2a9d8f;
  --yellow: #e9c46a;
  --bg: #f0f4f8;
  --card: #ffffff;
  --border: #e2e8f0;
  --text: #1a202c;
  --text-muted: #64748b;
  --sidebar-w: 240px;
  --shadow: 0 1px 3px rgba(0,0,0,0.08), 0 4px 16px rgba(0,0,0,0.04);
  --shadow-lg: 0 4px 12px rgba(0,0,0,0.12), 0 16px 40px rgba(0,0,0,0.08);
  --radius: 12px;
  --radius-sm: 8px;
}}

* {{ box-sizing: border-box; margin: 0; padding: 0; }}
html {{ scroll-behavior: smooth; }}
body {{ font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); display: flex; min-height: 100vh; }}

/* ── Sidebar ── */
#sidebar {{
  width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--navy-dark);
  position: fixed; top: 0; left: 0; height: 100vh; overflow-y: auto;
  display: flex; flex-direction: column; z-index: 100;
  box-shadow: 2px 0 12px rgba(0,0,0,0.15);
}}
.sidebar-logo {{
  padding: 24px 20px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.08);
}}
.sidebar-logo .logo-text {{ color: white; font-size: 1.3rem; font-weight: 800; letter-spacing: -0.5px; }}
.sidebar-logo .logo-sub {{ color: #94a3b8; font-size: 0.7rem; text-transform: uppercase; letter-spacing: 1px; margin-top: 2px; }}
.sidebar-logo .logo-bar {{ height: 3px; background: var(--orange); border-radius: 2px; margin-top: 12px; width: 40px; }}
.sidebar-section {{ padding: 16px 12px 4px; color: #64748b; font-size: 0.65rem; text-transform: uppercase; letter-spacing: 1.2px; font-weight: 600; }}
.sidebar-nav a {{
  display: flex; align-items: center; gap: 10px; padding: 9px 16px;
  color: #94a3b8; text-decoration: none; font-size: 0.83rem; font-weight: 500;
  border-radius: 6px; margin: 1px 8px; transition: all 0.15s;
}}
.sidebar-nav a:hover {{ background: rgba(255,255,255,0.07); color: white; }}
.sidebar-nav a.active {{ background: rgba(59,130,246,0.2); color: #93c5fd; }}
.sidebar-nav a i {{ width: 16px; text-align: center; font-size: 0.8rem; opacity: 0.8; }}
.sidebar-footer {{
  margin-top: auto; padding: 16px; border-top: 1px solid rgba(255,255,255,0.08);
  color: #475569; font-size: 0.72rem; line-height: 1.5;
}}

/* ── Main ── */
#main {{
  margin-left: var(--sidebar-w); flex: 1; min-width: 0;
}}

/* ── Top bar ── */
#topbar {{
  background: white; border-bottom: 1px solid var(--border);
  padding: 0 32px; height: 56px; display: flex; align-items: center;
  justify-content: space-between; position: sticky; top: 0; z-index: 90;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
}}
.topbar-title {{ font-size: 0.9rem; font-weight: 600; color: var(--text-muted); }}
.topbar-title span {{ color: var(--text); }}
.export-group {{ display: flex; gap: 8px; }}
.btn {{
  display: inline-flex; align-items: center; gap: 6px;
  padding: 7px 14px; border-radius: var(--radius-sm); font-size: 0.8rem;
  font-weight: 600; cursor: pointer; border: none; transition: all 0.15s;
  font-family: inherit; text-decoration: none;
}}
.btn-ghost {{ background: transparent; color: var(--text-muted); border: 1px solid var(--border); }}
.btn-ghost:hover {{ background: var(--bg); color: var(--text); }}
.btn-primary {{ background: var(--navy); color: white; }}
.btn-primary:hover {{ background: var(--navy-light); }}
.btn-orange {{ background: var(--orange); color: white; }}
.btn-orange:hover {{ background: var(--orange-dark); }}
.btn-green {{ background: var(--green); color: white; }}
.btn-green:hover {{ background: #218c7e; }}

/* ── Content ── */
.content {{ padding: 28px 32px 60px; }}

/* ── Hero ── */
.hero {{
  background: linear-gradient(135deg, var(--navy-dark) 0%, var(--navy-light) 100%);
  border-radius: var(--radius); padding: 36px 40px; margin-bottom: 28px;
  position: relative; overflow: hidden;
}}
.hero::before {{
  content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 0;
  background-image: radial-gradient(rgba(148,197,255,0.09) 1px, transparent 1px);
  background-size: 26px 26px;
}}
.hero::after {{
  content: ''; position: absolute; inset: 0; pointer-events: none; z-index: 0;
  background-image:
    linear-gradient(rgba(255,255,255,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px);
  background-size: 78px 78px;
}}
.hero-deco {{ position: absolute; pointer-events: none; z-index: 0; line-height: 1; }}
.hero-label {{ color: var(--orange); font-size: 0.75rem; font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px; margin-bottom: 8px; position: relative; z-index: 1; }}
.hero h1 {{ color: white; font-size: 1.9rem; font-weight: 800; letter-spacing: -0.5px; line-height: 1.2; position: relative; z-index: 1; }}
.hero-sub {{ color: #94a3b8; font-size: 0.9rem; margin-top: 6px; position: relative; z-index: 1; }}
.hero-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 20px; margin-top: 28px; position: relative; z-index: 1; }}
.hero-stat {{
  background: rgba(0,0,0,0.22); border-radius: 12px; padding: 16px 20px;
  border: 1px solid rgba(255,255,255,0.1);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.07), 0 4px 20px rgba(0,0,0,0.25);
  backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  position: relative; overflow: hidden;
  transition: transform 0.22s ease, box-shadow 0.22s ease;
  cursor: default;
}}
.hero-stat::before {{
  content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
  background: linear-gradient(90deg, transparent, var(--orange), transparent);
  opacity: 0.7;
}}
.hero-stat:hover {{
  transform: translateY(-3px);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.1), 0 10px 32px rgba(0,0,0,0.35), 0 0 0 1px rgba(230,159,0,0.3);
}}
.hero-stat-apps   {{ }}
.hero-stat-new    {{ }}
.hero-stat-ret    {{ }}
.hero-stat-growth {{ }}
.hero-stat .hs-label {{ color: #94a3b8; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 6px; }}
.hero-stat .hs-num {{
  color: white; font-size: 2rem; font-weight: 800; letter-spacing: -1px; line-height: 1;
  text-shadow: 0 0 20px rgba(255,255,255,0.15);
}}
.hero-stat .hs-change {{ margin-top: 6px; font-size: 0.78rem; font-weight: 600; }}
.pos {{ color: #4ade80; }} .neg {{ color: #f87171; }} .neutral {{ color: #94a3b8; }}

/* ── Pace banner ── */
.pace-banner {{
  position: relative; overflow: hidden;
  background: linear-gradient(120deg, #c2410c 0%, #ea580c 45%, #f97316 100%);
  border: none; border-radius: var(--radius);
  padding: 20px 24px; margin-bottom: 28px;
  box-shadow: 0 6px 32px rgba(194,65,12,0.45);
}}
.pace-banner > * {{ position: relative; z-index: 2; }}
/* Subtle dot-grid overlay */
.pace-banner::after {{
  content: ''; position: absolute; inset: 0; z-index: 1; pointer-events: none;
  background-image: radial-gradient(rgba(255,255,255,0.07) 1px, transparent 1px);
  background-size: 22px 22px;
}}
@keyframes live-pulse {{
  0%, 100% {{ box-shadow: 0 0 0 0 rgba(239,68,68,0.5); }}
  60% {{ box-shadow: 0 0 0 6px rgba(239,68,68,0); }}
}}
.banner-dot {{
  display: inline-block; width: 9px; height: 9px; border-radius: 50%;
  background: #ef4444; animation: live-pulse 1.6s ease-out infinite;
}}
.pace-chips {{ display: flex; gap: 8px; margin-top: 10px; flex-wrap: wrap; }}
.chip {{
  display: inline-flex; align-items: center; gap: 5px; padding: 4px 10px;
  border-radius: 20px; font-size: 0.75rem; font-weight: 600;
}}
.chip-blue {{ background: #dbeafe; color: #1d4ed8; }}
.chip-orange {{ background: #fed7aa; color: #9a3412; }}
.chip-green {{ background: #d1fae5; color: #065f46; }}

/* ── Section header ── */
.section-header {{
  margin: 32px 0 16px; display: flex; align-items: center; gap: 12px;
  padding-left: 14px; border-left: 4px solid var(--sh-color, var(--navy));
}}
.section-header h2 {{ font-size: 1.05rem; font-weight: 700; color: var(--navy); }}
.section-header .sh-line {{ flex: 1; height: 1px; background: linear-gradient(to right, var(--sh-color, var(--border)), transparent); opacity: 0.5; }}
.section-header .sh-badge {{
  font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px;
  color: white; background: var(--sh-color, var(--text-muted)); padding: 3px 10px; border-radius: 4px;
}}

/* ── Cards ── */
.card {{
  background: var(--card); border-radius: var(--radius); overflow: hidden;
  border: 1px solid var(--border);
  box-shadow: 0 2px 6px rgba(0,0,0,0.06), 0 8px 24px rgba(0,0,0,0.07);
}}
.card-header {{ padding: 18px 24px 0; }}
.card-header h3 {{ font-size: 0.9rem; font-weight: 700; color: var(--navy); }}
.card-header .ch-sub {{ font-size: 0.78rem; color: var(--text-muted); margin-top: 2px; }}
.card-body {{ padding: 16px 24px 24px; }}
.card-footer {{ padding: 12px 24px; background: #f8fafc; border-top: 1px solid var(--border); font-size: 0.75rem; color: var(--text-muted); }}

/* ── Grid ── */
.grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
.grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; }}
.grid-4 {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; }}

/* ── KPI cards ── */
/* ── Gamified KPI ── */
.kpi {{ padding: 20px 24px; position: relative; overflow: hidden; }}
.kpi-bg-icon {{
  position: absolute; right: -10px; bottom: -12px;
  font-size: 5.5rem; opacity: 0.04; pointer-events: none; line-height: 1;
}}
.kpi-ring {{
  position: absolute; top: 16px; right: 16px;
  width: 44px; height: 44px; border-radius: 50%;
  background: conic-gradient(var(--ring-c, #cbd5e1) calc(var(--ring-pct, 0) * 1%), #e8edf2 0);
}}
.kpi-ring::before {{
  content: ''; position: absolute; inset: 7px; border-radius: 50%; background: white;
}}
.kpi-ring-label {{
  position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  font-size: 0.55rem; font-weight: 800; color: var(--text-muted); z-index: 1; letter-spacing: -0.3px;
}}
.kpi-label {{ font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.8px; color: var(--text-muted); font-weight: 600; margin-bottom: 8px; position: relative; }}
.kpi-num {{ font-size: 2.5rem; font-weight: 800; letter-spacing: -1.5px; line-height: 1; position: relative; }}
.kpi-compare {{ font-size: 0.8rem; color: var(--text-muted); margin-top: 6px; position: relative; }}
.kpi-badge {{ display: inline-flex; align-items: center; gap: 4px; padding: 3px 8px; border-radius: 20px; font-size: 0.75rem; font-weight: 700; margin-top: 8px; position: relative; }}
.badge-green {{ background: #dcfce7; color: #15803d; }}
.badge-red {{ background: #fee2e2; color: #b91c1c; }}
.badge-blue {{ background: #dbeafe; color: #1d4ed8; }}
.badge-orange {{ background: #ffedd5; color: #c2410c; }}
.kpi-bar {{ height: 8px; background: #e8edf2; border-radius: 4px; margin-top: 16px; overflow: hidden; position: relative; }}
.kpi-bar-fill {{
  height: 100%; border-radius: 4px; position: relative; overflow: hidden;
  transition: width 1.4s cubic-bezier(0.25, 0.46, 0.45, 0.94);
}}
.kpi-bar-fill::after {{ display: none; }}
/* Card color themes */
.kpi-navy {{ background: linear-gradient(160deg, #fff 60%, #f0f4ff); border-top: 4px solid var(--navy); }}
.kpi-navy .kpi-num {{ background: linear-gradient(125deg, #0f2040, #2e5082); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }}
.kpi-navy .kpi-bar-fill {{ background: linear-gradient(90deg, #1e3a5f, #60a5fa); }}
.kpi-blue {{ background: linear-gradient(160deg, #fff 60%, #eff6ff); border-top: 4px solid var(--blue); }}
.kpi-blue .kpi-num {{ background: linear-gradient(125deg, #1e40af, #60a5fa); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }}
.kpi-blue .kpi-bar-fill {{ background: linear-gradient(90deg, #1d4ed8, #93c5fd); }}
.kpi-green {{ background: linear-gradient(160deg, #fff 60%, #f0fdf9); border-top: 4px solid var(--green); }}
.kpi-green .kpi-num {{ background: linear-gradient(125deg, #065f46, #2a9d8f); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }}
.kpi-green .kpi-bar-fill {{ background: linear-gradient(90deg, #065f46, #34d399); }}
.kpi-orange {{ background: linear-gradient(160deg, #fff 60%, #fff8f0); border-top: 4px solid var(--orange); }}
.kpi-orange .kpi-num {{ background: linear-gradient(125deg, #c2410c, #f97316); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent; }}
.kpi-orange .kpi-bar-fill {{ background: linear-gradient(90deg, #ea580c, #fdba74); }}

/* ── KPI funnel connectors ── */
.kpi-funnel {{ display: flex; align-items: stretch; gap: 0; margin-bottom: 20px; }}
.kpi-funnel > .card {{ flex: 1; min-width: 0; }}
.kpi-connector {{
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  flex-shrink: 0; width: 58px; gap: 2px; position: relative;
}}
.kpi-connector::before {{
  content: ''; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%);
  width: 40px; height: 40px; border-radius: 50%;
  background: white; border: 2px solid var(--border);
  z-index: 0;
}}
.kpi-conn-pct {{
  font-size: 0.8rem; font-weight: 800; color: var(--navy);
  line-height: 1; position: relative; z-index: 1;
}}
.kpi-conn-label {{
  font-size: 0.52rem; text-transform: uppercase; letter-spacing: 0.4px;
  color: var(--text-muted); text-align: center; line-height: 1.3; position: relative; z-index: 1;
}}
.kpi-conn-arrow {{
  font-size: 0.75rem; color: var(--border); position: absolute;
  right: -2px; top: 50%; transform: translateY(-50%); z-index: 2;
}}

/* ── Table ── */
.tbl-wrap {{ overflow-x: auto; }}
table {{ width: 100%; border-collapse: collapse; font-size: 0.84rem; }}
thead th {{ background: var(--navy); color: white; padding: 11px 16px; text-align: left; font-weight: 600; font-size: 0.78rem; white-space: nowrap; }}
thead th:first-child {{ border-radius: 0; }}
tbody tr {{ border-bottom: 1px solid #f1f5f9; transition: background 0.1s; }}
tbody tr:hover {{ background: #f8fafc; }}
tbody tr:last-child {{ border-bottom: none; }}
tbody td {{ padding: 11px 16px; color: var(--text); }}
tbody tr.highlight-row {{ background: #fffbeb; font-weight: 600; }}
tbody tr.highlight-row:hover {{ background: #fef3c7; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.72rem; font-weight: 600; }}
.tag-live {{ background: #fee2e2; color: #b91c1c; }}
.tag-done {{ background: #dcfce7; color: #15803d; }}
.pct-bar {{ display: flex; align-items: center; gap: 8px; }}
.pct-bar-bg {{ flex: 1; height: 6px; background: #e2e8f0; border-radius: 3px; overflow: hidden; min-width: 60px; }}
.pct-bar-fill {{ height: 100%; background: var(--navy); border-radius: 3px; }}

/* ── Insights ── */
.insight {{
  background: white; border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 20px 24px; display: flex; gap: 16px; align-items: flex-start;
  border-left: 4px solid var(--blue);
}}
.insight-icon {{ font-size: 1.2rem; margin-top: 2px; }}
.insight h4 {{ font-size: 0.9rem; font-weight: 700; color: var(--navy); margin-bottom: 5px; }}
.insight p {{ font-size: 0.83rem; color: #475569; line-height: 1.65; }}
.insight-grid {{ display: flex; flex-direction: column; gap: 12px; }}

/* ── Recommendations ── */
.rec {{
  background: white; border-radius: var(--radius); box-shadow: var(--shadow);
  padding: 20px 24px; display: flex; gap: 16px; align-items: flex-start;
}}
.rec-badge {{
  background: var(--orange); color: white; font-weight: 800; font-size: 0.85rem;
  border-radius: 8px; width: 32px; height: 32px; display: flex; align-items: center;
  justify-content: center; flex-shrink: 0; margin-top: 2px;
}}
.rec h4 {{ font-size: 0.9rem; font-weight: 700; color: var(--navy); margin-bottom: 5px; }}
.rec p {{ font-size: 0.83rem; color: #475569; line-height: 1.65; }}
.rec-grid {{ display: flex; flex-direction: column; gap: 12px; }}

/* ── Chart wrapper ── */
.chart-wrap {{ position: relative; }}

/* ── Toggle pills ── */
.toggle-group {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }}
.toggle-pill {{
  padding: 4px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600;
  cursor: pointer; border: 1.5px solid; transition: all 0.15s; user-select: none;
}}
.hero-year-pill {{
  padding: 6px 16px; border-radius: 20px; font-size: 0.8rem; font-weight: 600;
  cursor: pointer; border: 1.5px solid rgba(255,255,255,0.3);
  background: rgba(255,255,255,0.08); color: rgba(255,255,255,0.7);
  transition: all 0.18s; user-select: none;
  display: inline-flex; align-items: center; gap: 7px;
}}
.hero-year-pill:hover {{ background: rgba(255,255,255,0.18); color: white; border-color: rgba(255,255,255,0.6); }}
.hero-year-pill.active {{ background: white; color: var(--navy-dark); border-color: white; font-weight: 700; }}
.live-dot {{
  width: 7px; height: 7px; border-radius: 50%; background: rgba(220,38,38,0.7); flex-shrink: 0;
}}
.hero-year-pill.live {{ background: rgba(213,94,0,0.12); border-color: rgba(220,38,38,0.5); color: rgba(255,220,185,0.95); }}
.hero-year-pill.live:hover {{ background: rgba(213,94,0,0.22); border-color: rgba(220,38,38,0.7); color: white; }}
/* ── Trade progress bars ── */
.trade-row {{ display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }}
.trade-label {{ font-size: 0.82rem; font-weight: 600; color: var(--text); min-width: 140px; }}
.trade-bg {{ flex: 1; height: 8px; background: var(--border); border-radius: 4px; overflow: hidden; }}
.trade-fill {{ height: 100%; border-radius: 4px; transition: width 1.2s ease; }}
.trade-pct {{ font-size: 0.78rem; color: var(--text-muted); min-width: 36px; text-align: right; font-weight: 600; }}

/* ── Print / PDF ── */
@media print {{
  #sidebar, #topbar, .export-group, .pace-banner .pace-icon {{ display: none !important; }}
  #main {{ margin-left: 0 !important; }}
  .content {{ padding: 0 !important; }}
  .hero {{ -webkit-print-color-adjust: exact; print-color-adjust: exact; }}
  .card {{ break-inside: avoid; box-shadow: none; border: 1px solid var(--border); }}
  body {{ background: white; }}
}}

/* ── Scrollbar ── */
#sidebar::-webkit-scrollbar {{ width: 4px; }}
#sidebar::-webkit-scrollbar-thumb {{ background: rgba(255,255,255,0.1); border-radius: 2px; }}

@media (max-width: 900px) {{
  #sidebar {{ display: none; }}
  #main {{ margin-left: 0; }}
  .hero-stats {{ grid-template-columns: 1fr 1fr; }}
  .grid-2, .grid-3, .grid-4 {{ grid-template-columns: 1fr; }}
  .kpi-funnel {{ flex-direction: column; }}
  .kpi-connector {{ flex-direction: row; width: auto; height: 36px; padding: 0 16px; gap: 8px; }}
  .kpi-connector::before {{ width: 60px; height: 32px; border-radius: 16px; top: 50%; left: 50%; }}
  .kpi-conn-arrow {{ position: static; transform: rotate(90deg); }}
  .content {{ padding: 16px; }}
  #topbar {{ padding: 0 16px; }}
}}
</style>
</head>
<body>

<!-- ══ SIDEBAR ══ -->
<nav id="sidebar">
  <div class="sidebar-logo">
    <div class="logo-text">SEMCA</div>
    <div class="logo-sub">Southeast Michigan Construction Academy</div>
    <div class="logo-bar"></div>
  </div>
  <div class="sidebar-section">Overview</div>
  <div class="sidebar-nav">
    <a href="#overview"><i class="fa fa-gauge-high"></i> Dashboard</a>
    <a href="#pace"><i class="fa fa-bolt"></i> Fall 2026 Pace</a>
  </div>
  <div class="sidebar-section">Applications</div>
  <div class="sidebar-nav">
    <a href="#app-trends"><i class="fa fa-chart-bar"></i> Annual Totals</a>
    <a href="#app-pace"><i class="fa fa-chart-line"></i> Weekly Pace</a>
  </div>
  <div class="sidebar-section">Registrations</div>
  <div class="sidebar-nav">
    <a href="#returning"><i class="fa fa-rotate-right"></i> Returning Students</a>
    <a href="#new-reg"><i class="fa fa-user-plus"></i> New Students</a>
  </div>
  <div class="sidebar-section">Breakdown</div>
  <div class="sidebar-nav">
    <a href="#trades"><i class="fa fa-hard-hat"></i> By Trade</a>
    <a href="#locations"><i class="fa fa-location-dot"></i> By Campus</a>
    <a href="#winter"><i class="fa fa-snowflake"></i> Winter Enrollment</a>
  </div>
  <div class="sidebar-section">Analysis</div>
  <div class="sidebar-nav">
    <a href="#forecast"><i class="fa fa-chart-line"></i> Enrollment Forecast</a>
    <a href="#insights"><i class="fa fa-lightbulb"></i> Key Findings</a>
    <a href="#student-intel"><i class="fa fa-users"></i> Student Intelligence</a>
    <a href="#recommendations"><i class="fa fa-list-check"></i> Recommendations</a>
    <a href="#data-table"><i class="fa fa-table"></i> Full Data Table</a>
  </div>
  <div class="sidebar-footer">
    Generated {now_str}<br>
    Source: JotForm via SEMCA API
  </div>
</nav>

<!-- ══ MAIN ══ -->
<div id="main">

<!-- ── Top bar ── -->
<div id="topbar">
  <div class="topbar-title">Enrollment Trend Analysis &mdash; <span>Fall 2022 &ndash; Fall 2026</span></div>
  <div class="export-group">
    <button class="btn btn-ghost" onclick="exportCSV()"><i class="fa fa-file-csv"></i> CSV</button>
    <button class="btn btn-green" onclick="exportExcel()"><i class="fa fa-file-excel"></i> Excel</button>
    <button class="btn btn-primary" onclick="window.print()"><i class="fa fa-print"></i> PDF / Print</button>
  </div>
</div>

<div class="content">

<!-- ── Hero ── -->
<div class="hero" id="overview">
  <!-- decorative trade icons -->
  <i class="fa-solid fa-gear hero-deco" style="font-size:220px;color:rgba(255,255,255,0.04);right:-40px;top:50%;transform:translateY(-50%) rotate(12deg);"></i>
  <i class="fa-solid fa-bolt hero-deco" style="font-size:110px;color:rgba(213,94,0,0.08);left:18px;bottom:-18px;transform:rotate(-8deg);"></i>
  <i class="fa-solid fa-helmet-safety hero-deco" style="font-size:80px;color:rgba(255,255,255,0.035);right:210px;top:-10px;transform:rotate(10deg);"></i>
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:0;position:relative;z-index:1;">
    <div class="hero-label" style="margin-bottom:0;">Enrollment Trend Analysis &bull; {now_str}</div>
    <button id="liveRefreshBtn" onclick="liveRefresh()" title="Fetch latest counts from JotForm"
      style="display:inline-flex;align-items:center;gap:6px;padding:4px 12px;font-size:0.72rem;font-weight:600;
             color:#f4a261;background:rgba(244,162,97,0.1);border:1.5px solid rgba(244,162,97,0.35);
             border-radius:20px;cursor:pointer;outline:none;transition:all 0.18s;">
      <i id="liveRefreshIcon" class="fa fa-rotate"></i> Live Refresh
    </button>
    <span id="liveRefreshTime" style="font-size:0.7rem;color:#64748b;"></span>
  </div>
  <h1>SEMCA Enrollment Dashboard</h1>
  <div class="hero-sub">Historical data analysis covering Fall 2022 through Fall 2026 &bull; Applications, Registrations, Trends &amp; Insights</div>
  <div id="heroYearPills" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:16px;margin-bottom:16px;position:relative;z-index:1;">
    {hero_pills_html}
  </div>
  <div class="hero-stats">
    <div class="hero-stat hero-stat-apps">
      <div class="hs-label" id="hs-app-label">{complete_fall} Applications</div>
      <div class="hs-num" id="hs-app-num">{app_25}</div>
      <div class="hs-change pos" id="hs-app-change"><i class="fa fa-arrow-trend-up"></i> {pct_change(app_24, app_25)} vs {prior_year_short}</div>
    </div>
    <div class="hero-stat hero-stat-new">
      <div class="hs-label" id="hs-new-label">{complete_fall} New Enrollments</div>
      <div class="hs-num" id="hs-new-num">{new_25}</div>
      <div class="hs-change pos" id="hs-new-change"><i class="fa fa-arrow-trend-up"></i> {pct_change(new_24, new_25)} vs {prior_year_short}</div>
    </div>
    <div class="hero-stat hero-stat-ret">
      <div class="hs-label" id="hs-ret-label">Returning Students ({complete_year_short.replace("Fall ","F'")})</div>
      <div class="hs-num" id="hs-ret-num">{ret_25}</div>
      <div class="hs-change pos" id="hs-ret-change"><i class="fa fa-arrow-trend-up"></i> {pct_change(ret_24, ret_25)} vs {prior_year_short}</div>
    </div>
    <div class="hero-stat hero-stat-growth">
      <div class="hs-label" id="hs-growth-label">3-Year App Growth</div>
      <div class="hs-num" id="hs-growth-num">+83%</div>
      <div class="hs-change neutral" id="hs-growth-change">{app_22} (2022) &rarr; {app_25} (2025)</div>
    </div>
  </div>
</div>

<!-- ── Fall 2026 Pace Banner ── -->
<div class="pace-banner" id="pace" style="display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;">
  <div style="flex:1;min-width:220px;">
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
      <span class="banner-dot"></span>
      <span style="font-size:0.75rem;font-weight:700;color:rgba(255,255,255,0.85);text-transform:uppercase;letter-spacing:0.6px;">Live &bull; {active_year} &bull; Week {fall_2026_week + 1}</span>
    </div>
    <div style="font-size:2.6rem;font-weight:800;line-height:1;color:white;margin-bottom:4px;">{app_26} <span style="font-size:1rem;font-weight:500;color:rgba(255,255,255,0.7);">applications</span></div>
    <div style="font-size:0.78rem;color:rgba(255,255,255,0.75);margin-bottom:10px;">{ring_live_pct}% of last year&apos;s total ({app_25})</div>
    <div style="height:10px;background:rgba(255,255,255,0.25);border-radius:6px;overflow:hidden;">
      <div style="height:100%;width:{ring_live_pct}%;background:white;opacity:0.9;border-radius:6px;"></div>
    </div>
  </div>
  <div style="text-align:center;border-left:1.5px solid rgba(255,255,255,0.3);padding-left:28px;width:280px;flex-shrink:0;">
    <div style="font-size:0.68rem;font-weight:700;color:rgba(255,255,255,0.7);text-transform:uppercase;letter-spacing:0.7px;margin-bottom:12px;">Semester Starts In</div>
    <div id="countdown" style="display:flex;gap:6px;align-items:flex-end;justify-content:center;">
      <div style="text-align:center;width:54px;">
        <div id="cd-days" style="font-size:2.2rem;font-weight:800;line-height:1;color:rgba(255,255,255,0.9);font-variant-numeric:tabular-nums;">--</div>
        <div style="font-size:0.65rem;color:rgba(255,255,255,0.55);font-weight:600;text-transform:uppercase;margin-top:5px;letter-spacing:0.5px;">Days</div>
      </div>
      <div style="font-size:1.5rem;font-weight:300;color:rgba(255,255,255,0.3);padding-bottom:6px;">:</div>
      <div style="text-align:center;width:54px;">
        <div id="cd-hrs" style="font-size:2.2rem;font-weight:800;line-height:1;color:rgba(255,255,255,0.9);font-variant-numeric:tabular-nums;">--</div>
        <div style="font-size:0.65rem;color:rgba(255,255,255,0.55);font-weight:600;text-transform:uppercase;margin-top:5px;letter-spacing:0.5px;">Hrs</div>
      </div>
      <div style="font-size:1.5rem;font-weight:300;color:rgba(255,255,255,0.3);padding-bottom:6px;">:</div>
      <div style="text-align:center;width:54px;">
        <div id="cd-min" style="font-size:2.2rem;font-weight:800;line-height:1;color:rgba(255,255,255,0.9);font-variant-numeric:tabular-nums;">--</div>
        <div style="font-size:0.65rem;color:rgba(255,255,255,0.55);font-weight:600;text-transform:uppercase;margin-top:5px;letter-spacing:0.5px;">Min</div>
      </div>
      <div style="font-size:1.5rem;font-weight:300;color:rgba(255,255,255,0.3);padding-bottom:6px;">:</div>
      <div style="text-align:center;width:54px;">
        <div id="cd-sec" style="font-size:2.2rem;font-weight:800;line-height:1;color:rgba(255,255,255,0.75);font-variant-numeric:tabular-nums;">--</div>
        <div style="font-size:0.65rem;color:rgba(255,255,255,0.55);font-weight:600;text-transform:uppercase;margin-top:5px;letter-spacing:0.5px;">Sec</div>
      </div>
    </div>
    <div style="font-size:0.7rem;color:rgba(255,255,255,0.5);margin-top:10px;">Sept 3, {active_year_num}</div>
    <div style="margin-top:10px;">
      <div style="display:flex;justify-content:space-between;font-size:0.62rem;color:rgba(255,255,255,0.5);margin-bottom:4px;">
        <span>Enrollment opens</span><span>Classes begin</span>
      </div>
      <div style="height:7px;background:rgba(255,255,255,0.2);border-radius:4px;overflow:hidden;">
        <div id="cd-bar" style="height:100%;width:0%;background:rgba(255,255,255,0.75);border-radius:4px;"></div>
      </div>
    </div>
  </div>
</div>

<div id="forecastModal" style="display:none;position:fixed;inset:0;z-index:1000;background:rgba(15,32,64,0.55);backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);overflow-y:auto;padding:20px;">
  <div style="max-width:1100px;margin:0 auto;background:white;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,0.25);overflow:hidden;">
    <div style="position:sticky;top:0;background:white;z-index:10;display:flex;align-items:center;justify-content:space-between;padding:18px 28px 16px;border-bottom:1px solid #e2e8f0;">
      <div style="display:flex;align-items:center;gap:10px;">
        <i class="fa fa-chart-line" style="color:#f4a261;font-size:1.1rem;"></i>
        <span style="font-weight:700;font-size:1rem;color:#1e3a5f;">Enrollment Forecast</span>
      </div>
      <button onclick="toggleForecast()" style="background:none;border:none;cursor:pointer;color:#94a3b8;font-size:1.2rem;padding:4px 8px;border-radius:6px;transition:all 0.15s;" onmouseover="this.style.color='#1e3a5f';this.style.background='#f1f5f9'" onmouseout="this.style.color='#94a3b8';this.style.background='none'">
        <i class="fa fa-xmark"></i>
      </button>
    </div>
    <div style="padding:28px;">
      {forecast_section_html}
    </div>
  </div>
</div>
<!-- ── Application Trends ── -->
<div class="section-header" id="app-trends" style="--sh-color:#0072b2;">
  <h2><i class="fa fa-chart-bar" style="color:#0072b2;margin-right:8px;"></i>Fall Application Totals</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">Applications</div>
</div>
<div class="grid-2" style="margin-bottom:20px;">
  <div class="card">
    <div class="card-header">
      <h3>Applications by Year</h3>
      <div class="ch-sub">Total fall applications received per enrollment cycle</div>
    </div>
    <div class="card-body"><div class="chart-wrap"><canvas id="appBar" height="220"></canvas></div></div>
  </div>
  <div class="card">
    <div class="card-header" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;">
      <div>
        <h3>Year-over-Year Growth</h3>
        <div class="ch-sub">Percent change between consecutive enrollment cycles &bull; Last bar = Fall 2026 in progress</div>
      </div>
      <div id="yoyDropdown" style="position:relative;display:inline-block;user-select:none;">
        <div id="yoyDropdownBtn" onclick="toggleYoyDropdown()" style="display:flex;align-items:center;gap:8px;padding:5px 10px 5px 12px;background:#1e3a5f;border:1px solid #2e5082;border-radius:6px;cursor:pointer;font-size:0.75rem;font-weight:500;color:#e2e8f0;white-space:nowrap;">
          <span id="yoyDropdownLabel">Applications</span>
          <svg width="8" height="5" viewBox="0 0 8 5" style="flex-shrink:0;transition:transform 0.2s;" id="yoyChevron"><path d="M0 0l4 5 4-5z" fill="#93c5fd"/></svg>
        </div>
        <div id="yoyDropdownMenu" style="display:none;position:fixed;background:#152a46;border:1px solid #3b5f8a;border-radius:8px;overflow:hidden;box-shadow:0 8px 28px rgba(0,0,0,0.35);z-index:9999;min-width:180px;">
          <div class="yoy-opt" data-val="apps"      style="padding:11px 16px;font-size:0.83rem;font-weight:500;color:white;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.08);">Applications</div>
          <div class="yoy-opt" data-val="newreg"    style="padding:11px 16px;font-size:0.83rem;font-weight:500;color:white;cursor:pointer;border-bottom:1px solid rgba(255,255,255,0.08);">New Registrations</div>
          <div class="yoy-opt" data-val="returning" style="padding:11px 16px;font-size:0.83rem;font-weight:500;color:white;cursor:pointer;">Returning Students</div>
        </div>
      </div>
    </div>
    <div class="card-body"><div class="chart-wrap"><canvas id="appGrowth" height="220"></canvas></div></div>
  </div>
</div>

<div class="section-header" id="app-pace" style="--sh-color:#56b4e9;">
  <h2><i class="fa fa-chart-line" style="color:#56b4e9;margin-right:8px;"></i>Enrollment Pace</h2>
  <div class="sh-line"></div>
  <div style="display:flex;align-items:center;gap:10px;">
    <div class="sh-badge">Pace Comparison</div>
    <button id="forecastBtn" onclick="toggleForecast()" style="display:inline-flex;align-items:center;gap:6px;padding:5px 14px;font-size:0.75rem;font-weight:600;color:#f4a261;background:rgba(244,162,97,0.12);border:1.5px solid rgba(244,162,97,0.4);border-radius:20px;cursor:pointer;transition:all 0.15s;">
      <i class="fa fa-chart-line"></i> Show Forecast
    </button>
  </div>
</div>
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>Cumulative Fall Applications — Enrollment Pace</h3>
    <div class="ch-sub">Dates reflect Fall 2026 calendar &bull; Prior years aligned by week of their enrollment cycle &bull; Toggle years below</div>
  </div>
  <div class="card-body">
    <div class="toggle-group" id="appCumToggles"></div>
    <div class="chart-wrap"><canvas id="appCumLine" height="120"></canvas></div>
  </div>
  <div class="card-footer"><i class="fa fa-circle-info"></i> Use the year toggles above to show or hide individual enrollment cycles. Hover charts for exact values.</div>
</div>

<div class="section-header" id="returning" style="--sh-color:#e69f00;">
  <h2><i class="fa fa-rotate-right" style="color:#e69f00;margin-right:8px;"></i>Returning Students</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">Retention</div>
</div>
<div class="grid-2" style="margin-bottom:20px;">
  <div class="card">
    <div class="card-header">
      <h3>Cumulative New Registrations — Enrollment Pace</h3>
      <div class="ch-sub">New Student + ABC Member + Partner Program combined &bull; Dates reflect Fall 2026 calendar</div>
    </div>
    <div class="card-body">
      <div class="toggle-group" id="newRegToggles"></div>
      <canvas id="newRegCumLine" height="200"></canvas>
    </div>
  </div>
  <div class="card">
    <div class="card-header">
      <h3>Cumulative Returning Registrations — Enrollment Pace</h3>
      <div class="ch-sub">Returning student registration pace by year &bull; Dates reflect Fall 2026 calendar</div>
    </div>
    <div class="card-body">
      <div class="toggle-group" id="retToggles"></div>
      <canvas id="retCumLine" height="200"></canvas>
    </div>
  </div>
</div>

<!-- ── Cohort Dropout Analysis ── -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
    <div>
      <h3><i class="fa fa-arrow-trend-down" style="color:#ef4444;margin-right:6px;"></i>Electrical Program Retention</h3>
      <div class="ch-sub">Track how each cohort progresses through the program year by year</div>
    </div>
    <div style="display:flex;gap:6px;">
      <button id="retViewFunnel" onclick="switchRetView('funnel')"
        style="padding:6px 14px;font-size:0.78rem;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid #1e3a5f;background:#1e3a5f;color:white;transition:all 0.18s;">
        <i class="fa fa-filter"></i> Pipeline
      </button>
      <button id="retViewTrend" onclick="switchRetView('trend')"
        style="padding:6px 14px;font-size:0.78rem;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid #cbd5e1;background:white;color:#64748b;transition:all 0.18s;">
        <i class="fa fa-chart-line"></i> Trend
      </button>
      <button id="retViewLevels" onclick="switchRetView('levels')"
        style="padding:6px 14px;font-size:0.78rem;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid #cbd5e1;background:white;color:#64748b;transition:all 0.18s;">
        <i class="fa fa-layer-group"></i> By Level
      </button>
    </div>
  </div>

  <!-- ── Pipeline Funnel View ── -->
  <div id="retFunnelView" class="card-body">
    <div style="display:flex;gap:8px;margin-bottom:20px;flex-wrap:wrap;" id="cohortYearPills">
{cohort_year_pills_html}    </div>
    <div id="cohortFunnelDisplay" style="max-width:680px;"></div>
  </div>

  <!-- ── Retention Trend View ── -->
  <div id="retTrendView" class="card-body" style="display:none;">
    <canvas id="retTrendChart" height="100"></canvas>
  </div>

  <!-- ── Enrollment by Level View ── -->
  <div id="retLevelsView" class="card-body" style="display:none;">
    <div class="ch-sub" style="margin-bottom:12px;">Electrical students enrolled at each program year, per fall semester &bull; Year 1 = new students; Year 2–4 = returning</div>
    <canvas id="retLevelsChart" height="110"></canvas>
  </div>

  <div class="card-footer"><i class="fa fa-circle-info"></i> Fall 2026 figures are partial — registration is still open. Counts show how many students from that cohort registered at each subsequent level.</div>
</div>

<!-- ── New Student Cumulative Registrations by Trade ── -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
    <div>
      <h3><i class="fa fa-bolt" style="color:#0072b2;margin-right:6px;"></i>Cumulative New Student Registrations — Enrollment Pace</h3>
      <div class="ch-sub">All registration types combined (New Student, ABC Member, Partner Program) &bull; Dates reflect Fall 2026 calendar</div>
    </div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;" id="tradeCumTabs"></div>
  </div>
  <div class="card-body">
    <div class="toggle-group" id="elec1Toggles"></div>
    <div class="chart-wrap"><canvas id="elec1CumLine" height="120"></canvas></div>
  </div>
  <div class="card-footer"><i class="fa fa-circle-info"></i> Combined from New Student, ABC Member, and Partner Program registration forms. Electrical also feeds the Year 1→2 retention funnel above.</div>
</div>

<!-- ── Registration Trends ── -->
<div class="section-header" id="new-reg" style="--sh-color:#009e73;">
  <h2><i class="fa fa-users" style="color:#009e73;margin-right:8px;"></i>All Registrations — Merged View</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">Registrations</div>
</div>

<!-- type legend chips -->
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:16px;">
  <span class="chip" style="background:#dbeafe;color:#1d4ed8;font-size:0.8rem;padding:6px 14px;"><i class="fa fa-circle-dot"></i>&nbsp; New Student &mdash; standard registration form</span>
  <span class="chip" style="background:#fef3c7;color:#92400e;font-size:0.8rem;padding:6px 14px;"><i class="fa fa-circle-dot"></i>&nbsp; New Student (ABC Member) &mdash; ABC employer form</span>
  <span class="chip" style="background:#f3e8ff;color:#6b21a8;font-size:0.8rem;padding:6px 14px;"><i class="fa fa-circle-dot"></i>&nbsp; New Student (Partner Program) &mdash; Cornerstone, Chance for Life, Holly, etc.</span>
</div>

<div class="grid-2" style="margin-bottom:20px;">
  <div class="card">
    <div class="card-header">
      <h3>Total Registrations by Type &amp; Year</h3>
      <div class="ch-sub">All three registration sources stacked — one unified view</div>
    </div>
    <div class="card-body"><canvas id="regTypeStacked" height="220"></canvas></div>
  </div>
  <div class="card">
    <div class="card-header">
      <h3>Registration Type Mix — All Years Combined</h3>
      <div class="ch-sub">Overall share of each new-student registration source</div>
    </div>
    <div class="card-body">
      <canvas id="regTypePct" height="180"></canvas>
      <div style="margin-top:14px;padding:11px 14px;background:#f3e8ff;border-radius:8px;border-left:3px solid #9b5de5;display:flex;align-items:center;gap:12px;">
        <i class="fa fa-handshake" style="color:#9b5de5;font-size:1.1rem;flex-shrink:0;"></i>
        <div>
          <div style="font-size:0.8rem;font-weight:700;color:#6b21a8;">Partner Program &mdash; {reg_partner_total:,} registrations</div>
          <div style="font-size:0.75rem;color:#7c3aed;margin-top:2px;">Active in: {reg_partner_years} &bull; Cornerstone Schools, Chance for Life, Holly Area Schools</div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Per-year type count table -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>Registration Type Counts by Year</h3>
    <div class="ch-sub">Source column shows which form each group came from</div>
  </div>
  <div class="tbl-wrap">
    <table>
      <thead>
        <tr>
          <th>Year</th>
          <th>New Student</th>
          <th>New Student (ABC Member)</th>
          <th>New Student (Partner Program)</th>
          <th>Total New Students</th>
          <th>Source Forms</th>
        </tr>
      </thead>
      <tbody>
        {reg_type_table_rows}
      </tbody>
    </table>
  </div>
  <div class="card-footer"><i class="fa fa-circle-info"></i> All three types are new students — they use separate JotForm forms based on employer affiliation. Returning Student registrations are tracked separately below. The merged dataset with Registration Type column is included in the Excel export.</div>
</div>

<!-- ── Trades ── -->
<div class="section-header" id="trades" style="--sh-color:#cc79a7;">
  <h2><i class="fa fa-hard-hat" style="color:#cc79a7;margin-right:8px;"></i>Program / Trade Breakdown</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">By Trade</div>
</div>
<div class="grid-2" style="margin-bottom:20px;">
  <div class="card">
    <div class="card-header">
      <h3>Applications by Trade (Stacked)</h3>
    </div>
    <div class="card-body"><canvas id="tradeStacked" height="220"></canvas></div>
  </div>
  <div class="card">
    <div class="card-header">
      <h3>Trade Mix — {complete_fall}</h3>
      <div class="ch-sub">Share of total applications by program</div>
    </div>
    <div class="card-body">
      <canvas id="tradePie" height="160"></canvas>
      <div style="margin-top:16px;" id="tradeBars"></div>
    </div>
  </div>
</div>

<!-- ── Locations ── -->
<div class="section-header" id="locations" style="--sh-color:#2a9d8f;">
  <h2><i class="fa fa-location-dot" style="color:#2a9d8f;margin-right:8px;"></i>Campus Location Breakdown</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">By Campus</div>
</div>
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>Applications by Campus (Stacked)</h3>
    <div class="ch-sub">Shift from Madison Heights to new Sterling Heights campus visible in 2025</div>
  </div>
  <div class="card-body"><canvas id="locStacked" height="120"></canvas></div>
  <div class="card-footer"><i class="fa fa-triangle-exclamation" style="color:var(--orange);"></i> A large portion of applicants leave the location field blank ("Not Specified"). This is a data quality opportunity — making the field required would significantly improve campus planning accuracy.</div>
</div>

<!-- ── Winter ── -->
<div class="section-header" id="winter" style="--sh-color:#6c5ce7;">
  <h2><i class="fa fa-snowflake" style="color:#6c5ce7;margin-right:8px;"></i>Winter Enrollment</h2>
  <div class="sh-line"></div>
  <div class="sh-badge">Winter Cycle</div>
</div>
<div class="grid-2" style="margin-bottom:20px;">
  <div class="card">
    <div class="card-header">
      <h3>Winter vs. Fall Applications</h3>
      <div class="ch-sub">Winter is a growing complement to the main fall cycle</div>
    </div>
    <div class="card-body"><canvas id="winterVsFall" height="220"></canvas></div>
  </div>
  <div class="card">
    <div class="card-header">
      <h3>Winter Enrollment Summary</h3>
    </div>
    <div class="card-body" style="padding-top:8px;">
      <div class="tbl-wrap">
        <table>
          <thead><tr><th>Semester</th><th>Applications</th><th>New Registrations</th><th>vs Prior Year</th></tr></thead>
          <tbody>
            <tr><td>Winter 2025</td><td>{w25_app:,}</td><td>{winter_total_new_reg.get("Winter 2025",0):,}</td><td>&mdash;</td></tr>
            <tr><td>Winter 2026</td><td>{w26_app:,}</td><td>{winter_total_new_reg.get("Winter 2026",0):,}</td><td class="pos"><i class="fa fa-arrow-up"></i> {pct_change(w25_app, w26_app)}</td></tr>
          </tbody>
        </table>
      </div>
      <div style="margin-top:20px;">
        <div class="trade-row">
          <div class="trade-label" style="font-size:0.85rem;color:var(--text-muted);">Winter 2025</div>
          <div class="trade-bg"><div class="trade-fill" style="width:{round(w25_app/max(w26_app,1)*100)}%;background:var(--blue-light);"></div></div>
          <div class="trade-pct">{w25_app}</div>
        </div>
        <div class="trade-row">
          <div class="trade-label" style="font-size:0.85rem;color:var(--text-muted);">Winter 2026</div>
          <div class="trade-bg"><div class="trade-fill" style="width:100%;background:var(--green);"></div></div>
          <div class="trade-pct">{w26_app}</div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ── Insights ── -->
<div class="section-header" id="insights" style="--sh-color:#e9c46a;">
  <h2><i class="fa fa-lightbulb" style="color:#e9c46a;margin-right:8px;"></i>Key Findings</h2>
  <div class="sh-line"></div>
</div>
<div class="insight-grid" style="margin-bottom:28px;">
  <div class="insight">
    <div class="insight-icon">&#128200;</div>
    <div>
      <h4>Sustained Application Growth Across Every Fall Cycle</h4>
      <p>Fall applications have grown every single year: {_app_sequence} &mdash; a total increase of <strong>+{_growth_pct}%</strong> over {_growth_span} year{'s' if _growth_span != 1 else ''}. This reflects a strong and consistent demand pipeline. {active_year} is currently at <strong>{app_26:,} applications</strong> through week {fall_2026_week + 1} of enrollment.</p>
    </div>
  </div>
  <div class="insight">
    <div class="insight-icon">&#9889;</div>
    <div>
      <h4>Electrical Dominates, but HVACR Is the Fastest Growing New Program</h4>
      <p>Electrical consistently represents <strong>73–83%</strong> of all fall applications. Carpentry is second at 11–17%.{f" HVACR launched in {_hvacr_launch} and immediately attracted <strong>{_hvacr_count:,} applicants</strong> in its first full year &mdash; a strong debut that signals real market demand for this trade." if _hvacr_launch else ""}</p>
    </div>
  </div>
  <div class="insight" style="border-color:var(--green);">
    <div class="insight-icon">&#127968;</div>
    <div>
      <h4>Sterling Heights Campus Opened With Record Enrollment</h4>
      <p>The transition from Madison Heights to the new Sterling Heights campus in Fall 2025 coincided with the highest application and registration totals in SEMCA's history. Rather than causing a disruption, the new campus appears to have energized interest and driven growth.</p>
    </div>
  </div>
  <div class="insight" style="border-color:var(--orange);">
    <div class="insight-icon">&#128257;</div>
    <div>
      <h4>Returning Student Registrations Are a Growing Foundation</h4>
      <p>Returning registrations have grown from {ret_22:,} ({_first_fall}) to {ret_25:,} ({complete_fall}) — a <strong>{"+" if _ret_growth_pct is not None and _ret_growth_pct > 0 else ""}{_ret_growth_pct if _ret_growth_pct is not None else "N/A"}%</strong> increase. This reflects both a growing multi-year student body and strong program retention. Returning students now make up the majority of total enrollment each year.</p>
    </div>
  </div>
  <div class="insight" style="border-color:var(--yellow);">
    <div class="insight-icon">&#10052;</div>
    <div>
      <h4>Winter Enrollment Is Growing Strongly</h4>
      <p>Winter 2026 applications ({w26_app}) outpaced Winter 2025 ({w25_app}) by <strong>{pct_change(w25_app, w26_app)}</strong>. The winter cycle is becoming a meaningful second enrollment window and warrants dedicated marketing attention.</p>
    </div>
  </div>
  <div class="insight" style="border-color:#f87171;">
    <div class="insight-icon">&#9888;</div>
    <div>
      <h4>Location Data Gap Limits Campus-Level Analysis</h4>
      <p>In Fall 2024 and 2025, approximately <strong>70–80% of applicants</strong> left the campus location field blank. This significantly limits SEMCA's ability to do precise campus-level forecasting or measure the impact of location-specific marketing. Making the field required is a quick fix with high analytical value.</p>
    </div>
  </div>
</div>

<!-- ══ Student Intelligence ══ -->
<div class="section-header" id="student-intel" style="--sh-color:#0072b2;">
  <h2><i class="fa fa-users" style="color:#0072b2;margin-right:8px;"></i>Student Intelligence</h2>
  <div class="sh-line"></div>
  <span class="sh-badge">Data-Driven</span>
</div>

<!-- Card 1: Conversion Rate -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>Application &rarr; Registration Conversion Rate</h3>
    <div class="ch-sub">Email-matched applicants who completed a new-student registration &bull; Hover for exact counts</div>
  </div>
  <div class="card-body">
    <div class="chart-wrap"><canvas id="conversionChart" height="220"></canvas></div>
  </div>
  <div class="card-footer">
    <i class="fa fa-circle-info" style="margin-right:5px;"></i>
    In-progress seasons (Fall 2026, Winter 2026) show lower apparent rates — registrations continue after this report was generated.
    Conversion is computed by normalizing applicant emails to lowercase and intersecting with new-student registration emails.
  </div>
</div>

<!-- Card 2: How Students Find SEMCA -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>How Students Find SEMCA</h3>
    <div class="ch-sub">All seasons combined &bull; "How did you first hear about SEMCA?" &bull; Multi-select — totals exceed application count</div>
  </div>
  <div class="card-body">
    <div class="chart-wrap"><canvas id="mktAttrChart" height="220"></canvas></div>
    <div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap;">
      <div class="chip chip-blue"><i class="fa fa-magnifying-glass" style="margin-right:4px;"></i>
        Google + SEMCA Students = <strong style="margin-left:3px;">{_google_student_pct}%</strong>&nbsp;of all referrals
      </div>
      <div class="chip chip-green"><i class="fa fa-handshake" style="margin-right:4px;"></i>
        Word-of-mouth channels (Student + Employer + Family) = <strong style="margin-left:3px;">{_wom_pct}%</strong>
      </div>
    </div>
  </div>
  <div class="card-footer">Counts reflect all applications across all years and seasons. "Family/Friend/Word of Mouth" added as a distinct option in Fall 2026 / Winter 2026 forms.</div>
</div>

<!-- Card 3: Student Profile (Social Survey) -->
<div class="card" style="margin-bottom:20px;">
  <div class="card-header">
    <h3>Student Profile <span style="font-size:0.75rem;font-weight:400;color:var(--text-muted);">— 2026 Social Media Survey (n={len(_survey_rows)})</span></h3>
    <div class="ch-sub">One-time survey of current students &bull; Platforms, motivators, and communication preferences</div>
  </div>
  <div class="card-body">
    <!-- Stat callouts -->
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:20px;">
      <div style="background:var(--bg);border-radius:var(--radius-sm);padding:14px 16px;border:1px solid var(--border);">
        <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:6px;">Preferred Contact</div>
        <div style="font-size:1.6rem;font-weight:800;color:var(--navy);line-height:1;">Text</div>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{_sv_text_cnt} responses &bull; {round(_sv_text_cnt/_sv_n*100)}% of students</div>
        <div style="font-size:0.75rem;margin-top:6px;color:#0072b2;font-weight:600;">{round(_sv_text_cnt/max(_sv_email_cnt,1), 1)}&times; preferred over email</div>
      </div>
      <div style="background:var(--bg);border-radius:var(--radius-sm);padding:14px 16px;border:1px solid var(--border);">
        <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:6px;">Top Career Influence</div>
        <div style="font-size:1.6rem;font-weight:800;color:var(--navy);line-height:1;">Family</div>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{_sv_family_cnt} of {_sv_n} respondents</div>
        <div style="font-size:0.75rem;margin-top:6px;color:#e69f00;font-weight:600;">{round(_sv_family_cnt/_sv_n*100)}% of career decisions influenced by family</div>
      </div>
      <div style="background:var(--bg);border-radius:var(--radius-sm);padding:14px 16px;border:1px solid var(--border);">
        <div style="font-size:0.68rem;text-transform:uppercase;letter-spacing:0.8px;color:var(--text-muted);margin-bottom:6px;">Top Age Group</div>
        <div style="font-size:1.6rem;font-weight:800;color:var(--navy);line-height:1;">18–22</div>
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:4px;">{_sv_age.get('18-22', 0)} responses &bull; {round(_sv_age.get('18-22',0)/_sv_n*100)}% of students</div>
        <div style="font-size:0.75rem;margin-top:6px;color:#009e73;font-weight:600;">Majority of enrolled students are young adults</div>
      </div>
    </div>
    <!-- Charts row -->
    <div class="grid-2" style="gap:20px;">
      <div>
        <div style="font-size:0.78rem;font-weight:600;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:0.6px;">Platform Usage</div>
        <canvas id="svPlatformChart" height="200"></canvas>
      </div>
      <div>
        <div style="font-size:0.78rem;font-weight:600;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:0.6px;">What Drives Enrollment Action</div>
        <canvas id="svActionChart" height="200"></canvas>
      </div>
    </div>
  </div>
  <div class="card-footer">Survey conducted Spring 2026 with current SEMCA students. Multi-select questions — totals exceed respondent count.</div>
</div>

<!-- Card 4: Demographics -->
<div class="card" style="margin-bottom:28px;">
  <div class="card-header">
    <h3>Applicant Demographics</h3>
    <div class="ch-sub">Fall application cycles only &bull; Race and education breakdown &bull; Grant-reportable aggregates only — no individual records</div>
  </div>
  <div class="card-body">
    <div class="grid-2" style="gap:20px;">
      <div>
        <div style="font-size:0.78rem;font-weight:600;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:0.6px;">Race / Ethnicity by Year <span style="font-weight:400;font-size:0.7rem;">(primary reported)</span></div>
        <canvas id="demoRaceChart" height="200"></canvas>
      </div>
      <div>
        <div style="font-size:0.78rem;font-weight:600;color:var(--text-muted);margin-bottom:10px;text-transform:uppercase;letter-spacing:0.6px;">Education Level (All Fall Years Combined)</div>
        <canvas id="demoEduChart" height="200"></canvas>
      </div>
    </div>
  </div>
  <div class="card-footer">Race labels were standardized across form versions (2022 used different nomenclature). First reported race is used for individuals who selected multiple. Education reflects self-reported highest level completed at time of application.</div>
</div>

<!-- ── Recommendations ── -->
<div class="section-header" id="recommendations" style="--sh-color:#d55e00;">
  <h2><i class="fa fa-list-check" style="color:#d55e00;margin-right:8px;"></i>Recommendations</h2>
  <div class="sh-line"></div>
</div>
<div class="rec-grid" style="margin-bottom:28px;">
  <div class="rec">
    <div class="rec-badge">1</div>
    <div>
      <h4>Front-Load Recruiting &mdash; The First 4–6 Weeks Are Critical</h4>
      <p>Week-by-week data shows the steepest application intake occurs in the first 4–6 weeks of each enrollment cycle. Concentrating social media, employer outreach, and school visit campaigns <em>before and immediately at launch</em> would capture a larger portion of the addressable market while intent is highest.</p>
    </div>
  </div>
  <div class="rec">
    <div class="rec-badge">2</div>
    <div>
      <h4>Invest in Carpentry and HVACR Program Growth</h4>
      <p>Carpentry grew from 33 applicants in 2022 to 81 in 2025. HVACR launched in 2025 with strong demand. These two programs represent SEMCA's best opportunity to diversify beyond Electrical and reduce concentration risk. Dedicated program-specific marketing (separate from the general "learn a trade" message) would accelerate this.</p>
    </div>
  </div>
  <div class="rec">
    <div class="rec-badge">3</div>
    <div>
      <h4>Make Campus Location a Required Field on Application Forms</h4>
      <p>70–80% of recent applicants skip the location field. Requiring this field (with a clear dropdown of campus options) would cost SEMCA nothing to implement in JotForm and would immediately unlock accurate campus-level enrollment forecasting, staffing planning, and marketing attribution by location.</p>
    </div>
  </div>
  <div class="rec">
    <div class="rec-badge">4</div>
    <div>
      <h4>Add a Shared Identifier Across Forms to Track Conversion</h4>
      <p>Currently, applications and registrations are siloed — there is no way to link an applicant to their eventual registration. Adding a shared field (email is sufficient) would let SEMCA calculate application-to-registration conversion rate, identify where drop-off occurs, and measure the ROI of recruitment activities.</p>
    </div>
  </div>
  <div class="rec">
    <div class="rec-badge">5</div>
    <div>
      <h4>Run a Dedicated Winter Enrollment Campaign</h4>
      <p>Winter 2026 grew {pct_change(w25_app, w26_app)} over Winter 2025. With targeted outreach (particularly to employer partners who hire mid-year), the winter cycle could become a significantly larger second enrollment window without cannibalizing fall numbers.</p>
    </div>
  </div>
  <div class="rec">
    <div class="rec-badge">6</div>
    <div>
      <h4>Establish a Weekly Enrollment Pace Dashboard</h4>
      <p>This analysis can be regenerated any time the JotForm data is re-synced. Consider running the sync script weekly during enrollment periods and sharing the pace chart with leadership — it provides an early warning system if a given year is trending behind prior cycles and allows time to respond with targeted outreach.</p>
    </div>
  </div>
</div>

<!-- ── Full Data Table ── -->
<div class="section-header" id="data-table" style="--sh-color:#64748b;">
  <h2><i class="fa fa-table" style="color:#64748b;margin-right:8px;"></i>Full Data Table</h2>
  <div class="sh-line"></div>
</div>
<div class="card" style="margin-bottom:20px;">
  <div class="card-header" style="padding-bottom:16px;">
    <h3>Fall Semester Summary</h3>
    <div class="ch-sub">All figures as of {now_str}. Fall 2026 is in progress.</div>
  </div>
  <div class="tbl-wrap">
    <table id="summaryTable">
      <thead>
        <tr>
          <th>Year</th>
          <th>Applications</th>
          <th>New Students</th>
          <th>ABC Member</th>
          <th>Partner Program</th>
          <th>Returning</th>
          <th>Total Enrolled</th>
          <th>% Electrical</th>
          <th>Status</th>
        </tr>
      </thead>
      <tbody>
        {summary_table_rows}
      </tbody>
    </table>
  </div>
</div>

</div><!-- /content -->
</div><!-- /main -->

<script>
// ── Chart defaults ──
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size = 12;
Chart.defaults.color = '#64748b';
Chart.defaults.plugins.legend.labels.boxWidth = 12;
Chart.defaults.plugins.legend.labels.padding = 16;

// ── Gradient bar plugin ──
// Reads _gradTop / _gradBot from each dataset and fills with a vertical canvas gradient
Chart.register({{
  id: 'gradientBar',
  beforeDatasetsDraw(chart) {{
    const {{ctx, chartArea}} = chart;
    if (!chartArea) return;
    chart.data.datasets.forEach(ds => {{
      if (!ds._gradTop) return;
      const g = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
      g.addColorStop(0, ds._gradTop);
      g.addColorStop(1, ds._gradBot);
      ds.backgroundColor = g;
    }});
  }}
}});

// SEMCA_FALL_MAIN_START
const YEARS = {json.dumps(fall_years)};
const COLORS = {json.dumps({y: COLORS[y] for y in fall_years})};
const BAR_COLORS = YEARS.map(y => COLORS[y]);

const APP_TOTALS = {json.dumps([fall_app_totals.get(y,0) for y in fall_years])};
const NEW_REG = {json.dumps([fall_total_new_reg.get(y,0) for y in fall_years])};
const RET_REG = {json.dumps([fall_returning_totals.get(y,0) for y in fall_years])};
const PROJ_APPS    = {json.dumps(_proj_app_list)};
const PROJ_NEW_REG = {json.dumps(_proj_new_list)};
const PROJ_RET     = {json.dumps(_proj_ret_list)};
const ACTIVE_IDX   = {_active_fall_idx};
// SEMCA_FALL_MAIN_END

// SEMCA_TRADE_DATA_START
// ── Live refresh config ──
const PROXY_URL = "/api/counts";
const TRADE_CUM_DATA = {json.dumps(trade_cum_data)};
const TRADE_TAB_COLORS = {{"Electrical":"#0072b2","Carpentry":"#e69f00","HVACR":"#cc79a7","Plumbing":"#009e73"}};
// SEMCA_TRADE_DATA_END

// ── Shared bar options ──
// (defined before first use)
const barOpts = (stacked) => ({{
  responsive: true,
  plugins: {{
    legend: {{ display: stacked, position: "top" }},
    tooltip: {{ callbacks: {{ label: c => " " + c.dataset.label + ": " + c.raw.toLocaleString() }} }},
  }},
  scales: {{
    x: {{ stacked, grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
    y: {{ stacked, beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }}
  }}
}});

// ── App bar ──
const _activeColor   = ACTIVE_IDX >= 0 ? BAR_COLORS[ACTIVE_IDX] : "#ea580c";
const _projGap       = YEARS.map((_, i) =>
  (i === ACTIVE_IDX && PROJ_APPS[i] > APP_TOTALS[i]) ? PROJ_APPS[i] - APP_TOTALS[i] : null
);
const _hasProj       = _projGap.some(v => v !== null);
const _solidRadii    = YEARS.map((_, i) =>
  (_hasProj && i === ACTIVE_IDX) ? {{ topLeft:0, topRight:0, bottomLeft:6, bottomRight:6 }} : 8
);
new Chart(document.getElementById("appBar"), {{
  type: "bar",
  data: {{ labels: YEARS, datasets: [
    {{
      label: "Confirmed",
      data: APP_TOTALS,
      backgroundColor: BAR_COLORS,
      borderColor: BAR_COLORS.map(c => c + "bb"),
      borderWidth: {{ top: 0, right: 1, bottom: 1, left: 1 }},
      borderRadius: _solidRadii,
      borderSkipped: false,
      stack: "apps"
    }},
    {{
      label: "Projected",
      data: _projGap,
      backgroundColor: _activeColor + "33",
      borderColor: _activeColor,
      borderWidth: {{ top: 2, right: 2, bottom: 0, left: 2 }},
      borderDash: [5, 3],
      borderRadius: {{ topLeft:8, topRight:8, bottomLeft:0, bottomRight:0 }},
      borderSkipped: false,
      stack: "apps"
    }}
  ] }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: c => {{
            if (c.datasetIndex === 1) return ` Projected total: ${{(APP_TOTALS[c.dataIndex] + (c.raw || 0)).toLocaleString()}}`;
            return ` Confirmed: ${{c.raw.toLocaleString()}}`;
          }}
        }}
      }}
    }},
    scales: {{
      x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
      y: {{ stacked: true, beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }}
    }}
  }}
}});

// ── YoY % growth chart with metric dropdown ──
function yoyPct(arr) {{
  return arr.slice(1).map((v, i) => {{
    const old = arr[i];
    if (!old) return null;
    return parseFloat(((v - old) / old * 100).toFixed(1));
  }});
}}
function yoyPctProj(actual, projected) {{
  return actual.slice(1).map((v, i) => {{
    const src = (i === actual.length - 2) ? projected[i + 1] : actual[i + 1];
    const old = actual[i];
    if (!old) return null;
    return parseFloat(((src - old) / old * 100).toFixed(1));
  }});
}}
const YOY_LABELS = YEARS.slice(1).map((y, i) => "'" + YEARS[i].replace("Fall ","") + " → '" + y.replace("Fall ",""));
const YOY_METRICS = {{
  apps:      {{ label: "Applications",       data: yoyPctProj(APP_TOTALS, PROJ_APPS),    color: "#0072b2" }},
  newreg:    {{ label: "New Registrations",  data: yoyPctProj(NEW_REG,    PROJ_NEW_REG), color: "#009e73" }},
  returning: {{ label: "Returning Students", data: yoyPctProj(RET_REG,    PROJ_RET),     color: "#e69f00" }},
}};
function yoyBarColors(data, baseColor) {{
  return data.map((v, i) => {{
    if (i === data.length - 1) return baseColor + "50";
    return (v != null && v >= 0) ? baseColor : "#ef4444";
  }});
}}
function yoyBorderColors(data, baseColor) {{
  return data.map((v, i) => i === data.length - 1 ? baseColor : "transparent");
}}
let yoyMetric = "apps";
function yoyDataset() {{
  const m = YOY_METRICS[yoyMetric];
  return {{
    label: m.label + " YoY %", data: m.data,
    backgroundColor: yoyBarColors(m.data, m.color),
    borderColor: yoyBorderColors(m.data, m.color),
    borderWidth: 2, borderRadius: 5, borderSkipped: false
  }};
}}
const yoyChart = new Chart(document.getElementById("appGrowth"), {{
  type: "bar",
  data: {{ labels: YOY_LABELS, datasets: [yoyDataset()] }},
  options: {{
    responsive: true,
    interaction: {{ mode: "index", intersect: false }},
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{ callbacks: {{ label: ctx => {{
        const v = ctx.raw;
        if (v == null) return "N/A";
        const sfx = ctx.dataIndex === YOY_LABELS.length - 1 ? " (projected)" : "";
        return (v >= 0 ? "+" : "") + v + "%" + sfx;
      }} }} }}
    }},
    layout: {{ padding: {{ left: 0, right: 0, top: 8, bottom: 0 }} }},
    scales: {{
      y: {{ grid: {{ color: "#f1f5f9" }}, ticks: {{ callback: v => v + "%", maxTicksLimit: 6 }} }},
      x: {{ grid: {{ display: false }}, ticks: {{ maxRotation: 0 }} }}
    }}
  }}
}});
function toggleYoyDropdown() {{
  const menu = document.getElementById("yoyDropdownMenu");
  const btn  = document.getElementById("yoyDropdownBtn");
  const chev = document.getElementById("yoyChevron");
  const open = menu.style.display === "none";
  if (open) {{
    const r = btn.getBoundingClientRect();
    menu.style.top  = (r.bottom + 5) + "px";
    menu.style.left = r.left + "px";
  }}
  menu.style.display = open ? "block" : "none";
  chev.style.transform = open ? "rotate(180deg)" : "";
}}
document.querySelectorAll(".yoy-opt").forEach(opt => {{
  opt.addEventListener("mouseenter", () => opt.style.background = "rgba(255,255,255,0.08)");
  opt.addEventListener("mouseleave", () => opt.style.background = "");
  opt.addEventListener("click", () => {{
    yoyMetric = opt.dataset.val;
    document.getElementById("yoyDropdownLabel").textContent = opt.textContent;
    document.getElementById("yoyDropdownMenu").style.display = "none";
    document.getElementById("yoyChevron").style.transform = "";
    // Mark active
    document.querySelectorAll(".yoy-opt").forEach(o => o.style.color = "#e2e8f0");
    opt.style.color = "#93c5fd";
    const ds = yoyDataset();
    yoyChart.data.datasets[0].data = ds.data;
    yoyChart.data.datasets[0].backgroundColor = ds.backgroundColor;
    yoyChart.data.datasets[0].borderColor = ds.borderColor;
    yoyChart.data.datasets[0].borderWidth = ds.borderWidth;
    yoyChart.data.datasets[0].label = ds.label;
    yoyChart.update();
  }});
}});
document.addEventListener("click", e => {{
  if (!document.getElementById("yoyDropdown").contains(e.target)) {{
    document.getElementById("yoyDropdownMenu").style.display = "none";
    document.getElementById("yoyChevron").style.transform = "";
  }}
}});

// ── Cumulative chart builder with toggles ──
function buildCumulativeChart(canvasId, togglesId, labels, datasets, schoolStartIdx, inlinePills) {{
  const canvas = document.getElementById(canvasId);
  const togglesEl = document.getElementById(togglesId);

  const schoolLinePlugin = {{
    id: "schoolLine_" + canvasId,
    afterDraw(chart) {{
      if (schoolStartIdx == null || schoolStartIdx < 0 || schoolStartIdx >= chart.data.labels.length) return;
      const ctx = chart.ctx;
      const xScale = chart.scales.x;
      const yScale = chart.scales.y;
      const x = xScale.getPixelForValue(schoolStartIdx);
      const top = yScale.top;
      const bot = yScale.bottom;
      ctx.save();

      // Solid prominent line
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, bot);
      ctx.lineWidth = 2;
      ctx.strokeStyle = "rgba(234,88,12,0.85)";
      ctx.setLineDash([5, 3]);
      ctx.stroke();
      ctx.setLineDash([]);

      // Label — no box, just bold text with a subtle shadow
      const _text = "Classes Begin";
      ctx.font = "700 11px 'Inter', sans-serif";
      const _tw = ctx.measureText(_text).width;
      const _flipLeft = x + 8 + _tw > xScale.right;
      const _lx = _flipLeft ? x - _tw - 8 : x + 8;
      const _ly = top + 14;
      ctx.shadowColor = "rgba(255,255,255,0.9)";
      ctx.shadowBlur = 4;
      ctx.fillStyle = "#c2410c";
      ctx.fillText(_text, _lx, _ly);
      ctx.shadowBlur = 0;

      ctx.restore();
    }}
  }};

  // Apply solid-vs-dashed styling: solid up to lastKnownWeek, dashed beyond
  const styledDatasets = datasets.map(ds => {{
    const lkw = ds.lastKnownWeek ?? Infinity;
    return Object.assign({{}}, ds, {{
      segment: {{
        borderDash:      ctx => ctx.p1DataIndex > lkw ? [7, 4] : undefined,
        borderColor:     ctx => ctx.p1DataIndex > lkw ? ds.borderColor + "aa" : ds.borderColor,
        backgroundColor: ctx => ctx.p1DataIndex > lkw ? ds.borderColor + "08" : ds.borderColor + "40",
      }}
    }});
  }});

  let chart = new Chart(canvas, {{
    type: "line",
    data: {{ labels, datasets: styledDatasets }},
    options: {{
      responsive: true,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{ legend: {{ display: false }} }},
      scales: {{ y: {{ beginAtZero: true, grid: {{ color: '#f1f5f9' }} }}, x: {{ grid: {{ color: '#f8fafc' }} }} }}
    }},
    plugins: [schoolLinePlugin]
  }});

  // Build pill toggles — inline or dropdown
  function makePill(ds, i, container) {{
    const pill = document.createElement("span");
    pill.className = "toggle-pill";
    pill.textContent = ds.label;
    pill.style.borderColor = ds.borderColor;
    pill.style.color = ds.borderColor;
    pill.style.background = ds.borderColor + "18";
    pill.dataset.idx = i;
    pill.addEventListener("click", () => {{
      const meta = chart.getDatasetMeta(i);
      meta.hidden = !meta.hidden;
      pill.style.opacity = meta.hidden ? "0.3" : "1";
      chart.update();
    }});
    container.appendChild(pill);
  }}

  if (inlinePills) {{
    togglesEl.style.cssText += ";display:flex;flex-wrap:wrap;gap:6px;";
    datasets.forEach((ds, i) => makePill(ds, i, togglesEl));
  }} else {{
    const uid = canvasId + "_dd";
    const btn = document.createElement("button");
    btn.id = uid + "_btn";
    btn.style.cssText = "display:inline-flex;align-items:center;gap:6px;padding:4px 10px 4px 11px;font-size:0.75rem;font-weight:600;color:#1e3a5f;background:#f0f4f8;border:1.5px solid #cbd5e1;border-radius:6px;cursor:pointer;outline:none;";
    btn.innerHTML = '<i class="fa fa-layer-group" style="font-size:0.7rem;opacity:0.7;"></i> Years <svg width="8" height="5" viewBox="0 0 8 5" id="' + uid + '_chev" style="transition:transform 0.2s;"><path d="M0 0l4 5 4-5z" fill="#1e3a5f"/></svg>';
    togglesEl.appendChild(btn);

    const menu = document.createElement("div");
    menu.id = uid + "_menu";
    menu.style.cssText = "display:none;position:fixed;background:white;border:1.5px solid #e2e8f0;border-radius:10px;box-shadow:0 8px 24px rgba(0,0,0,0.12);z-index:9999;padding:10px 12px;flex-wrap:wrap;gap:6px;max-width:280px;";
    document.body.appendChild(menu);

    datasets.forEach((ds, i) => makePill(ds, i, menu));

    function positionMenu() {{
      const r = btn.getBoundingClientRect();
      menu.style.top  = (r.bottom + 5) + "px";
      menu.style.left = r.left + "px";
    }}

    btn.addEventListener("click", e => {{
      e.stopPropagation();
      const open = menu.style.display === "none" || menu.style.display === "";
      document.querySelectorAll("[id$='_menu']").forEach(m => {{ m.style.display = "none"; }});
      document.querySelectorAll("[id$='_chev']").forEach(c => {{ c.style.transform = ""; }});
      if (open) {{ positionMenu(); menu.style.display = "flex"; document.getElementById(uid + "_chev").style.transform = "rotate(180deg)"; }}
    }});

    document.addEventListener("click", () => {{
      menu.style.display = "none";
      const chev = document.getElementById(uid + "_chev");
      if (chev) chev.style.transform = "";
    }});
  }}

  return chart;
}}

buildCumulativeChart("appCumLine", "appCumToggles",
  {json.dumps(app_cum_labels)}, {json.dumps(app_cum_datasets)}, {app_school_start_idx}, true);
buildCumulativeChart("newRegCumLine", "newRegToggles",
  {json.dumps(new_reg_cum_labels)}, {json.dumps(new_reg_cum_datasets)}, {new_reg_school_start_idx}, true);
buildCumulativeChart("retCumLine", "retToggles",
  {json.dumps(ret_cum_labels)}, {json.dumps(ret_cum_datasets)}, {ret_school_start_idx}, true);

// ── Trade tab cumulative chart ──────────────────────────────────────────────
(function() {{
  const tabsEl = document.getElementById("tradeCumTabs");
  const trades = Object.keys(TRADE_CUM_DATA);

  function switchTrade(trade) {{
    // Update tab styles
    tabsEl.querySelectorAll(".trade-tab-btn").forEach(btn => {{
      const active = btn.dataset.trade === trade;
      btn.style.background   = active ? "#1e3a5f" : "white";
      btn.style.color        = active ? "white"   : "#64748b";
      btn.style.borderColor  = active ? "#1e3a5f" : "#cbd5e1";
    }});
    // Destroy existing chart on canvas
    const existing = Chart.getChart("elec1CumLine");
    if (existing) existing.destroy();
    // Clear year toggles
    const togglesEl = document.getElementById("elec1Toggles");
    togglesEl.innerHTML = "";
    // Build chart for selected trade
    const d = TRADE_CUM_DATA[trade];
    if (d) buildCumulativeChart("elec1CumLine", "elec1Toggles", d.labels, d.datasets, d.schoolStartIdx, true);
  }}

  trades.forEach(trade => {{
    const btn = document.createElement("button");
    btn.className = "trade-tab-btn";
    btn.dataset.trade = trade;
    btn.textContent = trade;
    btn.style.cssText = "padding:6px 14px;font-size:0.78rem;font-weight:600;border-radius:20px;cursor:pointer;border:1.5px solid #cbd5e1;background:white;color:#64748b;transition:all 0.18s;";
    btn.addEventListener("click", () => switchTrade(trade));
    tabsEl.appendChild(btn);
  }});

  // Initialize with Electrical
  switchTrade("Electrical");
}})();

// ── Registration type stacked count bar ──
new Chart(document.getElementById("regTypeStacked"), {{
  type: "bar",
  data: {{ labels: YEARS, datasets: {reg_type_stacked_datasets} }},
  options: barOpts(true),
}});

// ── Registration type mix doughnut (all-years aggregate) ──
const REG_TYPE_AGG = {reg_type_agg_json};
const REG_TYPE_COLORS_MAP = {reg_type_colors_json};
const regPieLabels = Object.keys(REG_TYPE_AGG);
const regPieData   = regPieLabels.map(k => REG_TYPE_AGG[k]);
const regPieColors = regPieLabels.map(k => REG_TYPE_COLORS_MAP[k] || "#aaa");
const regPieTotal  = regPieData.reduce((a, b) => a + b, 0);
new Chart(document.getElementById("regTypePct"), {{
  type: "doughnut",
  data: {{
    labels: regPieLabels,
    datasets: [{{ data: regPieData, backgroundColor: regPieColors, borderWidth: 3, borderColor: "white", hoverOffset: 14, borderRadius: 5 }}]
  }},
  options: {{
    responsive: true,
    cutout: "62%",
    plugins: {{
      legend: {{ position: "right" }},
      tooltip: {{ callbacks: {{ label: c => " " + c.label + ": " + c.raw.toLocaleString() + " (" + Math.round(regPieTotal ? c.raw / regPieTotal * 100 : 0) + "%)" }} }}
    }}
  }}
}});

// ── Trades stacked ──
new Chart(document.getElementById("tradeStacked"), {{
  type: "bar",
  data: {{ labels: YEARS, datasets: {json.dumps(trade_datasets)} }},
  options: barOpts(true),
}});

// ── Trade pie (most recent complete fall) ──
const TRADE_COMPLETE = {json.dumps({t: fall_app_trades.get(complete_fall, {}).get(t, 0) for t in all_trades})};
const TRADE_COLORS_MAP = {json.dumps(TRADE_COLORS)};
const tradePieLabels = Object.keys(TRADE_COMPLETE).filter(k => TRADE_COMPLETE[k] > 0);
const tradePieData = tradePieLabels.map(k => TRADE_COMPLETE[k]);
const tradePieColors = tradePieLabels.map(k => TRADE_COLORS_MAP[k] || "#aaa");
new Chart(document.getElementById("tradePie"), {{
  type: "doughnut",
  data: {{ labels: tradePieLabels, datasets: [{{ data: tradePieData, backgroundColor: tradePieColors, borderWidth: 3, borderColor: "white", hoverOffset: 14, borderRadius: 5 }}] }},
  options: {{ responsive: true, cutout: "62%", plugins: {{ legend: {{ position: "right" }}, tooltip: {{ callbacks: {{ label: c => " " + c.label + ": " + c.raw + " (" + Math.round(c.raw/(tradePieData.reduce((a,b)=>a+b,0)||1)*100) + "%)" }} }} }} }}
}});

// Trade progress bars
const tradeBarsEl = document.getElementById("tradeBars");
const total2025 = tradePieData.reduce((a,b) => a+b, 0);
const tradeBarGrads = {{
  "Electrical":      "linear-gradient(90deg,#56b4e9,#0072b2)",
  "Carpentry":       "linear-gradient(90deg,#93c5fd,#56b4e9)",
  "HVACR":           "linear-gradient(90deg,#fcd34d,#e69f00)",
  "Welding":         "linear-gradient(90deg,#6ee7b7,#009e73)",
  "Intro / Pre-App": "linear-gradient(90deg,#f0abfc,#cc79a7)",
  "CCL":             "linear-gradient(90deg,#fb923c,#d55e00)",
  "Plumbing":        "linear-gradient(90deg,#c084fc,#7b2d8b)",
}};
tradePieLabels.forEach((t, i) => {{
  const pct = Math.round(tradePieData[i] / (total2025 || 1) * 100);
  const fill = tradeBarGrads[t] || `linear-gradient(90deg,${{tradePieColors[i]}},${{tradePieColors[i]}})`;
  tradeBarsEl.innerHTML += `<div class="trade-row">
    <div class="trade-label">${{t}}</div>
    <div class="trade-bg"><div class="trade-fill" style="width:${{pct}}%;background:${{fill}};"></div></div>
    <div class="trade-pct">${{pct}}%</div>
  </div>`;
}});

// ── Locations stacked ──
new Chart(document.getElementById("locStacked"), {{
  type: "bar",
  data: {{ labels: YEARS, datasets: {json.dumps(loc_datasets)} }},
  options: barOpts(true),
}});

// ── Winter vs Fall ──
new Chart(document.getElementById("winterVsFall"), {{
  type: "bar",
  data: {{
    labels: {_winter_chart_labels},
    datasets: [
      {{ label: "Fall Applications",   data: {_winter_chart_fall},   _gradTop: "#93c5fd", _gradBot: "#0072b2", borderRadius: 8, borderSkipped: false }},
      {{ label: "Winter Applications", data: {_winter_chart_winter}, _gradTop: "#6ee7b7", _gradBot: "#009e73", borderRadius: 8, borderSkipped: false }},
    ]
  }},
  options: barOpts(false),
}});

// ── Forecast modal ──
function toggleForecast() {{
  const modal = document.getElementById("forecastModal");
  const btn   = document.getElementById("forecastBtn");
  const open  = modal.style.display === "none";
  modal.style.display = open ? "block" : "none";
  document.body.style.overflow = open ? "hidden" : "";
  btn.innerHTML = open
    ? '<i class="fa fa-chart-line"></i> Hide Forecast'
    : '<i class="fa fa-chart-line"></i> Show Forecast';
}}
document.addEventListener("keydown", e => {{
  if (e.key === "Escape") {{
    const modal = document.getElementById("forecastModal");
    if (modal.style.display !== "none") toggleForecast();
  }}
}});
document.getElementById("forecastModal").addEventListener("click", e => {{
  if (e.target === document.getElementById("forecastModal")) toggleForecast();
}});

// ── Sidebar active state ──
const sections = document.querySelectorAll('[id]');
const navLinks = document.querySelectorAll('.sidebar-nav a');
const observer = new IntersectionObserver(entries => {{
  entries.forEach(e => {{
    if (e.isIntersecting) {{
      const link = document.querySelector(`.sidebar-nav a[href="#${{e.target.id}}"]`);
      if (link) {{
        navLinks.forEach(a => a.classList.remove('active'));
        link.classList.add('active');
      }}
    }}
  }});
}}, {{ threshold: 0.3 }});
sections.forEach(s => observer.observe(s));

// ── CSV export ──
const CSV_DATA = {csv_rows_json};
function exportCSV() {{
  const keys = Object.keys(CSV_DATA[0]);
  const rows = [keys.join(","), ...CSV_DATA.map(r => keys.map(k => r[k]).join(","))];
  const blob = new Blob([rows.join("\\n")], {{ type: "text/csv" }});
  const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
  a.download = "SEMCA_Enrollment_Data.csv"; a.click();
}}

// ── Excel export ──
function exportExcel() {{
  const wb = XLSX.utils.book_new();
  // Summary sheet
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(CSV_DATA), "Summary");
  // Trade breakdown sheet
  const tradeData = YEARS.map(y => {{
    const row = {{ Year: y }};
    {json.dumps(all_trades)}.forEach(t => {{
      row[t] = ({json.dumps({y: fall_app_trades.get(y, {}) for y in fall_years})}[y] || {{}})[t] || 0;
    }});
    return row;
  }});
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(tradeData), "Trade Breakdown");
  // Location sheet
  const locData = YEARS.map(y => {{
    const row = {{ Year: y }};
    {json.dumps(all_locs)}.forEach(l => {{
      row[l] = ({json.dumps({y: fall_app_locations.get(y, {}) for y in fall_years})}[y] || {{}})[l] || 0;
    }});
    return row;
  }});
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(locData), "Location Breakdown");
  // Winter sheet
  const winterData = {winter_data_json};
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(winterData), "Winter Enrollment");
  // Merged new-student registrations sheet (with Registration Type column)
  const mergedRegData = {json.dumps(new_student_registrations)};
  XLSX.utils.book_append_sheet(wb, XLSX.utils.json_to_sheet(mergedRegData), "New Student Registrations");
  XLSX.writeFile(wb, "SEMCA_Enrollment_Analysis.xlsx");
}}

// ── Animated number roll-up ──
function animateHeroNum(el, target) {{
  const from = parseInt(el.textContent.replace(/[^0-9]/g, "")) || 0;
  const dur  = 550;
  let t0 = null;
  (function step(ts) {{
    if (!t0) t0 = ts;
    const p = Math.min((ts - t0) / dur, 1);
    const e = 1 - Math.pow(1 - p, 3);
    el.textContent = Math.round(from + (target - from) * e).toLocaleString();
    if (p < 1) requestAnimationFrame(step);
  }})(performance.now());
}}

// ── Hero stats year selector ──
function updateHeroStats(idx) {{
  const year  = YEARS[idx];
  const short = year.replace("Fall ", "");
  const prev  = idx > 0 ? idx - 1 : null;
  const prevYear = prev !== null ? YEARS[prev].replace("Fall ", "") : null;

  function pct(o, n) {{
    if (o == null || o === 0) return null;
    const v = ((n - o) / o * 100).toFixed(1);
    return (parseFloat(v) >= 0 ? "+" : "") + v + "%";
  }}
  function setChange(elId, val, prevVal, prevYr) {{
    const el = document.getElementById(elId);
    const p = pct(prevVal, val);
    if (p === null) {{
      el.className = "hs-change neutral";
      el.innerHTML = "Earliest year on record";
    }} else {{
      const up = parseFloat(p) >= 0;
      el.className = "hs-change " + (up ? "pos" : "neg");
      el.innerHTML = '<i class="fa fa-arrow-trend-' + (up ? "up" : "down") + '"></i> ' + p + " vs " + prevYr;
    }}
  }}

  const isActive = ACTIVE_IDX >= 0 && idx === ACTIVE_IDX;
  const apps   = isActive ? PROJ_APPS[idx]    : APP_TOTALS[idx];
  const newreg = isActive ? PROJ_NEW_REG[idx] : NEW_REG[idx];
  const ret    = isActive ? PROJ_RET[idx]     : RET_REG[idx];
  const pApps  = prev !== null ? APP_TOTALS[prev] : null;
  const pNew   = prev !== null ? NEW_REG[prev]    : null;
  const pRet   = prev !== null ? RET_REG[prev]    : null;
  const projSuffix = isActive ? " (projected)" : "";

  document.getElementById("hs-app-label").textContent = year + " Applications" + projSuffix;
  animateHeroNum(document.getElementById("hs-app-num"), apps);
  setChange("hs-app-change", apps, pApps, prevYear);

  document.getElementById("hs-new-label").textContent = year + " New Enrollments" + projSuffix;
  animateHeroNum(document.getElementById("hs-new-num"), newreg);
  setChange("hs-new-change", newreg, pNew, prevYear);

  document.getElementById("hs-ret-label").textContent = "Returning Students (F" + short.slice(-2) + ")" + projSuffix;
  animateHeroNum(document.getElementById("hs-ret-num"), ret);
  setChange("hs-ret-change", ret, pRet, prevYear);

  const baseIdx   = 0;
  const baseYear  = YEARS[baseIdx].replace("Fall ", "");
  const baseApps  = APP_TOTALS[baseIdx];
  const span      = idx - baseIdx;
  const growthPct = baseApps ? (((apps - baseApps) / baseApps) * 100).toFixed(0) : 0;
  document.getElementById("hs-growth-label").textContent  = span + "-Year App Growth";
  document.getElementById("hs-growth-num").textContent    = (growthPct >= 0 ? "+" : "") + growthPct + "%";
  document.getElementById("hs-growth-change").textContent = baseApps.toLocaleString() + " (" + baseYear + ") → " + apps.toLocaleString() + " (" + short + ")";
}}

// ── Semester countdown ──
(function() {{
  const target  = new Date("{active_semester_start.strftime('%Y-%m-%dT08:00:00')}");
  const enrOpen = new Date("{fall_app_start.get("Fall 2026").strftime("%Y-%m-%dT%H:%M:%S") if fall_app_start.get("Fall 2026") else "2026-05-04T00:00:00"}");
  const total   = target - enrOpen;
  // Progress bar is weeks-scale — set once, never touch it again
  const barPct = Math.min(100, Math.max(0, (Date.now() - enrOpen) / total * 100));
  const bar = document.getElementById("cd-bar");
  if (bar) bar.style.width = barPct.toFixed(1) + "%";
  function tick() {{
    const now  = Date.now();
    const diff = target - now;
    if (diff <= 0) {{
      document.getElementById("countdown").innerHTML = '<span style="font-size:1rem;font-weight:700;color:rgba(255,255,255,0.85);">Semester has started!</span>';
      return;
    }}
    const d = Math.floor(diff / 86400000);
    const h = Math.floor((diff % 86400000) / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    const s = Math.floor((diff % 60000) / 1000);
    document.getElementById("cd-days").textContent = String(d).padStart(2,"0");
    document.getElementById("cd-hrs").textContent  = String(h).padStart(2,"0");
    document.getElementById("cd-min").textContent  = String(m).padStart(2,"0");
    document.getElementById("cd-sec").textContent  = String(s).padStart(2,"0");
  }}
  tick();
  setInterval(tick, 1000);
}})();


// ── Electrical Retention — funnel + trend views ──────────────────────────────
const COHORT_FUNNELS = {json.dumps(cohort_funnels)};
const RET_TREND_LABELS = {json.dumps(_ret_trend_labels)};
const RET_TREND_E1E2   = {json.dumps(_ret_trend_e1e2)};
const RET_TREND_E2E3   = {json.dumps(_ret_trend_e2e3)};
const RET_TREND_E3E4   = {json.dumps(_ret_trend_e3e4)};
const LEVEL_BAR_LABELS = {json.dumps(_level_bar_labels)};
const LEVEL_BAR_E1     = {json.dumps(_level_bar_e1)};
const LEVEL_BAR_E2     = {json.dumps(_level_bar_e2)};
const LEVEL_BAR_E3     = {json.dumps(_level_bar_e3)};
const LEVEL_BAR_E4     = {json.dumps(_level_bar_e4)};

let retTrendChart  = null;
let retLevelsChart = null;

function renderFunnel(year) {{
  const d = COHORT_FUNNELS[year];
  if (!d) return;
  const max = d.e1 || 1;
  const levels = [
    {{ label: "Year 1 (New)", count: d.e1,   year: d.e1_year, partial: false }},
    {{ label: "Year 2",       count: d.e2,   year: d.e2_year, partial: d.e2_partial }},
    {{ label: "Year 3",       count: d.e3,   year: d.e3_year, partial: d.e3_partial }},
    {{ label: "Year 4",       count: d.e4,   year: d.e4_year, partial: d.e4_partial }},
  ];
  const colors = ["#0072b2","#009e73","#e69f00","#cc79a7"];
  let html = "";
  levels.forEach((lv, i) => {{
    if (lv.count == null) return;
    const pct = Math.round(lv.count / max * 100);
    const partialBadge = lv.partial ? ' <span style="font-size:0.68rem;color:#94a3b8;">(in progress)</span>' : "";
    html += `
      <div style="margin-bottom:4px;">
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px;">
          <div style="width:110px;font-size:0.78rem;font-weight:600;color:#475569;flex-shrink:0;">${{lv.label}}</div>
          <div style="flex:1;background:#f1f5f9;border-radius:6px;height:32px;overflow:hidden;">
            <div style="width:${{pct}}%;height:100%;background:${{colors[i]}};border-radius:6px;display:flex;align-items:center;padding-left:10px;box-sizing:border-box;transition:width 0.5s ease;">
              <span style="color:white;font-weight:700;font-size:0.82rem;white-space:nowrap;">${{lv.count.toLocaleString()}}${{partialBadge}}</span>
            </div>
          </div>
          <div style="width:46px;text-align:right;font-size:0.78rem;color:#64748b;flex-shrink:0;">${{pct}}%</div>
        </div>`;
    if (i < levels.length - 1 && levels[i+1].count != null) {{
      const dropped = lv.count - levels[i+1].count;
      const dropPct = (dropped / lv.count * 100).toFixed(1);
      const dropColor = dropped / lv.count > 0.2 ? "#ef4444" : dropped / lv.count > 0.1 ? "#f97316" : "#94a3b8";
      html += `
        <div style="display:flex;align-items:center;gap:10px;margin:2px 0 6px;">
          <div style="width:110px;"></div>
          <div style="font-size:0.72rem;color:${{dropColor}};font-weight:600;padding-left:4px;">
            ↓ ${{dropped > 0 ? dropped.toLocaleString() + " did not return (" + dropPct + "%)" : "All returned"}}
          </div>
        </div>`;
    }}
    html += `</div>`;
  }});
  document.getElementById("cohortFunnelDisplay").innerHTML = html;
}}

window.selectCohortYear = function(btn) {{
  document.querySelectorAll(".cohort-yr-pill").forEach(p => {{
    p.style.background = "#f8fafc"; p.style.color = "#475569"; p.style.borderColor = "#e2e8f0";
  }});
  btn.style.background = "#1e3a5f"; btn.style.color = "white"; btn.style.borderColor = "#1e3a5f";
  renderFunnel(btn.dataset.year);
}};

function buildTrendChart() {{
  if (retTrendChart) return;
  const ctx = document.getElementById("retTrendChart").getContext("2d");
  retTrendChart = new Chart(ctx, {{
    type: "line",
    data: {{
      labels: RET_TREND_LABELS,
      datasets: [
        {{ label: "Yr 1 → Yr 2", data: RET_TREND_E1E2, borderColor: "#0072b2", backgroundColor: "#0072b218",
           borderWidth: 2.5, pointRadius: 5, pointHoverRadius: 7, tension: 0.3, fill: false, spanGaps: false }},
        {{ label: "Yr 2 → Yr 3", data: RET_TREND_E2E3, borderColor: "#e69f00", backgroundColor: "#e69f0018",
           borderWidth: 2.5, pointRadius: 5, pointHoverRadius: 7, tension: 0.3, fill: false, spanGaps: false }},
        {{ label: "Yr 3 → Yr 4", data: RET_TREND_E3E4, borderColor: "#009e73", backgroundColor: "#009e7318",
           borderWidth: 2.5, pointRadius: 5, pointHoverRadius: 7, tension: 0.3, fill: false, spanGaps: false }},
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{
        legend: {{ display: true, position: "top" }},
        tooltip: {{
          callbacks: {{
            label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y !== null ? ctx.parsed.y + "%" : "partial"}}`
          }}
        }}
      }},
      scales: {{
        y: {{ min: 60, max: 100, ticks: {{ callback: v => v + "%" }}, grid: {{ color: "#f1f5f9" }} }},
        x: {{ grid: {{ color: "#f8fafc" }} }}
      }}
    }}
  }});
}}

function buildLevelsChart() {{
  if (retLevelsChart) return;
  const ctx = document.getElementById("retLevelsChart").getContext("2d");
  retLevelsChart = new Chart(ctx, {{
    type: "bar",
    data: {{
      labels: LEVEL_BAR_LABELS,
      datasets: [
        {{ label: "Year 1 (New)", data: LEVEL_BAR_E1, backgroundColor: "#0072b2" }},
        {{ label: "Year 2",       data: LEVEL_BAR_E2, backgroundColor: "#009e73" }},
        {{ label: "Year 3",       data: LEVEL_BAR_E3, backgroundColor: "#e69f00" }},
        {{ label: "Year 4",       data: LEVEL_BAR_E4, backgroundColor: "#cc79a7" }},
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{
        legend: {{ display: true, position: "top" }},
        tooltip: {{
          callbacks: {{
            label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.parsed.y.toLocaleString()}}`
          }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ color: "#f8fafc" }} }},
        y: {{ beginAtZero: true, ticks: {{ stepSize: 50 }}, grid: {{ color: "#f1f5f9" }} }}
      }}
    }}
  }});
}}

window.switchRetView = function(view) {{
  const views   = ["funnel", "trend", "levels"];
  const btnIds  = ["retViewFunnel", "retViewTrend", "retViewLevels"];
  const divIds  = ["retFunnelView",  "retTrendView",  "retLevelsView"];
  views.forEach((v, i) => {{
    const active = v === view;
    document.getElementById(divIds[i]).style.display      = active ? "" : "none";
    document.getElementById(btnIds[i]).style.background   = active ? "#1e3a5f" : "white";
    document.getElementById(btnIds[i]).style.color        = active ? "white"   : "#64748b";
    document.getElementById(btnIds[i]).style.borderColor  = active ? "#1e3a5f" : "#cbd5e1";
  }});
  if (view === "trend")  buildTrendChart();
  if (view === "levels") buildLevelsChart();
}};

// Init funnel with first cohort year
(function() {{
  const firstPill = document.querySelector(".cohort-yr-pill");
  if (firstPill) renderFunnel(firstPill.dataset.year);
}})();

// ── Hero year selector ──
(function() {{
  const pills = Array.from(document.querySelectorAll("#heroYearPills .hero-year-pill"));
  pills.forEach(pill => {{
    pill.addEventListener("click", () => {{
      pills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      updateHeroStats(parseInt(pill.dataset.idx));
    }});
  }});
  const activePill = pills.find(p => p.classList.contains("active"));
  if (activePill) updateHeroStats(parseInt(activePill.dataset.idx));
}})();

// ── Live refresh ──────────────────────────────────────────────────────────────
(function() {{
  const refreshBtn  = document.getElementById("liveRefreshBtn");
  const refreshTime = document.getElementById("liveRefreshTime");
  const refreshIcon = document.getElementById("liveRefreshIcon");
  let refreshing = false;

  window.liveRefresh = async function() {{
    if (refreshing) return;
    refreshing = true;
    refreshBtn.disabled = true;
    refreshIcon.style.animation = "fa-spin 0.8s linear infinite";

    let appCount, newCount, abcCount, partnerCount, retCount, failed;
    try {{
      const res  = await fetch(PROXY_URL);
      const data = await res.json();
      appCount     = data.app;
      newCount     = data.new_reg;
      abcCount     = data.abc_reg;
      partnerCount = data.partner;
      retCount     = data.returning;
      failed = [appCount, newCount, abcCount, partnerCount, retCount].some(v => v == null);
    }} catch (e) {{
      failed = true;
    }}

    if (!failed) {{
      APP_TOTALS[ACTIVE_IDX] = appCount;
      NEW_REG[ACTIVE_IDX]    = newCount + abcCount + partnerCount;
      RET_REG[ACTIVE_IDX]    = retCount;

      const activePill = document.querySelector("#heroYearPills .hero-year-pill.active");
      if (activePill && parseInt(activePill.dataset.idx) === ACTIVE_IDX) {{
        updateHeroStats(ACTIVE_IDX);
      }}
      refreshTime.textContent = "Updated " + new Date().toLocaleTimeString([], {{hour: "2-digit", minute: "2-digit"}});
      refreshTime.style.color = "#22c55e";
    }} else {{
      refreshTime.textContent = "Refresh failed — check connection";
      refreshTime.style.color = "#ef4444";
    }}

    refreshIcon.style.animation = "";
    refreshBtn.disabled = false;
    refreshing = false;
  }};

  // Auto-refresh every 5 minutes
  setInterval(window.liveRefresh, 5 * 60 * 1000);
  // Initial fetch on load
  window.liveRefresh();
}})();

// ══════════════════════════════════════════════════════════════════════════════
// ── Student Intelligence Charts ──────────────────────────────────────────────
// ══════════════════════════════════════════════════════════════════════════════

(function() {{
  // ── Conversion Rate Chart ──
  const CONV_DATA = {_conv_json};
  const fallConv   = CONV_DATA.filter(d => d.season === "Fall");
  const winterConv = CONV_DATA.filter(d => d.season === "Winter");
  // All unique labels in order
  const convLabels = CONV_DATA.map(d => d.label);

  // Build datasets aligned to all labels
  function convSeries(subset, color) {{
    return convLabels.map(lbl => {{
      const hit = subset.find(d => d.label === lbl);
      return hit ? hit.pct : null;
    }});
  }}

  new Chart(document.getElementById("conversionChart"), {{
    type: "bar",
    data: {{
      labels: convLabels,
      datasets: [
        {{
          label: "Fall Conversion %",
          data: convSeries(fallConv, "#0072b2"),
          backgroundColor: convLabels.map(l => l.startsWith("Fall") ? "#0072b2" : "transparent"),
          borderColor:     convLabels.map(l => l.startsWith("Fall") ? "#0072b2" : "transparent"),
          borderRadius: 5, borderSkipped: false,
        }},
        {{
          label: "Winter Conversion %",
          data: convSeries(winterConv, "#cc79a7"),
          backgroundColor: convLabels.map(l => l.startsWith("Winter") ? "#cc79a7" : "transparent"),
          borderColor:     convLabels.map(l => l.startsWith("Winter") ? "#cc79a7" : "transparent"),
          borderRadius: 5, borderSkipped: false,
        }}
      ]
    }},
    options: {{
      responsive: true,
      interaction: {{ mode: "index", intersect: false }},
      plugins: {{
        legend: {{ display: true, position: "top" }},
        tooltip: {{
          callbacks: {{
            label: ctx => {{
              const d = CONV_DATA.find(x => x.label === ctx.label);
              if (!d) return "";
              return ` ${{ctx.dataset.label.replace(" Conversion %","")}}: ${{d.pct}}%  (${{d.matched.toLocaleString()}} matched / ${{d.apps.toLocaleString()}} apps)`;
            }}
          }}
        }}
      }},
      scales: {{
        x: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{
          beginAtZero: true, max: 100,
          grid: {{ color: "#f1f5f9" }},
          ticks: {{ callback: v => v + "%", font: {{ size: 11 }} }}
        }}
      }}
    }}
  }});

  // ── Marketing Attribution Chart ──
  const MKT_DATA = {_mkt_totals_json};
  const mktLabels = MKT_DATA.map(d => d.source);
  const mktCounts = MKT_DATA.map(d => d.count);
  const mktMax    = Math.max(...mktCounts, 1);
  const mktColors = [
    "#0072b2","#e69f00","#009e73","#56b4e9","#cc79a7","#d55e00","#f0e442","#999999"
  ];

  new Chart(document.getElementById("mktAttrChart"), {{
    type: "bar",
    data: {{
      labels: mktLabels,
      datasets: [{{
        label: "Responses",
        data: mktCounts,
        backgroundColor: mktColors.slice(0, mktLabels.length),
        borderRadius: 5, borderSkipped: false,
      }}]
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw.toLocaleString()}} responses` }} }}
      }},
      scales: {{
        x: {{ beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 12 }} }} }}
      }}
    }}
  }});

  // ── Social Survey — Platform Chart ──
  const SV_PLATFORM = {_sv_platform_json};
  new Chart(document.getElementById("svPlatformChart"), {{
    type: "bar",
    data: {{
      labels: SV_PLATFORM.map(d => d.label),
      datasets: [{{
        label: "Students",
        data: SV_PLATFORM.map(d => d.count),
        backgroundColor: ["#e1306c","#ff0000","#000000","#fffc00","#1877f2","#1da1f2","#ff4500"],
        borderRadius: 4, borderSkipped: false,
      }}]
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw}} students` }} }}
      }},
      scales: {{
        x: {{ beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 12 }} }} }}
      }}
    }}
  }});

  // ── Social Survey — What Drives Action ──
  const SV_ACTION = {_sv_action_json};
  new Chart(document.getElementById("svActionChart"), {{
    type: "bar",
    data: {{
      labels: SV_ACTION.map(d => d.label),
      datasets: [{{
        label: "Students",
        data: SV_ACTION.map(d => d.count),
        backgroundColor: ["#0072b2","#e69f00","#009e73","#cc79a7","#d55e00"],
        borderRadius: 4, borderSkipped: false,
      }}]
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw}} students` }} }}
      }},
      scales: {{
        x: {{ beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 12 }}, maxTicksLimit: 8 }} }}
      }}
    }}
  }});

  // ── Demographics — Race Stacked Bar ──
  const DEMO_RACE    = {_demo_race_json};
  const DEMO_LABELS  = {_demo_labels_json};
  const DEMO_COLORS  = {_demo_race_colors_json};
  const DEMO_RACE_ORDER = {_demo_race_order_json};

  const demoRaceDatasets = DEMO_RACE_ORDER.map(race => ({{
    label: race,
    data: DEMO_LABELS.map(y => DEMO_RACE[y] ? (DEMO_RACE[y][race] || 0) : 0),
    backgroundColor: DEMO_COLORS[race] || "#aaa",
    borderRadius: 2, borderSkipped: false, stack: "race",
  }})).filter(ds => ds.data.some(v => v > 0));

  new Chart(document.getElementById("demoRaceChart"), {{
    type: "bar",
    data: {{ labels: DEMO_LABELS, datasets: demoRaceDatasets }},
    options: {{
      responsive: true,
      plugins: {{
        legend: {{ display: true, position: "bottom", labels: {{ boxWidth: 10, padding: 10, font: {{ size: 11 }} }} }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.dataset.label}}: ${{ctx.raw.toLocaleString()}}` }} }}
      }},
      scales: {{
        x: {{ stacked: true, grid: {{ display: false }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ stacked: true, beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }}
      }}
    }}
  }});

  // ── Demographics — Education Horizontal Bar ──
  const DEMO_EDU = {_demo_edu_json};
  const EDU_COLORS_MAP = {_demo_edu_colors_json};

  new Chart(document.getElementById("demoEduChart"), {{
    type: "bar",
    data: {{
      labels: DEMO_EDU.map(d => d.label),
      datasets: [{{
        label: "Applicants",
        data: DEMO_EDU.map(d => d.count),
        backgroundColor: DEMO_EDU.map(d => EDU_COLORS_MAP[d.label] || "#aaa"),
        borderRadius: 5, borderSkipped: false,
      }}]
    }},
    options: {{
      indexAxis: "y",
      responsive: true,
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{ctx.raw.toLocaleString()}} applicants` }} }}
      }},
      scales: {{
        x: {{ beginAtZero: true, grid: {{ color: "#f1f5f9" }}, ticks: {{ font: {{ size: 11 }} }} }},
        y: {{ grid: {{ display: false }}, ticks: {{ font: {{ size: 13 }} }} }}
      }}
    }}
  }});
}})();
</script>
</body>
</html>"""

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    f.write(html)

print(f"\nDashboard written to: {OUTPUT_PATH}")

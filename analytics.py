"""KPI calculations and analytical helpers (pure pandas/numpy, no Streamlit).

Definitions (all counts are ticket counts, NOT passenger counts):
  interval_total(t)      = count recorded for the 15-minute interval starting at t
  hourly_total(h)        = SUM of interval counts in hour h  (never an average)
  daily_total(d)         = SUM of interval counts on date d
  peak hour              = clock hour with the highest MEAN hourly total across days that had any
                           activity in that hour (mean of sums, see hourly_profile)
  off-peak hour          = clock hour with the lowest mean hourly total among regular-operation hours
                           (hours with recorded activity on at least MIN_ACTIVE_DAYS_SHARE = 90% of days);
                           overnight hours with sporadic activity are excluded from this ranking
  Seasonal Utilization Index (SUI) = 100 * mean daily total in group / mean daily total over all days
                           in the selection (baseline = selection-wide mean daily total = 100)
  Off-season / peak-season ratio    = mean daily total in the lowest season / mean daily total in the
                           highest season (seasons found from the data, not preset)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

import config as cfg

MIN_ACTIVE_DAYS_SHARE = 0.9   # 'regular-operation' hour: activity recorded on >=90% of days (used to rank off-peak)


# ----------------------------------------------------------------------------
# Filtering
# ----------------------------------------------------------------------------
@dataclass
class Filters:
    start_date: pd.Timestamp | None = None     # inclusive
    end_date: pd.Timestamp | None = None       # inclusive
    hour_range: tuple[int, int] = (0, 23)      # inclusive hours
    days_of_week: Iterable[int] | None = None  # Monday=0
    months: Iterable[int] | None = None
    years: Iterable[int] | None = None
    day_type: str = "All"                      # All / Weekday / Weekend
    exclude_outliers: bool = False


def apply_filters(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Return the subset of rows matching every filter. Boundaries are inclusive."""
    if df.empty:
        return df.copy()
    m = pd.Series(True, index=df.index)
    if f.start_date is not None:
        m &= df["date"] >= pd.Timestamp(f.start_date).normalize()
    if f.end_date is not None:
        m &= df["date"] <= pd.Timestamp(f.end_date).normalize()
    lo, hi = f.hour_range
    m &= df["hour"].between(lo, hi)
    if f.days_of_week is not None:
        m &= df["day_of_week"].isin(list(f.days_of_week))
    if f.months is not None:
        m &= df["month"].isin(list(f.months))
    if f.years is not None:
        m &= df["year"].isin(list(f.years))
    if f.day_type == "Weekday":
        m &= ~df["is_weekend"]
    elif f.day_type == "Weekend":
        m &= df["is_weekend"]
    if f.exclude_outliers:
        m &= ~df["is_outlier"]
    return df.loc[m].copy()


def measures(df: pd.DataFrame) -> list[str]:
    """Activity measures actually present in the data."""
    return [c for c in (cfg.COL_REDEEM, cfg.COL_SALES) if c in df.columns]


# ----------------------------------------------------------------------------
# Aggregation (always sums)
# ----------------------------------------------------------------------------
def aggregate(df: pd.DataFrame, level: str) -> pd.DataFrame:
    """Sum counts by 'interval', 'hour', 'day', 'month' or 'year'. Empty input gives an empty frame."""
    keys = {"interval": "interval_start", "hour": "hour_start", "day": "date", "month": "year_month", "year": "year"}
    if level not in keys:
        raise ValueError(f"Unknown aggregation level: {level}")
    cols = measures(df) if not df.empty else [cfg.COL_REDEEM]
    if df.empty:
        return pd.DataFrame(columns=[keys[level]] + cols)
    out = df.groupby(keys[level], as_index=False)[cols].sum()
    return out.sort_values(keys[level]).reset_index(drop=True)


def hourly_profile(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Per clock hour: mean and median of the hourly totals, over days with activity in that hour."""
    if df.empty:
        return pd.DataFrame(columns=["hour", "mean_hourly_total", "median_hourly_total", "active_days", "share_of_days_active"])
    hourly = df.groupby(["date", "hour"], as_index=False)[measure].sum()
    n_days = df["date"].nunique()
    g = hourly.groupby("hour")[measure].agg(["mean", "median", "count"]).reindex(range(24))
    return pd.DataFrame({
        "hour": g.index,
        "mean_hourly_total": g["mean"].values,
        "median_hourly_total": g["median"].values,
        "active_days": g["count"].fillna(0).astype(int).values,
        "share_of_days_active": (g["count"].fillna(0) / max(n_days, 1)).values,
    })


def interval_profile(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Mean count per 15-minute slot of the day. Absent intervals count as zero activity
    ONLY if `zero_fill` semantics are accepted; here we report the mean over observed intervals
    and the observation share so both readings are visible."""
    if df.empty:
        return pd.DataFrame(columns=["interval_of_day", "time_label", "mean_observed", "observed_share"])
    n_days = df["date"].nunique()
    g = df.groupby(["interval_of_day", "time_label"])[measure].agg(["mean", "count"]).reset_index()
    g["observed_share"] = g["count"] / max(n_days, 1)
    return g.rename(columns={"mean": "mean_observed"}).drop(columns="count")


def day_of_week_profile(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Mean daily total by weekday (days with data only)."""
    if df.empty:
        return pd.DataFrame(columns=["day_of_week", "day_name", "mean_daily_total", "days"])
    daily = df.groupby(["date", "day_of_week", "day_name"], as_index=False)[measure].sum()
    g = daily.groupby(["day_of_week", "day_name"])[measure].agg(["mean", "count"]).reset_index()
    return g.rename(columns={"mean": "mean_daily_total", "count": "days"}).sort_values("day_of_week").reset_index(drop=True)


def monthly_profile(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Mean daily total by calendar month (across years) plus total tickets."""
    if df.empty:
        return pd.DataFrame(columns=["month", "month_name", "mean_daily_total", "total", "days"])
    daily = df.groupby(["date", "month", "month_name"], as_index=False)[measure].sum()
    g = daily.groupby(["month", "month_name"])[measure].agg(["mean", "sum", "count"]).reset_index()
    return g.rename(columns={"mean": "mean_daily_total", "sum": "total", "count": "days"}).sort_values("month").reset_index(drop=True)


def seasonal_index(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Seasonal Utilization Index: 100 * season mean daily total / overall mean daily total."""
    if df.empty:
        return pd.DataFrame(columns=["season", "mean_daily_total", "days", "index"])
    daily = df.groupby(["date", "season"], as_index=False)[measure].sum()
    base = daily[measure].mean()
    g = daily.groupby("season")[measure].agg(["mean", "count"]).reset_index().rename(columns={"mean": "mean_daily_total", "count": "days"})
    g["index"] = 100 * g["mean_daily_total"] / base if base else np.nan
    g["season"] = pd.Categorical(g["season"], cfg.SEASON_ORDER, ordered=True)
    return g.sort_values("season").reset_index(drop=True)


def weekday_weekend(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["day_type", "mean_daily_total", "days", "total"])
    daily = df.groupby(["date", "day_type"], as_index=False)[measure].sum()
    g = daily.groupby("day_type")[measure].agg(["mean", "count", "sum"]).reset_index()
    return g.rename(columns={"mean": "mean_daily_total", "count": "days", "sum": "total"})


def year_month_matrix(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Total tickets per (year x month) plus days of data, for year-over-year comparison."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(["year", "month"]).agg(total=(measure, "sum"), days=("date", "nunique")).reset_index()
    return g


def yoy_table(df: pd.DataFrame, measure: str) -> pd.DataFrame:
    """Year-over-year change of mean DAILY totals per month, only where both months have >=25 days
    of data (so partial months are not compared with full ones)."""
    if df.empty:
        return pd.DataFrame(columns=["month", "year", "mean_daily_total", "prev_year_mean_daily_total", "yoy_pct", "days"])
    daily = df.groupby(["year", "month", "date"], as_index=False)[measure].sum()
    g = daily.groupby(["year", "month"])[measure].agg(["mean", "count"]).reset_index()
    g.columns = ["year", "month", "mean_daily_total", "days"]
    prev = g.copy()
    prev["year"] += 1
    m = g.merge(prev, on=["year", "month"], suffixes=("", "_prev"))
    m = m[(m["days"] >= 25) & (m["days_prev"] >= 25)]
    m["yoy_pct"] = 100 * (m["mean_daily_total"] / m["mean_daily_total_prev"] - 1)
    m = m.rename(columns={"mean_daily_total_prev": "prev_year_mean_daily_total"})
    return m[["year", "month", "mean_daily_total", "prev_year_mean_daily_total", "yoy_pct", "days"]].reset_index(drop=True)


def annual_summary(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    cols = measures(df)
    g = df.groupby("year").agg(days_with_data=("date", "nunique"), first_date=("date", "min"), last_date=("date", "max"),
                               **{c: (c, "sum") for c in cols}).reset_index()
    g["full_calendar_year"] = (g["first_date"].dt.strftime("%m-%d") == "01-01") & (g["last_date"].dt.strftime("%m-%d") == "12-31")
    return g


# ----------------------------------------------------------------------------
# Rolling averages
# ----------------------------------------------------------------------------
def rolling_demand(grid: pd.DataFrame, measure: str, windows: dict[str, int] | None = None) -> pd.DataFrame:
    """Trailing rolling MEAN of interval counts on a regular 15-minute grid.

    Window sizes are in intervals (1-hour = 4, 4-hour = 16). A window needs its full length
    (min_periods = window) so edges are NaN rather than misleading partial averages. Requires the
    grid from data_processing.build_regular_grid.
    """
    windows = windows or cfg.ROLLING_WINDOWS
    out = grid[["interval_start", measure]].copy()
    for label, n in windows.items():
        out[f"rolling_{label}"] = out[measure].rolling(n, min_periods=n).mean()
    return out


# ----------------------------------------------------------------------------
# Sales vs redemption
# ----------------------------------------------------------------------------
def sales_vs_redemption(df: pd.DataFrame) -> dict | None:
    """Comparison of the two ticket measures. Returns None when sales data is unavailable.

    'difference' = sales - redemptions in ticket counts. It is NOT passenger movement: tickets can be
    bought in advance, redeemed on a different day, or bought and never redeemed.
    """
    if cfg.COL_SALES not in df.columns or df.empty:
        return None
    s, r = df[cfg.COL_SALES].sum(), df[cfg.COL_REDEEM].sum()
    daily = df.groupby("date")[[cfg.COL_SALES, cfg.COL_REDEEM]].sum()
    corr_i = df[[cfg.COL_SALES, cfg.COL_REDEEM]].corr().iloc[0, 1] if len(df) > 2 else np.nan
    corr_d = daily.corr().iloc[0, 1] if len(daily) > 2 else np.nan
    return {
        "total_sales": int(s), "total_redemptions": int(r), "difference": int(s - r),
        "sales_to_redemption_ratio": float(s / r) if r else np.nan,
        "interval_correlation": float(corr_i), "daily_correlation": float(corr_d),
        "days_sales_gt_redemptions": int((daily[cfg.COL_SALES] > daily[cfg.COL_REDEEM]).sum()),
        "days": int(len(daily)),
    }


def daily_difference(df: pd.DataFrame) -> pd.DataFrame:
    if cfg.COL_SALES not in df.columns or df.empty:
        return pd.DataFrame(columns=["date", "sales_minus_redemptions"])
    d = df.groupby("date")[[cfg.COL_SALES, cfg.COL_REDEEM]].sum()
    d["sales_minus_redemptions"] = d[cfg.COL_SALES] - d[cfg.COL_REDEEM]
    return d.reset_index()


# ----------------------------------------------------------------------------
# KPI bundle
# ----------------------------------------------------------------------------
def compute_kpis(df: pd.DataFrame, measure: str = cfg.COL_REDEEM) -> dict:
    """All headline KPIs for a (filtered) frame. Never raises on empty input."""
    if df.empty or measure not in df.columns:
        return {"empty": True}
    k: dict = {"empty": False, "measure": measure}
    k["total"] = int(df[measure].sum())
    k["rows"] = int(len(df))
    k["days"] = int(df["date"].nunique())
    k["mean_per_observed_interval"] = float(df[measure].mean())
    hourly = df.groupby("hour_start")[measure].sum()
    k["mean_per_observed_hour"] = float(hourly.mean())
    daily = df.groupby("date")[measure].sum()
    k["mean_daily_total"] = float(daily.mean())
    k["max_daily_total"] = int(daily.max())
    k["max_daily_date"] = daily.idxmax()
    mon = df.groupby("year_month")[measure].sum()
    k["max_month_total"] = int(mon.max())
    k["max_month"] = mon.idxmax()
    k["peak_interval_value"] = int(df[measure].max())
    k["peak_interval_time"] = df.loc[df[measure].idxmax(), cfg.COL_TS]

    prof = hourly_profile(df, measure).dropna(subset=["mean_hourly_total"])
    if not prof.empty:
        peak = prof.loc[prof["mean_hourly_total"].idxmax()]
        k["peak_hour"] = int(peak["hour"])
        k["peak_hour_mean_total"] = float(peak["mean_hourly_total"])
        ranked = prof[prof["share_of_days_active"] >= MIN_ACTIVE_DAYS_SHARE]
        if not ranked.empty:
            off = ranked.loc[ranked["mean_hourly_total"].idxmin()]
            k["offpeak_hour"] = int(off["hour"])
            k["offpeak_hour_mean_total"] = float(off["mean_hourly_total"])
    ww = weekday_weekend(df, measure)
    k["weekday_mean_daily"] = _pick(ww, "Weekday")
    k["weekend_mean_daily"] = _pick(ww, "Weekend")
    if k["weekday_mean_daily"] and k["weekend_mean_daily"]:
        k["weekend_vs_weekday_ratio"] = k["weekend_mean_daily"] / k["weekday_mean_daily"]
    si = seasonal_index(df, measure)
    if not si.empty:
        k["seasonal_index"] = {str(r.season): float(r["index"]) for _, r in si.iterrows()}
        hi, lo = si.loc[si["mean_daily_total"].idxmax()], si.loc[si["mean_daily_total"].idxmin()]
        k["peak_season"], k["low_season"] = str(hi["season"]), str(lo["season"])
        if hi["mean_daily_total"]:
            k["low_to_peak_season_ratio"] = float(lo["mean_daily_total"] / hi["mean_daily_total"])
    return k


def _pick(ww: pd.DataFrame, label: str):
    r = ww.loc[ww["day_type"] == label, "mean_daily_total"]
    return float(r.iloc[0]) if len(r) else None


def peak_days(df: pd.DataFrame, measure: str, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["date", measure])
    d = df.groupby("date", as_index=False)[measure].sum()
    return d.nlargest(n, measure).reset_index(drop=True)


def peak_intervals(df: pd.DataFrame, measure: str, n: int = 10) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    cols = [cfg.COL_TS] + measures(df) + ["outlier_score", "is_outlier"]
    return df.nlargest(n, measure)[cols].reset_index(drop=True)


def peak_window(df: pd.DataFrame, measure: str, width_hours: int = 3) -> dict | None:
    """Contiguous clock-hour window (hours of day) with the highest mean-hourly-total sum."""
    prof = hourly_profile(df, measure).set_index("hour")["mean_hourly_total"].fillna(0)
    if prof.sum() == 0:
        return None
    best = max(range(0, 24 - width_hours + 1), key=lambda s: prof.iloc[s:s + width_hours].sum())
    share = prof.iloc[best:best + width_hours].sum() / prof.sum()
    return {"start_hour": best, "end_hour": best + width_hours, "share_of_daily_total": float(share)}


# ----------------------------------------------------------------------------
# Insights (every statement is computed from the data passed in)
# ----------------------------------------------------------------------------
def generate_insights(df: pd.DataFrame, measure: str = cfg.COL_REDEEM) -> dict[str, list[str]]:
    """Returns {'findings': [...], 'recommendations': [...]}. Findings are computed facts;
    recommendations are hypotheses that need operational validation."""
    out: dict[str, list[str]] = {"findings": [], "recommendations": []}
    if df.empty:
        return out
    k = compute_kpis(df, measure)
    label = {cfg.COL_REDEEM: "ticket redemptions", cfg.COL_SALES: "ticket sales"}.get(measure, measure.lower())
    out["findings"].append(
        f"Selection contains {k['total']:,} {label} over {k['days']:,} days with data "
        f"(mean {k['mean_daily_total']:,.0f} per day)."
    )
    if "peak_hour" in k:
        h = k["peak_hour"]
        out["findings"].append(
            f"The busiest clock hour is {h:02d}:00-{h + 1:02d}:00, averaging {k['peak_hour_mean_total']:,.0f} {label} per hour on days it is active."
        )
    pw = peak_window(df, measure)
    if pw:
        out["findings"].append(
            f"The 3-hour window {pw['start_hour']:02d}:00-{pw['end_hour']:02d}:00 carries {pw['share_of_daily_total']:.0%} of the average daily total."
        )
    if "weekend_vs_weekday_ratio" in k:
        out["findings"].append(
            f"Weekend days average {k['weekend_vs_weekday_ratio']:.2f}x the {label} of weekdays "
            f"({k['weekend_mean_daily']:,.0f} vs {k['weekday_mean_daily']:,.0f} per day)."
        )
    if "peak_season" in k and k["peak_season"] != k["low_season"]:
        si = k["seasonal_index"]
        out["findings"].append(
            f"{k['peak_season']} is the highest season (index {si[k['peak_season']]:.0f}); {k['low_season']} the lowest "
            f"(index {si[k['low_season']]:.0f}); the low season runs at {k['low_to_peak_season_ratio']:.0%} of the peak season's daily level."
        )
    out["findings"].append(
        f"The single busiest day was {pd.Timestamp(k['max_daily_date']).date()} with {k['max_daily_total']:,}; "
        f"the largest 15-minute value was {k['peak_interval_value']:,} at {k['peak_interval_time']}."
    )
    n_out = int(df["is_outlier"].sum())
    if n_out:
        out["findings"].append(
            f"{n_out:,} intervals are statistical outliers versus their month-and-hour norm; they are retained and flagged, not removed."
        )
    if "peak_hour" in k:
        out["recommendations"].append(
            f"Hypothesis: align staffing and sailing capacity with the {pw['start_hour']:02d}:00-{pw['end_hour']:02d}:00 window "
            "(validate against vessel capacity and queue data, which are not in this dataset)." if pw else
            f"Hypothesis: review capacity around {k['peak_hour']:02d}:00."
        )
    if "weekend_vs_weekday_ratio" in k and k["weekend_vs_weekday_ratio"] > 1.2:
        out["recommendations"].append(
            "Hypothesis: weekend demand is materially higher; consider weekend-specific scheduling and crowd-management plans (requires operational validation)."
        )
    if "low_to_peak_season_ratio" in k and k["low_to_peak_season_ratio"] < 0.5:
        out["recommendations"].append(
            "Hypothesis: the low season is far below peak levels; a reduced off-season service pattern may be worth evaluating against cost and service obligations."
        )
    if n_out:
        out["recommendations"].append(
            "Review the flagged extreme intervals with operations staff (events, weather, system batching) before using them for capacity planning."
        )
    return out

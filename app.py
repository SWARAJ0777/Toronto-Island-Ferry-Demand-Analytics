"""Toronto Island ferry ticket analytics - Streamlit dashboard (historical data).

Run from this directory with:  streamlit run app.py
"""
from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

import analytics as an
import config as cfg
import data_processing as dp
import visualizations as viz

st.set_page_config(page_title="Toronto Island Ferry Analytics", page_icon="⛴️", layout="wide")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _stretch(func) -> dict:
    """Kwargs that make an element fill its container on any supported Streamlit version."""
    params = inspect.signature(func).parameters
    w = params.get("width")
    if w is not None and (w.default == "stretch" or "stretch" in str(w.annotation)):
        return {"width": "stretch"}                      # newer Streamlit: width accepts "stretch"
    # Older Streamlit: `width` is pixels-only; `use_container_width` is the equivalent switch.
    return {"use_container_width": True} if "use_container_width" in params else {}


def show_fig(fig, key: str | None = None) -> None:
    st.plotly_chart(fig, key=key, **_stretch(st.plotly_chart))


def show_df(df: pd.DataFrame, **kw) -> None:
    st.dataframe(df, hide_index=True, **_stretch(st.dataframe), **kw)


def csv_button(label: str, df: pd.DataFrame, filename: str, key: str) -> None:
    st.download_button(label, df.to_csv(index=False).encode("utf-8"), file_name=filename, mime="text/csv", key=key,
                       disabled=df.empty, help=None if not df.empty else "Nothing to export for the current selection")


def fmt_int(v) -> str:
    return "n/a" if v is None or (isinstance(v, float) and pd.isna(v)) else f"{v:,.0f}"


def hour_label(h) -> str:
    return "n/a" if h is None else f"{int(h):02d}:00-{int(h) + 1:02d}:00"


@st.cache_data(show_spinner="Loading and cleaning data...")
def load_from_path(path: str, mtime: float, size: int):
    """mtime and size are part of the cache key so an updated file is never served stale."""
    return dp.load_and_prepare(path)


@st.cache_data(show_spinner="Loading and cleaning uploaded data...")
def load_from_upload(name: str, content: bytes):
    import io
    return dp.load_and_prepare(io.BytesIO(content), filename=name)


# ---------------------------------------------------------------------------
# Sidebar: data source
# ---------------------------------------------------------------------------
st.sidebar.title("⛴️ Ferry Analytics")
st.sidebar.caption("Historical analytics from a CSV file. This is **not** a live feed.")

with st.sidebar.expander("Data source", expanded=False):
    path_text = st.text_input("CSV path", value=str(cfg.DEFAULT_DATA_PATH), help="Path to a CSV with Timestamp and Redemption Count columns.")
    upload = st.file_uploader("...or upload a CSV", type=["csv"], help="An uploaded file overrides the path above.")
    if st.button("Reload file from disk", help="Clears cached data and re-reads the CSV (use after replacing the file)."):
        st.cache_data.clear()
        st.rerun()

try:
    if upload is not None:
        df_all, report = load_from_upload(upload.name, upload.getvalue())
        source_desc = f"Uploaded: {upload.name}"
        file_mtime = None
    else:
        p = Path(path_text).expanduser()
        if not p.is_absolute():
            p = cfg.BASE_DIR / p
        stat = p.stat() if p.exists() else None
        df_all, report = load_from_path(str(p), stat.st_mtime if stat else 0.0, stat.st_size if stat else 0)
        source_desc = p.name
        file_mtime = datetime.fromtimestamp(stat.st_mtime) if stat else None
except dp.DataError as exc:
    st.error(f"**Could not load data.** {exc}")
    st.info("Put `Toronto Island Ferry Tickets.csv` in the `data/` folder, set the path in the sidebar, or upload a CSV.")
    st.stop()
except Exception as exc:  # unexpected - show readable message instead of a stack trace
    st.error(f"Unexpected error while loading data: {exc}")
    st.stop()

MEAS = an.measures(df_all)
HAS_SALES = cfg.COL_SALES in MEAS

# ---------------------------------------------------------------------------
# Sidebar: filters
# ---------------------------------------------------------------------------
st.sidebar.header("Filters")
dmin, dmax = df_all["date"].min().date(), df_all["date"].max().date()
rng = st.sidebar.date_input("Date range", value=(dmin, dmax), min_value=dmin, max_value=dmax,
                            help="Inclusive of both dates. Defaults to the full coverage of the file.")
if isinstance(rng, (list, tuple)):
    if len(rng) == 2:
        d0, d1 = rng
    elif len(rng) == 1:
        d0 = d1 = rng[0]
    else:
        d0, d1 = dmin, dmax
else:
    d0 = d1 = rng
hours = st.sidebar.slider("Time of day (hours, inclusive)", 0, 23, (0, 23), help="Keeps intervals whose start hour is within the range.")
dow_sel = st.sidebar.multiselect("Day of week", cfg.DAY_NAMES, default=cfg.DAY_NAMES)
day_type = st.sidebar.radio("Weekday / weekend", ["All", "Weekday", "Weekend"], horizontal=True)
years_all = sorted(df_all["year"].unique().tolist())
year_sel = st.sidebar.multiselect("Year", years_all, default=years_all)
month_sel = st.sidebar.multiselect("Month", cfg.MONTH_NAMES, default=cfg.MONTH_NAMES)
primary = st.sidebar.selectbox("Primary measure (KPIs and profiles)", MEAS, help="Charts that compare both measures show both when sales data exists.")
excl_out = st.sidebar.checkbox("Exclude flagged outliers", value=False, help="Outliers are flagged, never deleted from the source. This only hides them from the view.")

filters = an.Filters(
    start_date=pd.Timestamp(d0), end_date=pd.Timestamp(d1), hour_range=hours,
    days_of_week=[cfg.DAY_NAMES.index(d) for d in dow_sel],
    months=[cfg.MONTH_NAMES.index(m) + 1 for m in month_sel], years=year_sel,
    day_type=day_type, exclude_outliers=excl_out,
)
df = an.apply_filters(df_all, filters)

page = st.sidebar.radio("Page", ["Overview", "Demand analysis", "Rolling & sales vs redemption", "Data quality",
                                 "Data explorer", "Insights", "Definitions & limits"])
st.sidebar.caption(f"{len(df):,} of {len(df_all):,} intervals selected")

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.title("Toronto Island Ferry - Ticket Sales & Redemption Analytics")
st.caption(
    "Historical analytics of 15-minute ticket counts for Toronto Island Park ferry service. "
    "Counts are **tickets, not passengers**; ticket sales and redemptions are not arrivals or departures."
)

if df.empty:
    st.warning("No records match the current filters. Widen the date range or reset a filter in the sidebar.")
    if page not in ("Data quality", "Definitions & limits"):
        st.stop()

kp = an.compute_kpis(df, primary) if not df.empty else {"empty": True}
cov = dp.coverage_for(df)


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
def page_overview():
    c = st.columns(5)
    c[0].metric("From", f"{d0:%Y-%m-%d}")
    c[1].metric("To", f"{d1:%Y-%m-%d}")
    c[2].metric("Records in selection", f"{len(df):,}")
    latest = df_all[cfg.COL_TS].max()
    c[3].metric("Latest record in file", f"{latest:%Y-%m-%d}", help=f"Last timestamp: {latest}")
    age_days = (datetime.now() - latest.to_pydatetime()).days
    c[4].metric("Days since latest record", f"{age_days:,}", help="Compared with today's date; data is historical, not live.")
    st.caption(f"Source: {source_desc}" + (f" | file modified {file_mtime:%Y-%m-%d %H:%M}" if file_mtime else ""))

    st.subheader(f"Headline KPIs - {primary}")
    r1 = st.columns(4)
    r1[0].metric("Total tickets", fmt_int(kp["total"]))
    r1[1].metric("Mean daily total", fmt_int(kp["mean_daily_total"]), help="Mean of daily sums over days that have data.")
    r1[2].metric("Peak hour (avg)", hour_label(kp.get("peak_hour")), help="Clock hour with the highest mean hourly total.")
    r1[3].metric("Off-peak hour (avg)", hour_label(kp.get("offpeak_hour")),
                 help="Lowest mean hourly total among regular-operation hours (activity recorded on at least 90% of days). Overnight hours with sporadic activity are excluded.")
    r2 = st.columns(4)
    r2[0].metric("Per observed 15-min interval", f"{kp['mean_per_observed_interval']:,.1f}",
                 help="Mean over intervals present in the file. Absent intervals are not counted as zero here.")
    r2[1].metric("Per observed hour", f"{kp['mean_per_observed_hour']:,.1f}", help="Mean of hourly SUMS over hours present in the file.")
    r2[2].metric("Weekend / weekday (daily)", f"{kp['weekend_vs_weekday_ratio']:.2f}x" if "weekend_vs_weekday_ratio" in kp else "n/a")
    r2[3].metric("Busiest day", fmt_int(kp["max_daily_total"]), help=str(pd.Timestamp(kp["max_daily_date"]).date()))
    r3 = st.columns(4)
    r3[0].metric("Completeness (within day span)", f"{cov['completeness_within_day_span_pct']:.1f}%",
                 help="Observed intervals / intervals between each day's first and last record. Absent intervals most likely mean no ticket activity.")
    r3[1].metric("Absent intervals", f"{cov['absent_intervals_within_day_span']:,}")
    r3[2].metric("Outliers flagged", f"{int(df['is_outlier'].sum()):,}")
    r3[3].metric("Days with data", f"{cov['days_present']:,}")

    if HAS_SALES:
        sv = an.sales_vs_redemption(df)
        st.subheader("Sales vs redemptions")
        s = st.columns(4)
        s[0].metric("Tickets sold", fmt_int(sv["total_sales"]))
        s[1].metric("Tickets redeemed", fmt_int(sv["total_redemptions"]))
        s[2].metric("Sales / redemptions", f"{sv['sales_to_redemption_ratio']:.3f}")
        s[3].metric("Daily correlation", f"{sv['daily_correlation']:.3f}")
        st.caption("The sales-minus-redemptions gap is a ticket-count difference, not net passenger movement.")
    else:
        st.info("Sales Count is not present in this file, so sales KPIs are unavailable. Redemption analysis continues below.")

    st.subheader("KPI summary by measure")
    rows = []
    for m in MEAS:
        k = an.compute_kpis(df, m)
        rows.append({"Measure": m, "Total": k["total"], "Per observed 15-min": round(k["mean_per_observed_interval"], 2),
                     "Per observed hour": round(k["mean_per_observed_hour"], 2), "Mean daily": round(k["mean_daily_total"], 1),
                     "Peak hour": hour_label(k.get("peak_hour")), "Off-peak hour": hour_label(k.get("offpeak_hour")),
                     "Max daily": k["max_daily_total"]})
    show_df(pd.DataFrame(rows))

    daily = an.aggregate(df, "day")
    show_fig(viz.time_series(daily, "date", MEAS, "Daily totals"), key="ov_daily")
    c1, c2 = st.columns(2)
    with c1:
        prof = an.hourly_profile(df, primary)
        show_fig(viz.hourly_profile_fig(prof, primary, kp.get("peak_hour"), kp.get("offpeak_hour")), key="ov_hour")
    with c2:
        show_fig(viz.monthly_fig(an.monthly_profile(df, primary), primary), key="ov_month")


def page_demand():
    st.subheader("Time series")
    n_hours = df["hour_start"].nunique()
    levels = ["Daily", "Monthly"] + (["Hourly"] if n_hours <= 60000 else []) + (["15-minute"] if len(df) <= 20000 else [])
    level = st.radio("Aggregation (sums)", levels, horizontal=True,
                     help="Hourly/15-minute views are offered only when the selection is small enough to plot responsively.")
    key = {"Daily": ("day", "date"), "Monthly": ("month", "year_month"), "Hourly": ("hour", "hour_start"), "15-minute": ("interval", "interval_start")}[level]
    show_measures = st.multiselect("Measures", MEAS, default=MEAS)
    agg = an.aggregate(df, key[0])
    show_fig(viz.time_series(agg, key[1], show_measures, f"{level} ticket totals"), key="dm_ts")
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        show_fig(viz.hourly_profile_fig(an.hourly_profile(df, primary), primary, kp.get("peak_hour"), kp.get("offpeak_hour")), key="dm_hour")
        st.caption("Red = peak hour, green = off-peak hour (definitions on the Definitions page).")
    with c2:
        show_fig(viz.interval_profile_fig(an.interval_profile(df, primary), primary), key="dm_int")
    c1, c2 = st.columns(2)
    with c1:
        show_fig(viz.dow_fig(an.day_of_week_profile(df, primary), primary), key="dm_dow")
    with c2:
        show_fig(viz.weekday_weekend_fig(an.weekday_weekend(df, primary), primary), key="dm_ww")
    show_fig(viz.heatmap_fig(df, primary), key="dm_heat")
    c1, c2 = st.columns(2)
    with c1:
        show_fig(viz.monthly_fig(an.monthly_profile(df, primary), primary), key="dm_mon")
    with c2:
        si = an.seasonal_index(df, primary)
        show_fig(viz.season_fig(si), key="dm_season")
        st.caption("Seasons: Winter = Dec-Feb, Spring = Mar-May, Summer = Jun-Aug, Fall = Sep-Nov. Index = 100 x season mean daily total / selection mean daily total.")
    st.subheader("Peak window and year-over-year")
    pw = an.peak_window(df, primary)
    if pw:
        st.write(f"Highest-volume 3-hour window: **{pw['start_hour']:02d}:00-{pw['end_hour']:02d}:00** "
                 f"({pw['share_of_daily_total']:.0%} of the average daily total).")
    ann = an.annual_summary(df)
    show_fig(viz.annual_fig(ann, MEAS), key="dm_annual")
    show_fig(viz.yoy_fig(an.yoy_table(df, primary)), key="dm_yoy")
    st.caption("Year-over-year is shown only for months with at least 25 days of data in both years. Partial years are visible in the annual chart.")


def page_rolling_sales():
    st.subheader("Rolling-average demand")
    dates = sorted(df["date"].dt.date.unique())
    busiest = an.peak_days(df, primary, 1)["date"].iloc[0].date()      # default window centres on the busiest day
    default_idx = max(dates.index(busiest) - 3, 0)
    c1, c2, c3 = st.columns(3)
    start = c1.selectbox("Window start date", dates, index=default_idx,
                         help="Choose a start date within the filtered selection (default: three days before the busiest day).")
    ndays = c2.slider("Days to show", 1, 31, min(7, 31))
    zero_fill = c3.checkbox("Treat absent intervals as zero", value=True,
                            help="ASSUMPTION: the file omits intervals with no activity. Unchecking leaves gaps (NaN) and rolling means then need full windows of observed data.")
    end = pd.Timestamp(start) + pd.Timedelta(days=ndays) - pd.Timedelta(minutes=15)
    base = an.apply_filters(df_all, an.Filters(start_date=pd.Timestamp(start), end_date=pd.Timestamp(end).normalize(), exclude_outliers=excl_out))
    if base.empty:
        st.info("No data in that window.")
    else:
        grid = dp.build_regular_grid(base, start=pd.Timestamp(start), end=end, zero_fill_absent=zero_fill)
        roll = an.rolling_demand(grid, primary)
        show_fig(viz.rolling_fig(roll, primary), key="rl_roll")
        st.caption("Trailing mean of 15-minute interval counts: 1-hour = 4 intervals, 4-hour = 16 intervals; the first windows are blank until full. "
                   "This view applies only the date window (and the outlier toggle), not the time-of-day/weekday filters.")
        csv_button("Download rolling-average data (CSV)", roll, "rolling_average.csv", "dl_roll")

    st.divider()
    st.subheader("Sales vs redemptions")
    if not HAS_SALES:
        st.info("Sales Count is not present in this dataset; sales-versus-redemption analysis is unavailable.")
        return
    sv = an.sales_vs_redemption(df)
    cols = st.columns(4)
    cols[0].metric("Sales / redemptions", f"{sv['sales_to_redemption_ratio']:.3f}")
    cols[1].metric("Ticket-count difference", f"{sv['difference']:+,}")
    cols[2].metric("Interval correlation", f"{sv['interval_correlation']:.3f}")
    cols[3].metric("Days with sales > redemptions", f"{sv['days_sales_gt_redemptions']:,} / {sv['days']:,}")
    st.warning("Tickets can be bought ahead of use, redeemed on another day, or never redeemed, so the difference is **not** net passenger movement.")
    daily = an.aggregate(df, "day")
    show_fig(viz.sales_vs_redemption_fig(daily), key="sv_daily")
    c1, c2 = st.columns(2)
    with c1:
        show_fig(viz.sales_redemption_scatter(df), key="sv_scatter")
    with c2:
        show_fig(viz.difference_fig(an.daily_difference(df)), key="sv_diff")


def page_quality():
    r = report
    st.subheader("Whole-file data quality")
    st.caption("These figures describe the file as loaded (before sidebar filters).")
    c = st.columns(4)
    c[0].metric("Rows read", f"{r.rows_raw:,}")
    c[1].metric("Rows after cleaning", f"{r.rows_clean:,}")
    c[2].metric("Calendar days covered", f"{r.n_calendar_days:,}")
    c[3].metric("Days with no data", f"{len(r.missing_calendar_days):,}")
    c = st.columns(4)
    c[0].metric("Completeness (within day span)", f"{r.completeness_within_day_span_pct:.1f}%")
    c[1].metric("Completeness (all 96 slots/day)", f"{r.completeness_full_days_pct:.1f}%")
    c[2].metric("Absent intervals (within day span)", f"{r.absent_intervals_within_day_span:,}")
    c[3].metric("Outliers flagged", f"{r.outliers_flagged:,}")
    st.write(f"**Coverage:** {r.first_timestamp} to {r.last_timestamp}.  **Columns:** {', '.join(r.columns)}.")

    st.subheader("Cleaning effects")
    eff = pd.DataFrame([
        ("Unparseable timestamps dropped", r.unparseable_timestamps_dropped),
        ("Rows dropped for missing/non-numeric counts", sum(r.missing_values_dropped.values())),
        ("Negative counts dropped", r.negative_values_dropped),
        ("Non-integer counts dropped", r.non_integer_values_dropped),
        ("Exact duplicate rows dropped", r.exact_duplicate_rows_dropped),
        ("Repeated timestamps summed (non-identical rows)", r.duplicate_timestamps_aggregated),
        ("Duplicate _id values", r.duplicate_ids),
        ("Timestamps off the 15-minute grid", r.non_quarter_hour_timestamps),
        ("Rows with Redemption Count = 0", r.zero_redemption_rows),
        ("Rows with Sales Count = 0", r.zero_sales_rows),
        ("Rows with both counts = 0", r.rows_with_both_zero),
        ("File was not in chronological order (re-sorted)", "yes" if r.was_sorted_by_cleaning else "no"),
        ("DST-transition days present", r.dst_transition_days_in_data),
    ], columns=["Check", "Result"])
    eff["Result"] = eff["Result"].astype(str)
    show_df(eff)
    for n in r.notes:
        st.info(n)
    if r.missing_calendar_days:
        st.write("**Calendar days with no records:** " + ", ".join(r.missing_calendar_days))

    st.subheader("Selection coverage")
    c = st.columns(3)
    c[0].metric("Observed intervals", f"{cov['observed_intervals']:,}")
    c[1].metric("Absent within day span", f"{cov['absent_intervals_within_day_span']:,}")
    c[2].metric("Completeness", "n/a" if pd.isna(cov["completeness_within_day_span_pct"]) else f"{cov['completeness_within_day_span_pct']:.1f}%")

    show_fig(viz.absent_hour_fig(dp.absent_by_hour(df_all)), key="dq_absent")
    st.caption("Overnight and early-morning hours have activity on few days, which is why most 'absent' intervals fall there.")
    gaps = dp.gap_table(df_all)
    st.write(f"**Runs of absent intervals longer than 2 hours:** {len(gaps):,} (longest 10 shown)")
    show_df(gaps.sort_values("absent_intervals", ascending=False).head(10))
    csv_button("Download all gaps (CSV)", gaps, "absent_interval_gaps.csv", "dl_gaps")

    st.subheader("Outliers (flagged, retained)")
    if not df.empty:
        show_fig(viz.outlier_fig(df, primary), key="dq_out")
        o = df.loc[df["is_outlier"], [cfg.COL_TS] + MEAS + ["outlier_score"]].sort_values(primary, ascending=False)
        st.caption("Method: modified z-score of log(1+count) within each (month, hour) group, threshold "
                   f"{cfg.OUTLIER_MODZ_THRESHOLD}, minimum count {cfg.OUTLIER_MIN_COUNT}. Extreme values may be genuine peak demand.")
        show_df(o.head(50))
        csv_button("Download flagged outliers (CSV)", o, "flagged_outliers.csv", "dl_out")


def page_explorer():
    st.subheader("Filtered data explorer")
    st.caption("Reflects every sidebar filter.")
    cols_default = [cfg.COL_TS] + MEAS + ["day_name", "season", "is_outlier"]
    show_cols = st.multiselect("Columns", list(df.columns), default=cols_default)
    order = st.selectbox("Sort by", [cfg.COL_TS] + MEAS, index=0)
    asc = st.checkbox("Ascending", value=True)
    view = df[show_cols] if show_cols else df
    if order in view.columns:
        view = view.sort_values(order, ascending=asc)
    st.caption(f"Showing first {min(len(view), cfg.MAX_TABLE_ROWS):,} of {len(view):,} rows. Downloads contain all rows.")
    show_df(view.head(cfg.MAX_TABLE_ROWS))
    c = st.columns(4)
    with c[0]:
        csv_button("Filtered intervals (CSV)", df.drop(columns=["hour_start"]), "filtered_intervals.csv", "dl_filtered")
    with c[1]:
        csv_button("Hourly totals (CSV)", an.aggregate(df, "hour"), "hourly_totals.csv", "dl_hourly")
    with c[2]:
        csv_button("Daily totals (CSV)", an.aggregate(df, "day"), "daily_totals.csv", "dl_daily")
    with c[3]:
        csv_button("Monthly totals (CSV)", an.aggregate(df, "month"), "monthly_totals.csv", "dl_monthly")
    c = st.columns(3)
    with c[0]:
        csv_button("Hourly profile (CSV)", an.hourly_profile(df, primary), "hourly_profile.csv", "dl_hprof")
    with c[1]:
        csv_button("Seasonal index (CSV)", an.seasonal_index(df, primary), "seasonal_index.csv", "dl_season")
    with c[2]:
        csv_button("Peak days (CSV)", an.peak_days(df, primary, 50), "peak_days.csv", "dl_peakdays")


def page_insights():
    st.subheader(f"Insights - {primary}")
    ins = an.generate_insights(df, primary)
    st.markdown("#### Findings (computed from the selected data)")
    for f in ins["findings"]:
        st.markdown(f"- {f}")
    st.markdown("#### Recommendations (hypotheses requiring operational validation)")
    for rec in ins["recommendations"]:
        st.markdown(f"- {rec}")
    st.caption("Findings are calculated directly from the filtered data. Recommendations are hypotheses: this dataset has no vessel capacity, queue, weather or event information.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Ten busiest days**")
        show_df(an.peak_days(df, primary, 10))
    with c2:
        st.markdown("**Ten largest 15-minute intervals**")
        show_df(an.peak_intervals(df, primary, 10))


def page_definitions():
    st.subheader("Definitions, interpretation and limits")
    st.markdown(f"""
**What the data is.** Interval-level aggregates: one row per 15-minute interval that had ticket activity, with `Redemption Count`
and (in this file) `Sales Count`. It is a **historical** file, so this dashboard is historical analytics; it does not receive a live feed.
To refresh, replace the CSV and press *Reload file from disk* (the cache is keyed on the file's modified time and size).

**Absent intervals.** The file contains no rows where both counts are zero, so intervals with no activity appear to be omitted. They are
reported as *absent*, not *missing*, and are treated as zero only where explicitly labelled (the rolling-average option).

**KPI definitions** (counts are tickets):
- *Interval total* = count in a 15-minute interval. *Hourly total* = **sum** of its intervals. *Daily/monthly total* = sum.
- *Per observed interval/hour* = mean over rows/hours present in the file (absent intervals excluded).
- *Peak hour* = clock hour with the highest mean hourly total. *Off-peak hour* = lowest mean hourly total among regular-operation hours (activity recorded on at least 90% of days).
  Overnight hours with sporadic activity are excluded from that ranking; read the full hourly profile for context.
- *Weekend vs weekday* = ratio of mean daily totals. Weekend = Saturday and Sunday.
- *Seasonal Utilization Index* = 100 x (season mean daily total) / (mean daily total of the whole selection). Baseline = 100. Seasons are meteorological (Dec-Feb winter, Mar-May spring, Jun-Aug summer, Sep-Nov fall).
- *Low-to-peak season ratio* = mean daily total of the lowest season / that of the highest season.
- *Completeness* = observed intervals / intervals between each day's first and last record (a strict "all 96 slots" version is on the Data quality page).
- *Rolling average* = trailing mean of interval counts over 4 (1-hour) or 16 (4-hour) intervals on a regular 15-minute grid.
- *Outlier* = modified z-score above {cfg.OUTLIER_MODZ_THRESHOLD} on log(1+count) within (month, hour), with count at least {cfg.OUTLIER_MIN_COUNT}. Flagged, never removed.

**Time zone.** Timestamps are timezone-naive and are kept as local wall-clock time (never reinterpreted as UTC). The file has no rows in the non-existent
spring-forward hour and no repeated fall-back timestamps, consistent with local time. DST transition days are flagged (`dst_transition_day`).

**Limits.**
- Ticket sales and redemptions are not passenger arrivals or departures; their difference is not net passenger movement.
- No vessel capacity, queue, weather, event or route (Centre Island / Hanlan's Point / Ward's Island) information exists in the file, so no capacity or per-route conclusions are drawn.
- 2015 starts on 1 May and 2025 ends on 21 December; annual totals for those years are partial. 2020 and 2017 are far lower than other years; causes are not in the data.
""")


{"Overview": page_overview, "Demand analysis": page_demand, "Rolling & sales vs redemption": page_rolling_sales,
 "Data quality": page_quality, "Data explorer": page_explorer, "Insights": page_insights,
 "Definitions & limits": page_definitions}[page]()

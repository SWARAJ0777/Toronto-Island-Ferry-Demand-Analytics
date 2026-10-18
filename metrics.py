"""Computes every number and chart used in the written reports from the real dataset.

Nothing here is typed in by hand: the report text pulls values from the dictionary returned by
compute_all(), so the reports always match the analysis. Run via build_reports.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import analytics as an  # noqa: E402
import config as cfg  # noqa: E402
import data_processing as dp  # noqa: E402

R, S = cfg.COL_REDEEM, cfg.COL_SALES
FIG = ROOT / "reports" / "figures"

# Validated two-series palette (see dataviz check): blue = redemptions, orange = sales.
C_R, C_S, C_INK, C_MUTED, C_GRID, C_ACC = "#1f6fb4", "#d9730d", "#1f2933", "#6b7280", "#e5e7eb", "#c0392b"
REFERENCE_YEARS = [2016, 2018, 2019, 2022, 2023, 2024]     # full years outside the two anomalous years


def _style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans", "font.size": 9, "axes.edgecolor": C_GRID, "axes.labelcolor": C_MUTED,
        "xtick.color": C_MUTED, "ytick.color": C_MUTED, "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": C_GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "figure.dpi": 150, "savefig.bbox": "tight", "axes.titleweight": "bold", "axes.titlesize": 10.5,
        "axes.titlelocation": "left", "axes.titlecolor": C_INK,
    })


def _save(fig, name):
    FIG.mkdir(parents=True, exist_ok=True)
    p = FIG / name
    fig.savefig(p)
    plt.close(fig)
    return p


def compute_all() -> dict:
    _style()
    df, rep = dp.load_and_prepare(cfg.DEFAULT_DATA_PATH)
    m: dict = {"rep": rep, "figs": {}}
    m["file"] = Path(cfg.DEFAULT_DATA_PATH).name
    m["file_bytes"] = Path(cfg.DEFAULT_DATA_PATH).stat().st_size
    kr, ks = an.compute_kpis(df, R), an.compute_kpis(df, S)
    m["kr"], m["ks"] = kr, ks
    m["sv"] = an.sales_vs_redemption(df)

    # ---- profiles ---------------------------------------------------------------------------------
    hp_r, hp_s = an.hourly_profile(df, R), an.hourly_profile(df, S)
    m["hp_r"], m["hp_s"] = hp_r, hp_s
    m["dow"] = an.day_of_week_profile(df, R)
    m["mon"] = an.monthly_profile(df, R)
    m["season"] = an.seasonal_index(df, R)
    m["ww"] = an.weekday_weekend(df, R)
    m["ann"] = an.annual_summary(df)
    m["yoy"] = an.yoy_table(df, R)
    m["pw_all"] = an.peak_window(df, R)
    m["pw_summer"] = an.peak_window(df[df.season == "Summer"], R)
    m["pw_winter"] = an.peak_window(df[df.season == "Winter"], R)
    m["peak_days"] = an.peak_days(df, R, 10)
    m["peak_ints"] = an.peak_intervals(df, R, 10)
    ww_s = an.weekday_weekend(df[df.season == "Summer"], R).set_index("day_type")["mean_daily_total"]
    m["summer_weekend_ratio"] = float(ww_s["Weekend"] / ww_s["Weekday"])
    ww_w = an.weekday_weekend(df[df.season == "Winter"], R).set_index("day_type")["mean_daily_total"]
    m["winter_weekend_ratio"] = float(ww_w["Weekend"] / ww_w["Weekday"])

    # regular-operation hours (activity on >=90% of days) and overnight
    ok = hp_r[hp_r.share_of_days_active >= an.MIN_ACTIVE_DAYS_SHARE]
    m["regular_hours"] = (int(ok.hour.min()), int(ok.hour.max()))
    m["offpeak_r"] = (int(ok.loc[ok.mean_hourly_total.idxmin(), "hour"]), float(ok.mean_hourly_total.min()))
    ok_s = hp_s[hp_s.share_of_days_active >= an.MIN_ACTIVE_DAYS_SHARE]
    m["offpeak_s"] = (int(ok_s.loc[ok_s.mean_hourly_total.idxmin(), "hour"]), float(ok_s.mean_hourly_total.min()))
    night = df[df.hour <= 5]
    m["night_rows"] = len(night)
    m["night_r_zero_share"] = float((night[R] == 0).mean())
    m["night_s_zero_share"] = float((night[S] == 0).mean())
    m["night_share_sales"] = float(night[S].sum() / df[S].sum())
    m["night_share_red"] = float(night[R].sum() / df[R].sum())
    tot_day = df.groupby("date")[R].sum()
    m["hours_7_to_20_share"] = float(df[df.hour.between(7, 20)][R].sum() / df[R].sum())
    m["hours_10_to_16_share"] = float(df[df.hour.between(10, 15)][R].sum() / df[R].sum())      # 10:00-15:59
    m["pm_vs_am"] = float(df[df.hour >= 12][R].sum() / df[R].sum())

    # heatmap peak cell
    hh = df.groupby(["date", "day_of_week", "hour"], as_index=False)[R].sum()
    cell = hh.groupby(["day_of_week", "hour"])[R].mean()
    d_, h_ = cell.idxmax()
    m["peak_cell"] = (cfg.DAY_NAMES[d_], int(h_), float(cell.max()))
    m["heat"] = cell.unstack("hour").reindex(index=range(7), columns=range(24))

    # ---- Seasonal concentration -----------------------------------------------------------------
    mon_tot = df.groupby("month")[R].sum()
    m["jja_share"] = float(mon_tot.loc[[6, 7, 8]].sum() / mon_tot.sum())
    m["julaug_share"] = float(mon_tot.loc[[7, 8]].sum() / mon_tot.sum())
    m["djf_share"] = float(mon_tot.loc[[12, 1, 2]].sum() / mon_tot.sum())

    # ---- Anomalous years --------------------------------------------------------------------------
    ym = df.groupby(["year", "month"])[R].sum().unstack().reindex(columns=range(1, 13))
    ref = ym.loc[REFERENCE_YEARS].mean()
    m["ref_month_mean"] = ref
    for y, months in ((2017, [5, 6, 7]), (2020, [4, 5, 6, 7, 8, 9])):
        obs, exp = float(ym.loc[y, months].sum()), float(ref[months].sum())
        m[f"anom_{y}"] = {"months": months, "observed": obs, "reference": exp, "pct_below": 100 * (1 - obs / exp)}
    ann = m["ann"].set_index("year")
    ref_full = ann.loc[REFERENCE_YEARS, R].mean()
    m["ref_annual_mean"] = float(ref_full)
    m["ann_vs_ref"] = {int(y): float(100 * (ann.loc[y, R] / ref_full - 1)) for y in (2017, 2020, 2021, 2025)}
    ratios = (ann[S] / ann[R]).round(3)
    m["ratio_by_year"] = ratios.to_dict()
    m["ym"] = ym

    # ---- Rolling windows on a regular zero-filled grid (assumption: absent intervals = 0) ------------
    grid = dp.build_regular_grid(df, zero_fill_absent=True)
    roll = an.rolling_demand(grid, R)
    m["roll"] = {}
    for lab in cfg.ROLLING_WINDOWS:
        c = f"rolling_{lab}"
        i = roll[c].idxmax()
        m["roll"][lab] = {"value": float(roll.loc[i, c]), "end": roll.loc[i, "interval_start"]}

    # ---- Peak interval neighbourhood ----------------------------------------------------------------------
    t0 = df.loc[df[R].idxmax(), "interval_start"]
    nb = grid[(grid.interval_start >= t0 - pd.Timedelta(minutes=60)) & (grid.interval_start <= t0 + pd.Timedelta(minutes=60))]
    m["peak_neighbourhood"] = nb[["interval_start", R, S]].reset_index(drop=True)

    # ---- Quality extras ------------------------------------------------------------------------------------------
    m["gaps"] = dp.gap_table(df).sort_values("absent_intervals", ascending=False).head(8).reset_index(drop=True)
    m["n_gaps_2h"] = len(dp.gap_table(df))
    m["absent_hour"] = dp.absent_by_hour(df)
    _n = m["absent_hour"][m["absent_hour"].hour <= 5]["pct_days_with_activity"]
    m["night_activity_range"] = (float(_n.min()), float(_n.max()))
    out = df[df.is_outlier]
    m["out_by_year"] = out.groupby("year").size().to_dict()
    m["out_by_month"] = out.groupby("month").size().to_dict()
    m["out_top"] = out.nlargest(8, R)[[cfg.COL_TS, R, S, "outlier_score"]].reset_index(drop=True)
    m["out_share_of_total"] = float(out[R].sum() / df[R].sum())
    m["dst_days"] = rep.dst_transition_days_in_data
    sf = df[df.dst_transition_day & (df.month == 3)]
    m["dst_spring_rows_in_hour2"] = int((sf.hour == 2).sum())
    m["dst_spring_days"] = int(sf.date.nunique())
    fb = df[df.dst_transition_day & (df.month == 11)]
    m["dst_fall_days"] = int(fb.date.nunique())
    m["dst_fall_dup_ts"] = int(fb.Timestamp.duplicated().sum())
    m["id_order_note"] = bool(df["_id"].is_monotonic_decreasing) if "_id" in df else None

    m["df"] = df
    _figures(m, df)
    return m


# ---------------------------------------------------------------------------------------------------------------
def _figures(m: dict, df: pd.DataFrame) -> None:
    f = m["figs"]
    # 1 hourly profile
    fig, ax = plt.subplots(figsize=(7.2, 3.1))
    for prof, c, lab in ((m["hp_s"], C_S, "Sales"), (m["hp_r"], C_R, "Redemptions")):
        ax.plot(prof.hour, prof.mean_hourly_total, color=c, lw=2, marker="o", ms=3.5)
    pk = m["kr"]["peak_hour"]
    ax.annotate("Redemptions", (6.4, m["hp_r"].mean_hourly_total[6]), xytext=(1.0, 190), color=C_R, fontsize=8.5,
                arrowprops=dict(arrowstyle="-", color=C_R, lw=0.8))
    ax.annotate("Sales", (0, m["hp_s"].mean_hourly_total[0]), xytext=(0.2, 78), color=C_S, fontsize=8.5)
    ax.axvline(pk, color=C_MUTED, lw=0.8, ls=":")
    ax.text(pk - 0.3, 18, f"peak {pk:02d}:00", color=C_MUTED, fontsize=8, ha="right", va="bottom")
    ax.set_xticks(range(0, 24, 2)); ax.set_xlabel("Hour of day (start of hour)"); ax.set_ylabel("Mean tickets per hour")
    ax.set_title("Average hourly total by clock hour")
    f["hourly"] = _save(fig, "hourly.png")

    # 2 monthly
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    mon = m["mon"]
    ax.bar(mon.month_name, mon.mean_daily_total, color=C_R, width=0.68)
    for x, v in zip(mon.month_name, mon.mean_daily_total):
        ax.text(x, v + 120, f"{v:,.0f}", ha="center", fontsize=7.5, color=C_INK)
    ax.set_ylabel("Mean tickets per day"); ax.set_title("Mean daily redemptions by calendar month")
    ax.grid(axis="x", visible=False)
    f["monthly"] = _save(fig, "monthly.png")

    # 3 day of week
    fig, ax = plt.subplots(figsize=(7.2, 2.7))
    d = m["dow"]
    cols = [C_R if x >= 5 else "#9dbfdc" for x in d.day_of_week]
    ax.bar(d.day_name.str[:3], d.mean_daily_total, color=cols, width=0.62)
    for x, v in zip(d.day_name.str[:3], d.mean_daily_total):
        ax.text(x, v + 80, f"{v:,.0f}", ha="center", fontsize=8, color=C_INK)
    ax.set_ylabel("Mean tickets per day"); ax.set_title("Mean daily redemptions by day of week (weekend darker)")
    ax.grid(axis="x", visible=False)
    f["dow"] = _save(fig, "dow.png")

    # 4 heatmap
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    im = ax.imshow(m["heat"].values, aspect="auto", cmap="Blues")
    ax.set_yticks(range(7)); ax.set_yticklabels([x[:3] for x in cfg.DAY_NAMES]); ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)]); ax.set_xlabel("Hour of day"); ax.grid(False)
    cb = fig.colorbar(im, ax=ax, pad=0.015); cb.set_label("Mean redemptions per hour", color=C_MUTED)
    ax.set_title("Mean hourly redemptions: weekday x hour")
    f["heat"] = _save(fig, "heatmap.png")

    # 5 annual totals
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    a = m["ann"]
    x = np.arange(len(a)); w = 0.38
    part = ~a.full_calendar_year.values
    ax.bar(x - w / 2, a[R], w, color=C_R, label="Redemptions")
    ax.bar(x + w / 2, a[S], w, color=C_S, label="Sales")
    for xi in x[part]:
        ax.text(xi, 40000, "partial", rotation=90, ha="center", va="bottom", fontsize=7.5, color="white")
    ax.set_xticks(x); ax.set_xticklabels(a.year); ax.set_ylabel("Tickets per year")
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v/1e6:.1f}M"))
    ax.legend(frameon=False, ncol=2, loc="lower right", bbox_to_anchor=(1.0, 1.0), fontsize=8); ax.grid(axis="x", visible=False)
    ax.set_title("Annual ticket totals")
    f["annual"] = _save(fig, "annual.png")

    # 6 daily series + 28-day mean
    daily = df.groupby("date")[R].sum().asfreq("D")
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    ax.plot(daily.index, daily.values, color="#b8c4d6", lw=0.6)
    ax.plot(daily.index, daily.rolling(28, min_periods=14).mean(), color=C_R, lw=1.6)
    ax.set_ylabel("Redemptions per day"); ax.set_title("Daily redemptions with 28-day average")
    ax.annotate("28-day mean", (daily.index[180], 12000), color=C_R, fontsize=8.5)
    f["daily"] = _save(fig, "daily.png")

    # 7 seasonal index
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    si = m["season"]
    ax.bar(si.season.astype(str), si["index"], color=C_R, width=0.55)
    ax.axhline(100, color=C_MUTED, lw=1, ls="--"); ax.text(3.45, 104, "baseline = 100", ha="right", fontsize=8, color=C_MUTED)
    for x_, v in zip(si.season.astype(str), si["index"]):
        ax.text(x_, v + 4, f"{v:.0f}", ha="center", fontsize=8.5, color=C_INK)
    ax.set_ylabel("Index"); ax.set_title("Seasonal Utilization Index (redemptions)"); ax.grid(axis="x", visible=False)
    f["season"] = _save(fig, "season.png")

    # 8 sales/redemption ratio by year
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    yrs = list(m["ratio_by_year"]); vals = list(m["ratio_by_year"].values())
    ax.plot(yrs, vals, color=C_S, lw=2, marker="o", ms=4)
    ax.axhline(1, color=C_MUTED, lw=0.9, ls="--")
    for y_, v in zip(yrs, vals):
        ax.text(y_, v + 0.012, f"{v:.2f}", ha="center", fontsize=7.5, color=C_INK)
    ax.set_xticks(yrs); ax.set_ylabel("Sales / redemptions"); ax.set_ylim(0.93, 1.27)
    ax.set_title("Annual ratio of tickets sold to tickets redeemed")
    f["ratio"] = _save(fig, "ratio.png")

    # 9 share of days with any activity by hour
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    ah = m["absent_hour"]
    ax.bar(ah.hour, ah.pct_days_with_activity, color="#8794a6", width=0.7)
    ax.axhline(90, color=C_ACC, lw=0.9, ls="--"); ax.text(-0.4, 92, "90% line: regular-operation hours", ha="left", fontsize=7.5, color=C_ACC)
    ax.set_ylim(0, 108)
    ax.set_xticks(range(24)); ax.set_xlabel("Hour of day"); ax.set_ylabel("% of days with a record")
    ax.set_title("Share of days with any recorded activity, by hour"); ax.grid(axis="x", visible=False)
    f["activity"] = _save(fig, "activity_by_hour.png")

    # 10 outliers
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    base = df[~df.is_outlier].sample(20000, random_state=0)
    out = df[df.is_outlier]
    ax.scatter(base.Timestamp, base[R], s=2, color="#b8c4d6", linewidths=0, rasterized=True)
    ax.scatter(out.Timestamp, out[R], s=9, color=C_ACC, linewidths=0, rasterized=True)
    ax.set_ylabel("Redemptions per 15 min"); ax.set_title(f"Flagged outliers ({len(out)}, red) versus a 20,000-interval sample (grey)")
    f["outliers"] = _save(fig, "outliers.png")

    # 11 YoY heat (median per year) - simple bar of annual vs reference
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    a = m["ann"].set_index("year")
    pct = 100 * (a[R] / m["ref_annual_mean"] - 1)
    cols = [C_ACC if v < -20 else C_R for v in pct]
    ax.bar(pct.index.astype(str), pct.values, color=cols, width=0.62)
    ax.axhline(0, color=C_MUTED, lw=0.8)
    for x_, v in zip(pct.index.astype(str), pct.values):
        ax.text(x_, v + (4 if v >= 0 else -9), f"{v:+.0f}%", ha="center", fontsize=7.5, color=C_INK)
    ax.set_ylabel("% vs reference-year mean"); ax.grid(axis="x", visible=False); ax.set_ylim(-100, 28)
    ax.set_title("Annual redemptions versus the mean of reference years (2016, 2018-19, 2022-24)")
    f["vs_ref"] = _save(fig, "annual_vs_reference.png")


if __name__ == "__main__":
    out = compute_all()
    print({k: v for k, v in out.items() if k in ("kr",)})
    print("figures:", list(out["figs"]))

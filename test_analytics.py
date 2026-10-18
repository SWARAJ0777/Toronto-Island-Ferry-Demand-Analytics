import numpy as np
import pandas as pd
import pytest

import analytics as an
import config as cfg
import data_processing as dp
import visualizations as viz
from conftest import make_raw

R, S = cfg.COL_REDEEM, cfg.COL_SALES


def frame(rows, with_sales=True):
    d = pd.DataFrame(rows, columns=["Timestamp", R] + ([S] if with_sales else []))
    d["Timestamp"] = pd.to_datetime(d["Timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
    return dp.clean(d)[0]


# ---- aggregation ------------------------------------------------------------------
def test_hourly_aggregation_sums_not_averages():
    df = frame([("2024-07-01 10:00", 1, 10), ("2024-07-01 10:15", 2, 20), ("2024-07-01 10:30", 3, 30), ("2024-07-01 11:00", 5, 50)])
    h = an.aggregate(df, "hour")
    assert h[R].tolist() == [6, 5] and h[S].tolist() == [60, 50]


def test_daily_and_monthly_aggregation():
    df = frame([("2024-07-01 10:00", 1, 1), ("2024-07-01 23:45", 2, 2), ("2024-07-02 00:00", 4, 4), ("2024-08-01 12:00", 8, 8)])
    assert an.aggregate(df, "day")[R].tolist() == [3, 4, 8]
    m = an.aggregate(df, "month")
    assert m["year_month"].tolist() == ["2024-07", "2024-08"] and m[R].tolist() == [7, 8]
    assert an.aggregate(df, "year")[R].tolist() == [15]


def test_aggregation_total_matches_source(clean_df):
    for lvl in ("interval", "hour", "day", "month", "year"):
        assert an.aggregate(clean_df, lvl)[R].sum() == clean_df[R].sum()


def test_aggregate_bad_level_and_empty(clean_df):
    with pytest.raises(ValueError):
        an.aggregate(clean_df, "week")
    assert an.aggregate(clean_df.iloc[0:0], "day").empty


# ---- KPIs --------------------------------------------------------------------------
def test_kpis_known_values():
    rows = []
    for day, mult in (("2024-07-06", 10), ("2024-07-07", 10), ("2024-07-08", 1), ("2024-07-09", 1)):   # Sat, Sun, Mon, Tue
        rows += [(f"{day} 12:00", 10 * mult, 5), (f"{day} 12:15", 10 * mult, 5), (f"{day} 03:00", 1, 1)]
    df = frame(rows)
    k = an.compute_kpis(df, R)
    assert k["total"] == (200 + 1) * 2 + (20 + 1) * 2
    assert k["days"] == 4
    assert k["mean_daily_total"] == pytest.approx(((201) * 2 + 21 * 2) / 4)
    assert k["peak_hour"] == 12
    assert k["weekend_mean_daily"] == pytest.approx(201) and k["weekday_mean_daily"] == pytest.approx(21)
    assert k["weekend_vs_weekday_ratio"] == pytest.approx(201 / 21)
    assert k["max_daily_total"] == 201
    assert k["mean_per_observed_interval"] == pytest.approx(k["total"] / 12)
    assert k["mean_per_observed_hour"] == pytest.approx(k["total"] / 8)       # 8 distinct hour buckets (2 per day x 4)


def test_offpeak_requires_enough_active_days():
    rows = [(f"2024-07-0{d} 12:00", 100, 1) for d in range(1, 8)] + [("2024-07-01 03:00", 1, 1)]   # 03:00 active on 1 of 7 days
    k = an.compute_kpis(frame(rows), R)
    assert k["peak_hour"] == 12 and k["offpeak_hour"] == 12      # 03:00 excluded: active on only 1 of 7 days (<90%)


def test_kpis_empty():
    assert an.compute_kpis(pd.DataFrame(), R) == {"empty": True}


def test_kpis_missing_sales_measure():
    df = dp.clean(make_raw(with_sales=False))[0]
    assert an.measures(df) == [R]
    assert an.compute_kpis(df, S) == {"empty": True}
    assert an.sales_vs_redemption(df) is None
    assert an.daily_difference(df).empty


def test_seasonal_index_baseline_is_100():
    rows = [("2024-01-10 12:00", 10, 1), ("2024-04-10 12:00", 20, 1), ("2024-07-10 12:00", 60, 1), ("2024-10-10 12:00", 10, 1)]
    si = an.seasonal_index(frame(rows), R).set_index("season")
    assert si.loc["Summer", "index"] == pytest.approx(100 * 60 / 25)
    assert si.loc["Winter", "index"] == pytest.approx(40)
    # day-weighted mean of indices equals 100
    assert (si["index"] * si["days"]).sum() / si["days"].sum() == pytest.approx(100)


def test_low_to_peak_ratio():
    rows = [("2024-01-10 12:00", 10, 1), ("2024-07-10 12:00", 100, 1)]
    k = an.compute_kpis(frame(rows), R)
    assert k["peak_season"] == "Summer" and k["low_season"] == "Winter" and k["low_to_peak_season_ratio"] == pytest.approx(0.1)


def test_peak_window():
    rows = [(f"2024-07-01 {h:02d}:00", 100 if 11 <= h <= 13 else 1, 1) for h in range(24)]
    pw = an.peak_window(frame(rows), R, 3)
    assert pw["start_hour"] == 11 and pw["end_hour"] == 14 and 0 < pw["share_of_daily_total"] < 1


def test_peak_days_and_intervals(clean_df):
    top = an.peak_days(clean_df, R, 5)
    assert len(top) == clean_df["date"].nunique() == 2 and top[R].is_monotonic_decreasing
    assert an.peak_intervals(clean_df, R, 2)[R].iloc[0] == clean_df[R].max()


# ---- sales vs redemption ------------------------------------------------------------------
def test_sales_vs_redemption_values():
    df = frame([("2024-07-01 10:00", 10, 12), ("2024-07-01 10:15", 10, 8), ("2024-07-02 10:00", 5, 9)])
    sv = an.sales_vs_redemption(df)
    assert sv["total_sales"] == 29 and sv["total_redemptions"] == 25 and sv["difference"] == 4
    assert sv["sales_to_redemption_ratio"] == pytest.approx(29 / 25)
    assert sv["days_sales_gt_redemptions"] == 1 and sv["days"] == 2
    d = an.daily_difference(df)
    assert d["sales_minus_redemptions"].tolist() == [0, 4]


# ---- rolling ----------------------------------------------------------------------------------
def test_rolling_mean_values_and_edges():
    df = frame([(f"2024-07-01 10:{m:02d}", v, 1) for m, v in zip((0, 15, 30, 45), (4, 8, 12, 16))])
    g = dp.build_regular_grid(df)
    r = an.rolling_demand(g, R, {"1-hour": 4, "30-min": 2})
    assert r["rolling_1-hour"].isna().sum() == 3 and r["rolling_1-hour"].iloc[3] == pytest.approx(10)
    assert r["rolling_30-min"].tolist()[1:] == [6, 10, 14]


def test_rolling_default_windows_present():
    g = dp.build_regular_grid(dp.clean(make_raw())[0])
    r = an.rolling_demand(g, R)
    assert {"rolling_1-hour", "rolling_4-hour"} <= set(r.columns)
    assert r["rolling_4-hour"].notna().sum() == len(g) - 15


# ---- filters ----------------------------------------------------------------------------------
@pytest.fixture
def week():
    ts = pd.date_range("2024-07-01", "2024-07-14 23:45", freq="1h")
    raw = pd.DataFrame({"Timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "Redemption Count": 1, "Sales Count": 1})
    return dp.clean(raw)[0]


def test_filter_date_boundaries_inclusive(week):
    f = an.apply_filters(week, an.Filters(start_date=pd.Timestamp("2024-07-03"), end_date=pd.Timestamp("2024-07-05")))
    assert f["date"].min() == pd.Timestamp("2024-07-03") and f["date"].max() == pd.Timestamp("2024-07-05")
    assert f["date"].nunique() == 3 and len(f) == 72


def test_filter_single_day_and_out_of_range(week):
    one = an.apply_filters(week, an.Filters(start_date=pd.Timestamp("2024-07-04"), end_date=pd.Timestamp("2024-07-04")))
    assert len(one) == 24
    none = an.apply_filters(week, an.Filters(start_date=pd.Timestamp("2030-01-01")))
    assert none.empty


def test_filter_hours_inclusive(week):
    f = an.apply_filters(week, an.Filters(hour_range=(9, 11)))
    assert sorted(f["hour"].unique()) == [9, 10, 11]


def test_filter_weekday_weekend(week):
    assert an.apply_filters(week, an.Filters(day_type="Weekend"))["is_weekend"].all()
    wd = an.apply_filters(week, an.Filters(day_type="Weekday"))
    assert not wd["is_weekend"].any() and len(wd) == 10 * 24


def test_filter_days_months_years(week):
    assert an.apply_filters(week, an.Filters(days_of_week=[0]))["day_name"].unique().tolist() == ["Monday"]
    assert an.apply_filters(week, an.Filters(months=[8])).empty
    assert len(an.apply_filters(week, an.Filters(years=[2024]))) == len(week)
    assert an.apply_filters(week, an.Filters(days_of_week=[])).empty          # nothing selected -> empty, no crash


def test_filter_excludes_outliers(week):
    w = week.copy()
    w.loc[w.index[:5], "is_outlier"] = True
    assert len(an.apply_filters(w, an.Filters(exclude_outliers=True))) == len(w) - 5


def test_filter_combination_consistent_with_kpis(week):
    f = an.apply_filters(week, an.Filters(day_type="Weekend", hour_range=(0, 11)))
    assert an.compute_kpis(f, R)["total"] == len(f) == 4 * 12


def test_filters_on_empty_frame(week):
    assert an.apply_filters(week.iloc[0:0], an.Filters()).empty


# ---- year over year ----------------------------------------------------------------------------
def test_yoy_requires_full_months():
    rows = [(d.strftime("%Y-%m-%d 12:00"), 10, 1) for d in pd.date_range("2023-07-01", "2023-07-31")]
    rows += [(d.strftime("%Y-%m-%d 12:00"), 20, 1) for d in pd.date_range("2024-07-01", "2024-07-31")]
    rows += [(d.strftime("%Y-%m-%d 12:00"), 99, 1) for d in pd.date_range("2023-08-01", "2023-08-05")]     # partial month
    rows += [(d.strftime("%Y-%m-%d 12:00"), 99, 1) for d in pd.date_range("2024-08-01", "2024-08-31")]
    y = an.yoy_table(frame(rows), R)
    assert len(y) == 1 and y["month"].iloc[0] == 7 and y["yoy_pct"].iloc[0] == pytest.approx(100.0)


def test_yoy_empty():
    assert an.yoy_table(pd.DataFrame(), R).empty


# ---- insights ------------------------------------------------------------------------------------
def test_insights_contain_computed_numbers(clean_df):
    ins = an.generate_insights(clean_df, R)
    assert ins["findings"] and f"{int(clean_df[R].sum()):,}" in ins["findings"][0]
    assert an.generate_insights(clean_df.iloc[0:0], R) == {"findings": [], "recommendations": []}


# ---- charts ------------------------------------------------------------------------------------------
def test_all_charts_build_with_minimal_and_empty_data(clean_df):
    for d in (clean_df, clean_df.iloc[:2], clean_df.iloc[0:0]):
        figs = [
            viz.time_series(an.aggregate(d, "day"), "date", an.measures(d), "t"),
            viz.hourly_profile_fig(an.hourly_profile(d, R), R, 10, 3),
            viz.interval_profile_fig(an.interval_profile(d, R), R),
            viz.dow_fig(an.day_of_week_profile(d, R), R),
            viz.monthly_fig(an.monthly_profile(d, R), R),
            viz.season_fig(an.seasonal_index(d, R)),
            viz.weekday_weekend_fig(an.weekday_weekend(d, R), R),
            viz.heatmap_fig(d, R),
            viz.sales_vs_redemption_fig(an.aggregate(d, "day")),
            viz.sales_redemption_scatter(d),
            viz.difference_fig(an.daily_difference(d)),
            viz.yoy_fig(an.yoy_table(d, R)),
            viz.annual_fig(an.annual_summary(d), an.measures(d)),
            viz.absent_hour_fig(dp.absent_by_hour(d) if len(d) else pd.DataFrame()),
            viz.outlier_fig(d, R),
            viz.rolling_fig(an.rolling_demand(dp.build_regular_grid(d), R) if len(d) else pd.DataFrame(), R),
        ]
        assert all(hasattr(f, "to_dict") for f in figs)


def test_sales_charts_show_unavailable_state_without_sales():
    d = dp.clean(make_raw(with_sales=False))[0]
    fig = viz.sales_vs_redemption_fig(an.aggregate(d, "day"))
    assert "not available" in fig.layout.annotations[0].text


# ---- exports -----------------------------------------------------------------------------------------------
def test_csv_export_columns_and_filtered_rows(week):
    f = an.apply_filters(week, an.Filters(day_type="Weekend"))
    out = pd.read_csv(pd.io.common.StringIO(f.drop(columns=["hour_start"]).to_csv(index=False)))
    assert len(out) == len(f) and {"Timestamp", R, S, "day_name", "season", "is_outlier"} <= set(out.columns)
    hourly = pd.read_csv(pd.io.common.StringIO(an.aggregate(f, "hour").to_csv(index=False)))
    assert list(hourly.columns) == ["hour_start", R, S] and hourly[R].sum() == f[R].sum()


def test_offpeak_threshold_is_90_percent_of_days():
    base = [(f"2024-07-{d:02d} 12:00", 100, 1) for d in range(1, 11)]
    eight_of_ten = base + [(f"2024-07-{d:02d} 22:00", 2, 1) for d in range(1, 9)]       # 80% of days -> excluded
    nine_of_ten = base + [(f"2024-07-{d:02d} 22:00", 2, 1) for d in range(1, 10)]       # 90% of days -> ranked
    assert an.compute_kpis(frame(eight_of_ten), R)["offpeak_hour"] == 12
    assert an.compute_kpis(frame(nine_of_ten), R)["offpeak_hour"] == 22

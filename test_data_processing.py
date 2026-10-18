import io
import numpy as np
import pandas as pd
import pytest

import config as cfg
import data_processing as dp
from conftest import make_raw


# ---- loading -------------------------------------------------------------
def test_load_from_path(csv_file):
    df, rep = dp.load_and_prepare(csv_file)
    assert len(df) == 96 and rep.rows_raw == 96 and rep.has_sales


def test_load_from_filelike(raw):
    buf = io.BytesIO(raw.to_csv(index=False).encode())
    df, rep = dp.load_and_prepare(buf, filename="up.csv")
    assert len(df) == 96


def test_missing_file(tmp_path):
    with pytest.raises(dp.DataError, match="not found"):
        dp.load_and_prepare(tmp_path / "nope.csv")


def test_unsupported_format(tmp_path):
    p = tmp_path / "x.xlsx"
    p.write_text("a")
    with pytest.raises(dp.DataError, match="Unsupported file format"):
        dp.load_and_prepare(p)


def test_empty_file(tmp_path):
    p = tmp_path / "e.csv"
    p.write_text("")
    with pytest.raises(dp.DataError, match="empty"):
        dp.load_and_prepare(p)


def test_header_only(tmp_path):
    p = tmp_path / "h.csv"
    p.write_text("_id,Timestamp,Redemption Count\n")
    with pytest.raises(dp.DataError, match="no data rows"):
        dp.load_and_prepare(p)


def test_missing_required_column(raw):
    with pytest.raises(dp.DataError, match="Missing required column"):
        dp.clean(raw.drop(columns=["Redemption Count"]))


def test_missing_timestamp_column(raw):
    with pytest.raises(dp.DataError, match="Timestamp"):
        dp.clean(raw.drop(columns=["Timestamp"]))


# ---- timestamp parsing ---------------------------------------------------
def test_timestamp_parsing_and_sorting(raw):
    shuffled = raw.sample(frac=1, random_state=1)
    df, rep = dp.clean(shuffled)
    assert df["Timestamp"].is_monotonic_increasing
    assert rep.was_sorted_by_cleaning
    assert str(df["Timestamp"].dt.tz) == "None"          # stays naive, never reinterpreted as UTC


def test_unparseable_timestamps_dropped_and_counted(raw):
    raw = raw.copy()
    raw.loc[3, "Timestamp"] = "not a date"
    raw.loc[4, "Timestamp"] = None
    df, rep = dp.clean(raw)
    assert rep.unparseable_timestamps_dropped == 2 and len(df) == 94


def test_tz_aware_timestamps_converted_to_toronto():
    raw = pd.DataFrame({"Timestamp": ["2024-07-01T12:00:00+00:00"], "Redemption Count": [5]})
    df, rep = dp.clean(raw)
    assert df["Timestamp"].iloc[0] == pd.Timestamp("2024-07-01 08:00")   # EDT = UTC-4
    assert any("converted" in n for n in rep.notes)


# ---- duplicates --------------------------------------------------------------
def test_exact_duplicates_dropped(raw):
    dup = pd.concat([raw, raw.iloc[[5]]], ignore_index=True)
    df, rep = dp.clean(dup)
    assert rep.exact_duplicate_rows_dropped == 1 and len(df) == 96


def test_repeated_timestamp_with_different_counts_is_summed_not_dropped(raw):
    extra = raw.iloc[[5]].copy()
    extra["Redemption Count"] += 1000
    extra["Sales Count"] += 1000
    extra["_id"] = 9999
    df, rep = dp.clean(pd.concat([raw, extra], ignore_index=True))
    assert rep.duplicate_timestamps_aggregated == 1 and len(df) == 96
    orig = raw.iloc[5]["Redemption Count"]
    assert df.loc[df["Timestamp"] == pd.Timestamp(raw.iloc[5]["Timestamp"]), "Redemption Count"].iloc[0] == 2 * orig + 1000
    assert df["Redemption Count"].sum() == raw["Redemption Count"].sum() + orig + 1000   # no double counting


def test_total_preserved_when_no_issues(raw):
    df, _ = dp.clean(raw)
    assert df["Redemption Count"].sum() == raw["Redemption Count"].sum()
    assert df["Sales Count"].sum() == raw["Sales Count"].sum()


# ---- invalid values -------------------------------------------------------------
def test_negative_counts_dropped(raw):
    raw = raw.copy()
    raw.loc[2, "Redemption Count"] = -5
    raw.loc[7, "Sales Count"] = -1
    df, rep = dp.clean(raw)
    assert rep.negative_values_dropped == 2 and len(df) == 94 and (df["Redemption Count"] >= 0).all()


def test_missing_counts_dropped_not_zero_filled(raw):
    raw = raw.copy()
    raw["Redemption Count"] = raw["Redemption Count"].astype(object)
    raw.loc[1, "Redemption Count"] = np.nan
    raw.loc[2, "Redemption Count"] = "abc"
    df, rep = dp.clean(raw)
    assert len(df) == 94 and rep.missing_values_dropped["Redemption Count"] == 2


def test_non_integer_counts_dropped(raw):
    raw = raw.copy()
    raw["Redemption Count"] = raw["Redemption Count"].astype(float)
    raw.loc[0, "Redemption Count"] = 2.5
    df, rep = dp.clean(raw)
    assert rep.non_integer_values_dropped == 1 and len(df) == 95


def test_all_invalid_raises(raw):
    raw = raw.copy()
    raw["Timestamp"] = "bad"
    with pytest.raises(dp.DataError, match="No valid rows"):
        dp.clean(raw)


def test_input_not_mutated(raw):
    before = raw.copy()
    dp.clean(raw)
    pd.testing.assert_frame_equal(raw, before)


# ---- missing sales -------------------------------------------------------------
def test_sales_column_optional():
    df, rep = dp.clean(make_raw(with_sales=False))
    assert not rep.has_sales and "Sales Count" not in df.columns


# ---- features -------------------------------------------------------------------
def test_features():
    raw = pd.DataFrame({"Timestamp": ["2024-07-06T17:45:00", "2024-01-02T00:00:00"], "Redemption Count": [10, 1]})
    df, _ = dp.clean(raw)
    jan, jul = df.iloc[0], df.iloc[1]
    assert jul["day_name"] == "Saturday" and jul["is_weekend"] and jul["day_type"] == "Weekend"
    assert jul["season"] == "Summer" and jul["quarter"] == 3 and jul["hour"] == 17
    assert jul["interval_of_day"] == 17 * 4 + 3 and jul["year_month"] == "2024-07"
    assert jan["season"] == "Winter" and not jan["is_weekend"] and jan["quarter"] == 1


def test_season_boundaries():
    for m, s in {12: "Winter", 2: "Winter", 3: "Spring", 5: "Spring", 6: "Summer", 8: "Summer", 9: "Fall", 11: "Fall"}.items():
        assert cfg.SEASON_BY_MONTH[m] == s


def test_off_grid_timestamps_floored_and_reported():
    raw = pd.DataFrame({"Timestamp": ["2024-07-01T10:07:00", "2024-07-01T10:15:00"], "Redemption Count": [1, 2]})
    df, rep = dp.clean(raw)
    assert rep.non_quarter_hour_timestamps == 1
    assert df["interval_start"].iloc[0] == pd.Timestamp("2024-07-01 10:00")


# ---- DST ---------------------------------------------------------------------------------
def test_dst_transition_days_detected():
    days = pd.to_datetime(["2024-03-10", "2024-11-03", "2024-07-01"])
    got = dp.dst_transition_days(days)
    assert pd.Timestamp("2024-03-10") in got and pd.Timestamp("2024-11-03") in got
    assert pd.Timestamp("2024-07-01") not in got


def test_dst_flag_on_features():
    raw = pd.DataFrame({"Timestamp": ["2024-03-10T12:00:00", "2024-03-11T12:00:00"], "Redemption Count": [1, 1]})
    df, rep = dp.clean(raw)
    assert df["dst_transition_day"].tolist() == [True, False] and rep.dst_transition_days_in_data == 1


def test_data_near_dst_does_not_crash():
    ts = pd.date_range("2024-03-10 00:00", periods=96, freq="15min")
    raw = pd.DataFrame({"Timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "Redemption Count": 1})
    df, _ = dp.clean(raw)
    assert len(df) == 96


# ---- coverage / gaps -------------------------------------------------------------------
def test_coverage_counts_absent_intervals():
    raw = make_raw(periods=10)
    raw = raw.drop(index=[3, 4, 5])               # remove 3 interior intervals
    df, rep = dp.clean(raw)
    assert rep.observed_intervals == 7
    assert rep.expected_intervals_within_day_span == 10
    assert rep.absent_intervals_within_day_span == 3
    assert rep.completeness_within_day_span_pct == 70.0


def test_missing_calendar_days_listed():
    raw = pd.DataFrame({"Timestamp": ["2024-07-01T10:00:00", "2024-07-04T10:00:00"], "Redemption Count": [1, 1]})
    _, rep = dp.clean(raw)
    assert rep.missing_calendar_days == ["2024-07-02", "2024-07-03"] and rep.n_calendar_days == 4


def test_gap_table_finds_long_gap():
    ts = list(pd.date_range("2024-07-01 08:00", periods=4, freq="15min")) + list(pd.date_range("2024-07-01 15:00", periods=4, freq="15min"))
    raw = pd.DataFrame({"Timestamp": pd.Series(ts).dt.strftime("%Y-%m-%dT%H:%M:%S"), "Redemption Count": 1})
    df, _ = dp.clean(raw)
    g = dp.gap_table(df, min_gap_intervals=8)
    assert len(g) == 1 and g["absent_intervals"].iloc[0] == 24     # 08:45..15:00 exclusive = 24 intervals


def test_regular_grid_zero_fill_and_nan():
    raw = make_raw(periods=6).drop(index=[2])
    df, _ = dp.clean(raw)
    zf = dp.build_regular_grid(df)
    nf = dp.build_regular_grid(df, zero_fill_absent=False)
    assert len(zf) == 6 and zf["Redemption Count"].iloc[2] == 0
    assert nf["Redemption Count"].isna().sum() == 1


def test_regular_grid_empty():
    df, _ = dp.clean(make_raw())
    assert dp.build_regular_grid(df.iloc[0:0]).empty


# ---- outliers --------------------------------------------------------------------------------
def test_outlier_flagged_but_retained():
    rng = np.random.default_rng(1)
    n = 400
    ts = pd.date_range("2024-07-01 12:00", periods=n, freq="1D")
    vals = rng.integers(180, 220, n)
    vals[100] = 9000
    raw = pd.DataFrame({"Timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"), "Redemption Count": vals})
    df, rep = dp.clean(raw)
    assert len(df) == n and rep.outliers_flagged >= 1
    assert df.loc[df["Redemption Count"] == 9000, "is_outlier"].all()


def test_small_values_not_flagged():
    raw = make_raw(periods=500)
    df, _ = dp.clean(raw)
    assert not df["is_outlier"].any()

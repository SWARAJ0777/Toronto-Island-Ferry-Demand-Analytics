"""Data loading, validation, cleaning and feature engineering.

No Streamlit imports here: this module is pure pandas/numpy so it can be tested
and reused independently of the dashboard.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import config as cfg


class DataError(Exception):
    """Raised for user-facing data problems (bad file, missing columns, no usable rows)."""


@dataclass
class CleaningReport:
    """Transparent summary of everything the pipeline checked or changed."""

    source: str = ""
    rows_raw: int = 0
    rows_clean: int = 0
    columns: list[str] = field(default_factory=list)
    has_sales: bool = False
    has_id: bool = False
    unparseable_timestamps_dropped: int = 0
    missing_values_dropped: dict[str, int] = field(default_factory=dict)
    negative_values_dropped: int = 0
    non_integer_values_dropped: int = 0
    non_quarter_hour_timestamps: int = 0
    exact_duplicate_rows_dropped: int = 0
    duplicate_timestamps_aggregated: int = 0
    duplicate_ids: int = 0
    zero_redemption_rows: int = 0
    zero_sales_rows: int = 0
    rows_with_both_zero: int = 0
    was_sorted_by_cleaning: bool = False
    first_timestamp: str = ""
    last_timestamp: str = ""
    n_days_present: int = 0
    n_calendar_days: int = 0
    missing_calendar_days: list[str] = field(default_factory=list)
    observed_intervals: int = 0
    expected_intervals_within_day_span: int = 0
    absent_intervals_within_day_span: int = 0
    expected_intervals_full_days: int = 0
    completeness_within_day_span_pct: float = 0.0
    completeness_full_days_pct: float = 0.0
    outliers_flagged: int = 0
    dst_transition_days_in_data: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------
def read_raw(source: str | Path | io.IOBase | Any, filename: str | None = None) -> pd.DataFrame:
    """Read a CSV from a path or an uploaded file-like object.

    Raises DataError with a readable message for unsupported/missing/empty input.
    """
    name = filename or (str(source) if isinstance(source, (str, Path)) else getattr(source, "name", ""))
    suffix = Path(name).suffix.lower()
    if suffix not in cfg.SUPPORTED_EXTENSIONS:
        raise DataError(
            f"Unsupported file format '{suffix or 'unknown'}'. Please provide a CSV file (.csv)."
        )
    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.exists():
            raise DataError(
                f"Data file not found: {path}. Place the CSV in the data/ folder or upload it in the sidebar."
            )
    try:
        df = pd.read_csv(source)
    except pd.errors.EmptyDataError as exc:
        raise DataError("The file is empty.") from exc
    except (pd.errors.ParserError, UnicodeDecodeError) as exc:
        raise DataError(f"Could not parse the CSV file: {exc}") from exc
    if df.empty:
        raise DataError("The file contains a header but no data rows.")
    return df


def validate_schema(df: pd.DataFrame) -> None:
    missing = [c for c in cfg.REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise DataError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Required: {', '.join(cfg.REQUIRED_COLUMNS)}. Found: {', '.join(map(str, df.columns))}."
        )


# ----------------------------------------------------------------------------
# Cleaning
# ----------------------------------------------------------------------------
def clean(raw: pd.DataFrame, source: str = "") -> tuple[pd.DataFrame, CleaningReport]:
    """Validate and clean raw data. The input frame is never modified.

    Strategy (all counted in the returned report):
      * Unparseable timestamps and rows with missing/non-numeric counts are dropped (never zero-filled).
      * Negative or non-integer counts are impossible for ticket counts and are dropped.
      * Exact duplicate rows (same timestamp AND same counts) are dropped; rows that repeat a
        timestamp with different counts are kept distinct and summed per timestamp, because
        they may be legitimate partial records. Both cases are reported.
      * Rows are sorted chronologically. Timestamps stay timezone-naive local wall-clock time.
    """
    validate_schema(raw)
    rep = CleaningReport(source=source, rows_raw=len(raw), columns=list(map(str, raw.columns)))
    df = raw.copy()
    rep.has_sales = cfg.COL_SALES in df.columns
    rep.has_id = cfg.COL_ID in df.columns

    count_cols = [cfg.COL_REDEEM] + ([cfg.COL_SALES] if rep.has_sales else [])

    # Timestamps -------------------------------------------------------------
    ts = pd.to_datetime(df[cfg.COL_TS], errors="coerce")
    if getattr(ts.dt, "tz", None) is not None:
        # Convert explicit-offset timestamps to Toronto wall-clock, then drop the tz.
        ts = ts.dt.tz_convert(cfg.LOCAL_TZ).dt.tz_localize(None)
        rep.notes.append("Timestamps carried a UTC offset and were converted to Toronto local time.")
    df[cfg.COL_TS] = ts
    bad_ts = ts.isna()
    rep.unparseable_timestamps_dropped = int(bad_ts.sum())

    # Counts ------------------------------------------------------------------
    for c in count_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    miss = {c: int(df[c].isna().sum()) for c in count_cols}
    rep.missing_values_dropped = {k: v for k, v in miss.items() if v}
    bad_counts = df[count_cols].isna().any(axis=1)

    drop = bad_ts | bad_counts
    df = df.loc[~drop].copy()

    neg = (df[count_cols] < 0).any(axis=1)
    rep.negative_values_dropped = int(neg.sum())
    nonint = ((df[count_cols] % 1) != 0).any(axis=1) & ~neg
    rep.non_integer_values_dropped = int(nonint.sum())
    df = df.loc[~(neg | nonint)].copy()
    for c in count_cols:
        df[c] = df[c].astype("int64")

    if df.empty:
        raise DataError("No valid rows remain after validation (check timestamp and count columns).")

    # Duplicates ---------------------------------------------------------------
    if rep.has_id:
        rep.duplicate_ids = int(df[cfg.COL_ID].duplicated().sum())
    rep.was_sorted_by_cleaning = not df[cfg.COL_TS].is_monotonic_increasing
    key = [cfg.COL_TS] + count_cols
    exact = df.duplicated(subset=key, keep="first")
    rep.exact_duplicate_rows_dropped = int(exact.sum())
    df = df.loc[~exact].copy()
    dup_ts = df[cfg.COL_TS].duplicated(keep=False)
    if dup_ts.any():
        rep.duplicate_timestamps_aggregated = int(df[cfg.COL_TS].duplicated().sum())
        agg = {c: "sum" for c in count_cols}
        if rep.has_id:
            agg[cfg.COL_ID] = "first"
        df = df.groupby(cfg.COL_TS, as_index=False).agg(agg)
    df = df.sort_values(cfg.COL_TS, kind="mergesort").reset_index(drop=True)

    # Interval alignment -------------------------------------------------------
    ts = df[cfg.COL_TS]
    off_grid = (ts.dt.minute % cfg.INTERVAL_MINUTES != 0) | (ts.dt.second != 0)
    rep.non_quarter_hour_timestamps = int(off_grid.sum())
    if rep.non_quarter_hour_timestamps:
        rep.notes.append(
            f"{rep.non_quarter_hour_timestamps} timestamps are not on a 15-minute boundary; "
            "they are kept as-is and floored to their interval in 'interval_start'."
        )

    # Zero semantics ----------------------------------------------------------------
    rep.zero_redemption_rows = int((df[cfg.COL_REDEEM] == 0).sum())
    if rep.has_sales:
        rep.zero_sales_rows = int((df[cfg.COL_SALES] == 0).sum())
        rep.rows_with_both_zero = int(((df[cfg.COL_REDEEM] == 0) & (df[cfg.COL_SALES] == 0)).sum())

    df = add_features(df)
    df = flag_outliers(df)
    rep.outliers_flagged = int(df["is_outlier"].sum())
    rep.rows_clean = len(df)
    _coverage(df, rep)
    rep.dst_transition_days_in_data = int(df.loc[df["dst_transition_day"], "date"].nunique())
    if rep.has_sales and rep.rows_with_both_zero == 0:
        rep.notes.append(
            "No row has both counts equal to zero, so intervals without any activity appear to be "
            "omitted from the file rather than stored as zero rows. Absent intervals are therefore "
            "reported as 'absent', not 'missing', and are zero-filled only where an analysis "
            "explicitly says so."
        )
    return df, rep


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add calendar and interval features derived from the (naive local) timestamp."""
    out = df.copy()
    ts = out[cfg.COL_TS]
    out["interval_start"] = ts.dt.floor(f"{cfg.INTERVAL_MINUTES}min")
    out["date"] = ts.dt.normalize()
    out["year"] = ts.dt.year
    out["quarter"] = ts.dt.quarter
    out["month"] = ts.dt.month
    out["month_name"] = out["month"].map(lambda m: cfg.MONTH_NAMES[m - 1])
    out["year_month"] = ts.dt.to_period("M").astype(str)
    out["day_of_week"] = ts.dt.dayofweek            # Monday = 0
    out["day_name"] = out["day_of_week"].map(lambda d: cfg.DAY_NAMES[d])
    out["is_weekend"] = out["day_of_week"] >= 5
    out["day_type"] = np.where(out["is_weekend"], "Weekend", "Weekday")
    out["season"] = out["month"].map(cfg.SEASON_BY_MONTH)
    out["hour"] = ts.dt.hour
    out["interval_of_day"] = out["hour"] * cfg.INTERVALS_PER_HOUR + ts.dt.minute // cfg.INTERVAL_MINUTES
    out["time_label"] = ts.dt.strftime("%H:%M")
    out["hour_start"] = ts.dt.floor("h")
    out["dst_transition_day"] = out["date"].isin(dst_transition_days(out["date"].unique()))
    return out


def dst_transition_days(dates) -> set[pd.Timestamp]:
    """Dates (naive midnight) on which Toronto's local day is not 24 hours long."""
    dates = pd.DatetimeIndex(pd.to_datetime(list(dates))).normalize().unique()
    if len(dates) == 0:
        return set()
    result: set[pd.Timestamp] = set()
    tz = cfg.LOCAL_TZ
    for d in dates:
        # Midnight always exists in Toronto (DST changes happen at 02:00).
        start = d.tz_localize(tz)
        nxt = (d + pd.Timedelta(days=1)).tz_localize(tz)
        if (nxt - start) != pd.Timedelta(hours=24):
            result.add(d)
    return result


def flag_outliers(df: pd.DataFrame) -> pd.DataFrame:
    """Flag statistical outliers using a modified z-score within (month, hour) groups.

    Informational only: flagged rows stay in the data because genuine peak demand can look extreme.
    """
    out = df.copy()
    out["outlier_score"] = 0.0
    out["is_outlier"] = False
    x = np.log1p(out[cfg.COL_REDEEM].astype(float))
    grp = out.groupby(["month", "hour"])[cfg.COL_REDEEM]
    size = grp.transform("size")
    med = x.groupby([out["month"], out["hour"]]).transform("median")
    mad = (x - med).abs().groupby([out["month"], out["hour"]]).transform("median")
    scale = np.maximum(mad, 0.05) * 1.4826            # floor avoids division by ~0 in flat groups
    score = (x - med) / scale
    out["outlier_score"] = score.where(size >= cfg.OUTLIER_MIN_GROUP_SIZE, 0.0).round(2)
    out["is_outlier"] = (out["outlier_score"] > cfg.OUTLIER_MODZ_THRESHOLD) & (
        out[cfg.COL_REDEEM] >= cfg.OUTLIER_MIN_COUNT
    )
    return out


# ----------------------------------------------------------------------------
# Coverage / completeness
# ----------------------------------------------------------------------------
def _coverage(df: pd.DataFrame, rep: CleaningReport) -> None:
    ts = df[cfg.COL_TS]
    rep.first_timestamp = str(ts.min())
    rep.last_timestamp = str(ts.max())
    per_day = df.groupby("date")["interval_start"].agg(["min", "max", "nunique"])
    span = ((per_day["max"] - per_day["min"]).dt.total_seconds() / 60 / cfg.INTERVAL_MINUTES + 1).astype(int)
    rep.n_days_present = int(len(per_day))
    all_days = pd.date_range(ts.min().normalize(), ts.max().normalize(), freq="D")
    rep.n_calendar_days = len(all_days)
    rep.missing_calendar_days = [str(d.date()) for d in all_days.difference(per_day.index)]
    rep.observed_intervals = int(per_day["nunique"].sum())
    rep.expected_intervals_within_day_span = int(span.sum())
    rep.absent_intervals_within_day_span = rep.expected_intervals_within_day_span - rep.observed_intervals
    rep.expected_intervals_full_days = rep.n_calendar_days * cfg.INTERVALS_PER_DAY
    rep.completeness_within_day_span_pct = round(
        100 * rep.observed_intervals / max(rep.expected_intervals_within_day_span, 1), 2
    )
    rep.completeness_full_days_pct = round(
        100 * rep.observed_intervals / max(rep.expected_intervals_full_days, 1), 2
    )


def coverage_for(df: pd.DataFrame) -> dict[str, Any]:
    """Coverage metrics for an arbitrary (e.g. filtered) frame."""
    if df.empty:
        return {"observed_intervals": 0, "absent_intervals_within_day_span": 0,
                "completeness_within_day_span_pct": float("nan"), "days_present": 0}
    per_day = df.groupby("date")["interval_start"].agg(["min", "max", "nunique"])
    span = ((per_day["max"] - per_day["min"]).dt.total_seconds() / 60 / cfg.INTERVAL_MINUTES + 1).astype(int)
    obs = int(per_day["nunique"].sum())
    exp = int(span.sum())
    return {
        "observed_intervals": obs,
        "absent_intervals_within_day_span": exp - obs,
        "completeness_within_day_span_pct": round(100 * obs / max(exp, 1), 2),
        "days_present": int(len(per_day)),
    }


def gap_table(df: pd.DataFrame, min_gap_intervals: int = 8) -> pd.DataFrame:
    """Runs of absent 15-minute intervals longer than `min_gap_intervals` (default 2 hours)."""
    t = df["interval_start"].drop_duplicates().sort_values().reset_index(drop=True)
    step = t.diff().dt.total_seconds().div(60 * cfg.INTERVAL_MINUTES)
    idx = step[step > min_gap_intervals].index
    rows = [
        {"gap_start": t[i - 1] + pd.Timedelta(minutes=cfg.INTERVAL_MINUTES), "gap_end": t[i] - pd.Timedelta(minutes=cfg.INTERVAL_MINUTES),
         "absent_intervals": int(step[i] - 1)}
        for i in idx
    ]
    return pd.DataFrame(rows, columns=["gap_start", "gap_end", "absent_intervals"])


def absent_by_hour(df: pd.DataFrame) -> pd.DataFrame:
    """Share of calendar days (in the data's range) on which each hour-of-day has no recorded interval."""
    days = df["date"].nunique()
    seen = df.groupby("hour")["date"].nunique().reindex(range(24), fill_value=0)
    return pd.DataFrame({"hour": seen.index, "days_with_activity": seen.values,
                         "pct_days_with_activity": (100 * seen.values / max(days, 1)).round(1)})


# ----------------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------------
def load_and_prepare(source: str | Path | Any, filename: str | None = None) -> tuple[pd.DataFrame, CleaningReport]:
    """Read, validate, clean and feature-engineer a ferry-ticket CSV."""
    name = filename or (str(source) if isinstance(source, (str, Path)) else getattr(source, "name", "uploaded.csv"))
    raw = read_raw(source, filename=name)
    return clean(raw, source=Path(name).name)


def build_regular_grid(df: pd.DataFrame, start=None, end=None, zero_fill_absent: bool = True) -> pd.DataFrame:
    """Reindex to a regular 15-minute grid (needed for rolling windows).

    With zero_fill_absent=True, absent intervals become 0 (an ASSUMPTION: the file appears to omit
    zero-activity intervals). With False they remain NaN so callers can see real gaps.
    """
    if df.empty:
        return pd.DataFrame(columns=["interval_start", cfg.COL_REDEEM] + ([cfg.COL_SALES] if cfg.COL_SALES in df else []))
    cols = [cfg.COL_REDEEM] + ([cfg.COL_SALES] if cfg.COL_SALES in df.columns else [])
    s = df.groupby("interval_start")[cols].sum()
    lo = pd.Timestamp(start) if start is not None else s.index.min()
    hi = pd.Timestamp(end) if end is not None else s.index.max()
    grid = pd.date_range(lo.floor(f"{cfg.INTERVAL_MINUTES}min"), hi, freq=f"{cfg.INTERVAL_MINUTES}min")
    g = s.reindex(grid)
    if zero_fill_absent:
        g = g.fillna(0).astype("int64")
    g.index.name = "interval_start"
    return g.reset_index()

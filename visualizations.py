"""Plotly chart builders. Every function returns a Figure and accepts empty input."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

import config as cfg

C_REDEEM = "#1f6fb4"
C_SALES = "#d9730d"
C_NEUTRAL = "#6b7280"
C_PEAK = "#c0392b"
C_OFF = "#2e8b57"
MEASURE_COLORS = {cfg.COL_REDEEM: C_REDEEM, cfg.COL_SALES: C_SALES}


def _base(fig: go.Figure, title: str, x: str = "", y: str = "Tickets", height: int = 420) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0.0, font=dict(size=16)),
        xaxis_title=x, yaxis_title=y, height=height, template="plotly_white",
        margin=dict(l=50, r=20, t=60, b=50), hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        font=dict(family="Inter, Segoe UI, Arial, sans-serif", size=12),
    )
    return fig


def empty_figure(message: str = "No data for the current selection") -> go.Figure:
    fig = go.Figure()
    fig.add_annotation(text=message, showarrow=False, font=dict(size=15, color=C_NEUTRAL), xref="paper", yref="paper", x=0.5, y=0.5)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_layout(height=300, template="plotly_white")
    return fig


def _ok(df: pd.DataFrame, *cols: str) -> bool:
    return df is not None and not df.empty and all(c in df.columns for c in cols)


def time_series(df: pd.DataFrame, x: str, measure_cols: list[str], title: str, y_title: str = "Tickets") -> go.Figure:
    if not _ok(df, x) or not measure_cols:
        return empty_figure()
    fig = go.Figure()
    for m in measure_cols:
        if m in df.columns:
            fig.add_trace(go.Scatter(x=df[x], y=df[m], name=m, mode="lines", line=dict(width=1.4, color=MEASURE_COLORS.get(m)),
                                     hovertemplate="%{y:,.0f}<extra>" + m + "</extra>"))
    fig = _base(fig, title, y=y_title)
    fig.update_xaxes(rangeslider=dict(visible=len(df) > 30))
    return fig


def hourly_profile_fig(prof: pd.DataFrame, measure: str, peak_hour: int | None = None, off_hour: int | None = None) -> go.Figure:
    if not _ok(prof, "mean_hourly_total"):
        return empty_figure()
    colors = [C_PEAK if h == peak_hour else C_OFF if h == off_hour else MEASURE_COLORS.get(measure, C_REDEEM) for h in prof["hour"]]
    fig = go.Figure(go.Bar(x=prof["hour"], y=prof["mean_hourly_total"], marker_color=colors,
                           customdata=np.c_[prof["median_hourly_total"], prof["share_of_days_active"] * 100],
                           hovertemplate="Hour %{x:02d}:00<br>Mean hourly total: %{y:,.0f}<br>Median: %{customdata[0]:,.0f}<br>Days active: %{customdata[1]:.0f}%<extra></extra>"))
    fig = _base(fig, f"Average hourly total by clock hour - {measure}", "Hour of day", "Mean tickets per hour")
    fig.update_xaxes(dtick=1)
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def interval_profile_fig(prof: pd.DataFrame, measure: str) -> go.Figure:
    if not _ok(prof, "mean_observed"):
        return empty_figure()
    fig = go.Figure(go.Scatter(x=prof["time_label"], y=prof["mean_observed"], mode="lines", line=dict(color=MEASURE_COLORS.get(measure, C_REDEEM)),
                               customdata=prof["observed_share"] * 100,
                               hovertemplate="%{x}<br>Mean (observed intervals): %{y:,.1f}<br>Observed on %{customdata:.0f}% of days<extra></extra>"))
    fig = _base(fig, f"Mean count per 15-minute slot (observed intervals only) - {measure}", "Time of day", "Mean tickets per interval")
    fig.update_xaxes(nticks=24)
    return fig


def dow_fig(prof: pd.DataFrame, measure: str) -> go.Figure:
    if not _ok(prof, "mean_daily_total"):
        return empty_figure()
    fig = go.Figure(go.Bar(x=prof["day_name"], y=prof["mean_daily_total"], marker_color=MEASURE_COLORS.get(measure, C_REDEEM),
                           customdata=prof["days"], hovertemplate="%{x}<br>Mean daily total: %{y:,.0f}<br>%{customdata} days<extra></extra>"))
    fig = _base(fig, f"Mean daily total by day of week - {measure}", "", "Mean tickets per day")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def monthly_fig(prof: pd.DataFrame, measure: str) -> go.Figure:
    if not _ok(prof, "mean_daily_total"):
        return empty_figure()
    fig = go.Figure(go.Bar(x=prof["month_name"], y=prof["mean_daily_total"], marker_color=MEASURE_COLORS.get(measure, C_REDEEM),
                           customdata=np.c_[prof["days"], prof["total"]],
                           hovertemplate="%{x}<br>Mean daily total: %{y:,.0f}<br>%{customdata[0]} days, %{customdata[1]:,.0f} tickets<extra></extra>"))
    fig = _base(fig, f"Mean daily total by calendar month - {measure}", "", "Mean tickets per day")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def season_fig(si: pd.DataFrame) -> go.Figure:
    if not _ok(si, "index"):
        return empty_figure()
    fig = go.Figure(go.Bar(x=si["season"].astype(str), y=si["index"], marker_color=C_REDEEM,
                           customdata=np.c_[si["mean_daily_total"], si["days"]],
                           hovertemplate="%{x}<br>Index: %{y:.0f}<br>Mean daily total: %{customdata[0]:,.0f}<br>%{customdata[1]} days<extra></extra>"))
    fig.add_hline(y=100, line_dash="dash", line_color=C_NEUTRAL, annotation_text="Baseline = 100 (mean daily total of selection)")
    fig = _base(fig, "Seasonal Utilization Index", "", "Index (baseline 100)")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def weekday_weekend_fig(ww: pd.DataFrame, measure: str) -> go.Figure:
    if not _ok(ww, "mean_daily_total"):
        return empty_figure()
    fig = go.Figure(go.Bar(x=ww["day_type"], y=ww["mean_daily_total"], marker_color=[C_REDEEM, C_SALES][: len(ww)],
                           customdata=ww["days"], hovertemplate="%{x}<br>Mean daily total: %{y:,.0f}<br>%{customdata} days<extra></extra>"))
    fig = _base(fig, f"Weekday vs weekend - mean daily total ({measure})", "", "Mean tickets per day")
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def heatmap_fig(df: pd.DataFrame, measure: str) -> go.Figure:
    """Mean hourly total by weekday x hour."""
    if df.empty:
        return empty_figure()
    hourly = df.groupby(["date", "day_of_week", "hour"], as_index=False)[measure].sum()
    p = hourly.groupby(["day_of_week", "hour"])[measure].mean().unstack("hour").reindex(index=range(7), columns=range(24))
    fig = go.Figure(go.Heatmap(z=p.values, x=[f"{h:02d}" for h in p.columns], y=cfg.DAY_NAMES, colorscale="YlGnBu",
                               colorbar=dict(title="Mean / hour"), hovertemplate="%{y} %{x}:00<br>Mean hourly total: %{z:,.0f}<extra></extra>"))
    fig = _base(fig, f"Mean hourly total - weekday x hour ({measure})", "Hour of day", "", height=400)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(hovermode="closest")
    return fig


def rolling_fig(roll: pd.DataFrame, measure: str) -> go.Figure:
    if not _ok(roll, measure):
        return empty_figure()
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=roll["interval_start"], y=roll[measure], name="15-min interval", mode="lines",
                             line=dict(width=1, color="#b8c4d6")))
    pal = {"1-hour": C_REDEEM, "4-hour": C_PEAK}
    for c in [c for c in roll.columns if c.startswith("rolling_")]:
        lab = c.replace("rolling_", "")
        fig.add_trace(go.Scatter(x=roll["interval_start"], y=roll[c], name=f"{lab} rolling mean", mode="lines", line=dict(width=2, color=pal.get(lab))))
    fig = _base(fig, f"Rolling average demand - {measure}", y="Tickets per 15-min interval")
    fig.update_xaxes(rangeslider=dict(visible=True))
    return fig


def peak_offpeak_fig(prof: pd.DataFrame, measure: str, peak_hour: int | None, off_hour: int | None) -> go.Figure:
    return hourly_profile_fig(prof, measure, peak_hour, off_hour)


def sales_vs_redemption_fig(daily: pd.DataFrame) -> go.Figure:
    if not _ok(daily, cfg.COL_SALES, cfg.COL_REDEEM):
        return empty_figure("Sales data is not available in this dataset")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=daily["date"], y=daily[cfg.COL_SALES], name=cfg.COL_SALES, mode="lines", line=dict(width=1.3, color=C_SALES)))
    fig.add_trace(go.Scatter(x=daily["date"], y=daily[cfg.COL_REDEEM], name=cfg.COL_REDEEM, mode="lines", line=dict(width=1.3, color=C_REDEEM)))
    fig = _base(fig, "Daily ticket sales vs redemptions", y="Tickets per day")
    fig.update_xaxes(rangeslider=dict(visible=True))
    return fig


def sales_redemption_scatter(df: pd.DataFrame, sample: int = 20000) -> go.Figure:
    if not _ok(df, cfg.COL_SALES, cfg.COL_REDEEM):
        return empty_figure("Sales data is not available in this dataset")
    d = df.sample(min(sample, len(df)), random_state=0) if len(df) > sample else df
    fig = go.Figure(go.Scattergl(x=d[cfg.COL_SALES], y=d[cfg.COL_REDEEM], mode="markers", marker=dict(size=4, opacity=0.35, color=C_REDEEM),
                                 hovertemplate="Sales %{x:,}<br>Redemptions %{y:,}<extra></extra>"))
    fig = _base(fig, "Sales vs redemptions per 15-minute interval" + (f" (random sample of {sample:,})" if len(df) > sample else ""),
                "Sales Count", "Redemption Count")
    fig.update_layout(hovermode="closest")
    return fig


def difference_fig(diff: pd.DataFrame) -> go.Figure:
    if not _ok(diff, "sales_minus_redemptions"):
        return empty_figure("Sales data is not available in this dataset")
    fig = go.Figure(go.Bar(x=diff["date"], y=diff["sales_minus_redemptions"],
                           marker_color=np.where(diff["sales_minus_redemptions"] >= 0, C_SALES, C_REDEEM)))
    fig = _base(fig, "Daily ticket-count difference: sales minus redemptions (not passenger movement)", y="Tickets")
    return fig


def yoy_fig(yoy: pd.DataFrame) -> go.Figure:
    if not _ok(yoy, "yoy_pct"):
        return empty_figure("Not enough comparable months (need >=25 days of data in both years)")
    p = yoy.pivot(index="month", columns="year", values="yoy_pct").reindex(range(1, 13))
    fig = go.Figure(go.Heatmap(z=p.values, x=[str(c) for c in p.columns], y=cfg.MONTH_NAMES, colorscale="RdBu", zmid=0,
                               colorbar=dict(title="YoY %"), hovertemplate="%{y} %{x}<br>YoY change: %{z:.0f}%<extra></extra>"))
    fig = _base(fig, "Year-over-year change in mean daily total, by month", "Year", "", height=440)
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(hovermode="closest")
    return fig


def annual_fig(ann: pd.DataFrame, measure_cols: list[str]) -> go.Figure:
    if not _ok(ann, "year"):
        return empty_figure()
    fig = go.Figure()
    for m in measure_cols:
        if m in ann.columns:
            fig.add_trace(go.Bar(x=ann["year"].astype(str), y=ann[m], name=m, marker_color=MEASURE_COLORS.get(m)))
    fig = _base(fig, "Annual totals (partial years: 2015 starts 1 May, 2025 ends 21 Dec)", "", "Tickets")
    fig.update_layout(barmode="group")
    return fig


def absent_hour_fig(ab: pd.DataFrame) -> go.Figure:
    if not _ok(ab, "pct_days_with_activity"):
        return empty_figure()
    fig = go.Figure(go.Bar(x=ab["hour"], y=ab["pct_days_with_activity"], marker_color=C_NEUTRAL,
                           hovertemplate="Hour %{x:02d}:00<br>%{y:.1f}% of days have any recorded activity<extra></extra>"))
    fig = _base(fig, "Share of days with any recorded activity, by hour", "Hour of day", "% of days")
    fig.update_xaxes(dtick=1)
    fig.update_layout(hovermode="closest", showlegend=False)
    return fig


def outlier_fig(df: pd.DataFrame, measure: str) -> go.Figure:
    if df.empty:
        return empty_figure()
    n = df["is_outlier"].sum()
    base = df.loc[~df["is_outlier"]]
    base = base.sample(min(15000, len(base)), random_state=0)
    out = df.loc[df["is_outlier"]]
    fig = go.Figure()
    fig.add_trace(go.Scattergl(x=base[cfg.COL_TS], y=base[measure], mode="markers", name="Normal", marker=dict(size=3, color="#b8c4d6")))
    fig.add_trace(go.Scattergl(x=out[cfg.COL_TS], y=out[measure], mode="markers", name=f"Flagged outliers ({n:,})", marker=dict(size=6, color=C_PEAK),
                               customdata=out["outlier_score"], hovertemplate="%{x}<br>%{y:,}<br>Modified z: %{customdata:.1f}<extra></extra>"))
    fig = _base(fig, f"Outlier flags - {measure} (retained in the data)", y="Tickets per interval")
    fig.update_layout(hovermode="closest")
    return fig

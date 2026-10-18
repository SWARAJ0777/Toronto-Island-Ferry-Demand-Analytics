"""Integration tests: the real supplied dataset and headless Streamlit runs."""
from pathlib import Path

import pandas as pd
import pytest

import analytics as an
import config as cfg
import data_processing as dp
from conftest import make_raw

APP = str(cfg.BASE_DIR / "app.py")
REAL = cfg.DEFAULT_DATA_PATH
PAGES = ["Overview", "Demand analysis", "Rolling & sales vs redemption", "Data quality", "Data explorer", "Insights", "Definitions & limits"]

needs_real = pytest.mark.skipif(not Path(REAL).exists(), reason="supplied dataset not present in data/")


# ---- real dataset -----------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real():
    return dp.load_and_prepare(REAL)


@needs_real
def test_real_dataset_loads_and_matches_known_facts(real):
    df, rep = real
    assert rep.rows_raw == rep.rows_clean == 261538
    assert rep.has_sales and rep.has_id
    assert rep.first_timestamp.startswith("2015-05-01 13:30") and rep.last_timestamp.startswith("2025-12-21 22:30")
    assert df[cfg.COL_REDEEM].sum() == 12785293 and df[cfg.COL_SALES].sum() == 12972051
    assert rep.exact_duplicate_rows_dropped == 0 and rep.negative_values_dropped == 0
    assert rep.rows_with_both_zero == 0
    assert rep.missing_calendar_days == ["2015-05-02", "2015-05-03", "2018-01-04", "2021-02-21", "2021-02-22", "2025-01-26"]


@needs_real
def test_real_dataset_aggregations_conserve_totals(real):
    df, _ = real
    for lvl in ("hour", "day", "month", "year"):
        assert an.aggregate(df, lvl)[cfg.COL_REDEEM].sum() == df[cfg.COL_REDEEM].sum()
    assert an.compute_kpis(df, cfg.COL_REDEEM)["total"] == 12785293


@needs_real
def test_real_dataset_no_rows_in_spring_forward_hour(real):
    df, _ = real
    sf = df[df["dst_transition_day"] & (df["month"] == 3)]
    assert not (sf["hour"] == 2).any()


# ---- headless app runs ----------------------------------------------------------------------------
def _run_app(path=None, upload_pages=True):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(APP, default_timeout=240)
    at.run()
    return at


def _set_path(at, path):
    ti = [t for t in at.sidebar.text_input if t.label == "CSV path"][0]
    ti.set_value(str(path))
    return at.run()


def _page(at, name):
    r = [r for r in at.sidebar.radio if r.label == "Page"][0]
    r.set_value(name)
    return at.run()


@needs_real
def test_app_starts_and_every_page_renders_on_real_data():
    at = _run_app()
    assert not at.exception
    for p in PAGES:
        at = _page(at, p)
        assert not at.exception, f"{p}: {[e.value for e in at.exception]}"
        assert not at.error, f"{p}: {[e.value for e in at.error]}"


@needs_real
def test_app_filters_update_kpis():
    at = _run_app()
    before = [m.value for m in at.metric if m.label == "Records in selection"][0]
    dt = [r for r in at.sidebar.radio if r.label == "Weekday / weekend"][0]
    dt.set_value("Weekend")
    at = at.run()
    after = [m.value for m in at.metric if m.label == "Records in selection"][0]
    assert not at.exception and int(after.replace(",", "")) < int(before.replace(",", ""))


@needs_real
def test_app_empty_filter_selection_handled():
    at = _run_app()
    ms = [m for m in at.sidebar.multiselect if m.label == "Day of week"][0]
    ms.set_value([])
    at = at.run()
    assert not at.exception and any("No records match" in w.value for w in at.warning)


def test_app_missing_file_shows_friendly_error(tmp_path):
    at = _run_app()
    at = _set_path(at, tmp_path / "missing.csv")
    assert not at.exception and any("Could not load data" in e.value for e in at.error)


def test_app_unsupported_file_shows_friendly_error(tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("a,b\n1,2\n")
    at = _set_path(_run_app(), p)
    assert not at.exception and any("Unsupported file format" in e.value for e in at.error)


def test_app_missing_required_column_shows_friendly_error(tmp_path):
    p = tmp_path / "bad.csv"
    make_raw().drop(columns=["Redemption Count"]).to_csv(p, index=False)
    at = _set_path(_run_app(), p)
    assert not at.exception and any("Missing required column" in e.value for e in at.error)


def test_app_without_sales_column_degrades_gracefully(tmp_path):
    p = tmp_path / "nosales.csv"
    make_raw(periods=400, with_sales=False).to_csv(p, index=False)
    at = _set_path(_run_app(), p)
    assert not at.exception and not at.error
    assert any("Sales Count is not present" in i.value for i in at.info)
    for name in PAGES:
        at = _page(at, name)
        assert not at.exception, f"{name}: {[e.value for e in at.exception]}"


def test_app_minimal_dataset_all_pages(tmp_path):
    p = tmp_path / "tiny.csv"
    make_raw(periods=3).to_csv(p, index=False)
    at = _set_path(_run_app(), p)
    for name in PAGES:
        at = _page(at, name)
        assert not at.exception, f"{name}: {[e.value for e in at.exception]}"


def test_default_path_is_relative_not_machine_specific():
    assert Path(REAL).is_relative_to(cfg.BASE_DIR)          # default data path lives inside the project
    for module in ("config.py", "app.py", "data_processing.py", "analytics.py", "visualizations.py"):
        src = (cfg.BASE_DIR / module).read_text()
        assert "/home/" not in src and "C:\\" not in src, f"machine-specific path in {module}"

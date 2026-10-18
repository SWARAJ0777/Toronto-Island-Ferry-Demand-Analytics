# Toronto Island Ferry - Ticket Sales & Redemption Analytics

A Streamlit dashboard and reproducible analysis pipeline for 15-minute ferry ticket **sales** and **redemption** counts
(Toronto Island Park service from Jack Layton Ferry Terminal).

> **Historical analytics, not a live feed.** The supplied file ends on 2025-12-21 22:30. The dashboard never shows
> invented real-time values. To update it, replace the CSV and press **Reload file from disk** in the sidebar.
>
> **Counts are tickets, not passengers.** Sales and redemptions are not arrivals or departures, and their difference
> is not net passenger movement.

## Prerequisites

- Python 3.11 or newer (developed and tested on 3.13)
- pip

## Directory structure

```
ferry_analytics/
├── app.py                 Streamlit entry point (7 pages)
├── config.py              Paths, schema, seasons, outlier and rolling-window settings
├── data_processing.py     Loading, validation, cleaning, feature engineering, coverage
├── analytics.py           Filters, aggregation, KPIs, profiles, insights
├── visualizations.py      Plotly chart builders
├── requirements.txt       Dependencies (version ranges)
├── pytest.ini             Test configuration
├── .streamlit/config.toml Theme and server settings
├── data/                  Put "Toronto Island Ferry Tickets.csv" here
├── tests/                 Automated tests
└── reports/               PDFs (research paper, executive summary, data-quality, test report),
                           figures/, screenshots/, and the scripts that generate them
```

## Setup

```bash
cd ferry_analytics
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Dataset

Place the CSV at `data/Toronto Island Ferry Tickets.csv` (included in the delivered ZIP). Alternatives:

- Set another location with the environment variable `FERRY_DATA_PATH`, or type a path in the sidebar *Data source* box.
- Upload a CSV in the sidebar (overrides the path).

The project never substitutes sample data: if the file is missing, the app shows an error and stops.

### Schema

| Column | Required | Meaning |
|---|---|---|
| `Timestamp` | yes | ISO-like date-time of the 15-minute interval start (naive local time) |
| `Redemption Count` | yes | Tickets redeemed in the interval (non-negative integer) |
| `Sales Count` | no | Tickets sold in the interval. If absent, sales KPIs and charts show an "unavailable" state |
| `_id` | no | Row identifier (only checked for duplicates) |

Only `.csv` files are supported.

## Run

```bash
streamlit run app.py
```

Run it from inside the `ferry_analytics` directory. The app opens at http://localhost:8501.

## Test

```bash
python -m pytest
```

75 tests cover loading, timestamp parsing, duplicates, gaps, invalid values, aggregation, KPIs, rolling averages,
filters and boundaries, DST, empty/minimal/no-sales data, chart construction, CSV exports, and headless runs of every
dashboard page on the real dataset.

## Regenerate the reports (optional)

The PDFs in `reports/` are produced from the real data and a fresh test run, so every number in them is calculated, not typed.

```bash
pip install -r reports/requirements-reports.txt     # matplotlib, reportlab, pillow (+ playwright for screenshots)
python reports/build_reports.py
```

Screenshots need Playwright's Chromium (`playwright install chromium`); without it the build records the browser check as not completed.

## Deploy to Streamlit Community Cloud

1. Push this folder to a GitHub repository (the CSV is about 8 MB, so it can be committed; otherwise users upload it in the sidebar).
2. On https://share.streamlit.io choose **New app**, select the repository and branch, and set the main file to `app.py`
   (if the project sits in a sub-folder, enter that sub-folder path, e.g. `ferry_analytics/app.py`).
3. Under *Advanced settings* choose Python 3.11 or newer. Dependencies are read from `requirements.txt`.
4. No secrets or API keys are needed. Confirm you have the right to redistribute the data before publishing it in a public repository.

## Dashboard pages

1. **Overview** - date range, record count, latest record, headline KPIs, data-quality indicators, sales-vs-redemption summary.
2. **Demand analysis** - daily/monthly/hourly series, hourly and 15-minute profiles, weekday comparison, weekday vs weekend, weekday x hour heatmap, monthly, seasonal index, annual and year-over-year.
3. **Rolling & sales vs redemption** - 1-hour and 4-hour rolling means; sales/redemption comparison.
4. **Data quality** - coverage, absent intervals and gaps, cleaning effects, outliers.
5. **Data explorer** - filterable table and CSV downloads (intervals, hourly, daily, monthly, profiles).
6. **Insights** - computed findings; recommendations are labelled as hypotheses.
7. **Definitions & limits** - every KPI formula and interpretation.

Sidebar filters (date range, hours, weekday, weekend/weekday, year, month, measure, outlier exclusion) apply to every page except
the *whole-file* section of Data quality and the rolling-average window, which are labelled where they differ.

## Supported and unsupported

| Supported | Not supported (data does not allow it) |
|---|---|
| Sales and redemption KPIs, peak/off-peak, seasonal index, rolling means, YoY | Real-time ingestion |
| DST-day flagging, outlier flagging, coverage metrics | Passenger arrival/departure or net-flow estimates |
| CSV upload and path configuration | Per-route (Centre Island / Hanlan's / Ward's) analysis |
| Graceful handling of missing sales column | Capacity, queue or weather-based conclusions |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Data file not found` | Put the CSV in `data/`, set `FERRY_DATA_PATH`, or upload it in the sidebar |
| `Missing required column(s)` | The CSV needs at least `Timestamp` and `Redemption Count` (exact names) |
| `Unsupported file format` | Provide a `.csv` file |
| `ModuleNotFoundError` | Activate the virtual environment and run `pip install -r requirements.txt` |
| Imports fail in tests | Run `python -m pytest` from the `ferry_analytics` directory (`pytest.ini` sets the path) |
| Old numbers after replacing the CSV | Press **Reload file from disk**; the cache also keys on file modified time and size |
| Slow first load | The 260k-row file loads in about 2 seconds; results are cached afterwards |

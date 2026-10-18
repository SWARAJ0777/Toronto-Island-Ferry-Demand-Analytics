"""Application configuration for the Toronto Island ferry analytics project."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Dataset location. Override with the FERRY_DATA_PATH environment variable.
DEFAULT_DATA_PATH = Path(
    os.environ.get("FERRY_DATA_PATH", BASE_DIR / "data" / "Toronto Island Ferry Tickets.csv")
)
REPORTS_DIR = BASE_DIR / "reports"

# --- Schema -----------------------------------------------------------------
COL_ID = "_id"
COL_TS = "Timestamp"
COL_REDEEM = "Redemption Count"
COL_SALES = "Sales Count"
REQUIRED_COLUMNS = [COL_TS, COL_REDEEM]          # sales is optional
OPTIONAL_COLUMNS = [COL_ID, COL_SALES]
SUPPORTED_EXTENSIONS = {".csv"}

# --- Time handling ------------------------------------------------------------
# Source timestamps are timezone-naive. The data shows no rows inside the
# non-existent spring-forward hour and no repeated fall-back stamps, which is
# consistent with Toronto local wall-clock time. They are kept naive (never
# reinterpreted as UTC) and Toronto is used only for DST-day flagging.
LOCAL_TZ = "America/Toronto"
INTERVAL_MINUTES = 15
INTERVALS_PER_HOUR = 60 // INTERVAL_MINUTES
INTERVALS_PER_DAY = 24 * INTERVALS_PER_HOUR

# --- Seasons (meteorological, Northern Hemisphere) ---------------------------
SEASON_BY_MONTH = {
    12: "Winter", 1: "Winter", 2: "Winter",
    3: "Spring", 4: "Spring", 5: "Spring",
    6: "Summer", 7: "Summer", 8: "Summer",
    9: "Fall", 10: "Fall", 11: "Fall",
}
SEASON_ORDER = ["Winter", "Spring", "Summer", "Fall"]
DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# --- Outlier detection -------------------------------------------------------
# Modified z-score (Iglewicz & Hoaglin) on log1p(count) within (month, hour)
# groups. Flags are informational; nothing is removed.
OUTLIER_MODZ_THRESHOLD = 3.5
OUTLIER_MIN_GROUP_SIZE = 30
OUTLIER_MIN_COUNT = 100   # ignore flags on tiny counts, where relative spikes are trivial

# --- Rolling windows (in 15-minute intervals) ----------------------------------
ROLLING_WINDOWS = {"1-hour": 4, "4-hour": 16}

MAX_TABLE_ROWS = 5000   # rows rendered in the data explorer (exports are not capped)

import io
import numpy as np
import pandas as pd
import pytest


def make_raw(start="2024-07-01 08:00", periods=96, with_sales=True, seed=0):
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=periods, freq="15min")
    d = {"_id": range(1, periods + 1), "Timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
         "Redemption Count": rng.integers(1, 50, periods)}
    if with_sales:
        d["Sales Count"] = rng.integers(1, 50, periods)
    return pd.DataFrame(d)


@pytest.fixture
def raw():
    return make_raw()


@pytest.fixture
def csv_file(tmp_path, raw):
    p = tmp_path / "ferry.csv"
    raw.to_csv(p, index=False)
    return p


@pytest.fixture
def clean_df(raw):
    import data_processing as dp
    return dp.clean(raw)[0]

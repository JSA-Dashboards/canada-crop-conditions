"""Weekly satellite crop condition by province from NOAA STAR Vegetation Health (no Streamlit import).

StatCan's public weekly NDVI tables stopped (32-10-0453-01 at 2021-10, 32-10-0383-01 at 2024-05), so NOAA STAR is the
current free source: cropland pixels only, province averages, weekly from 1982 to the latest week.
  SMN = smoothed NDVI (greenness), SMT = smoothed brightness temperature (K), VCI = vegetation condition index (0-100),
  TCI = thermal condition index, VHI = vegetation health index (0.5 VCI + 0.5 TCI).
NOAA labels the product experimental. Weeks count in sevens from Jan 1 (week 42 is about Oct 15).
"""
import datetime
import re
from pathlib import Path

import numpy as np
import pandas as pd
import requests

URL = "https://www.star.nesdis.noaa.gov/smcd/emb/vci/VH/get_TS_admin.php"
DATA = Path(__file__).parent / "data" / "vh.csv"
PROVINCE_ID = {"Alberta": 1, "Manitoba": 3, "Ontario": 9, "Saskatchewan": 12}
COLS = ["SMN", "SMT", "VCI", "TCI", "VHI"]
LABEL = {"SMN": "NDVI (greenness)", "VCI": "VCI (vegetation condition)", "TCI": "TCI (thermal condition)",
         "VHI": "VHI (vegetation health)"}
FIRST_YEAR = 1982
# Windows fixed in advance on crop stage, never searched for the best fit:
# Prairie canola and cereals flowering to grain fill, Ontario soybean pod set and fill, corn silking and fill.
WINDOWS = {"Canola": (25, 31), "Spring wheat": (25, 31), "Durum": (25, 31), "Barley": (25, 31),
           "Soybeans": (29, 35), "Corn": (27, 35)}


def parse(text):
    rows = []
    for line in text.splitlines():
        m = re.match(r"^\s*(\d{4}),\s*(\d+),\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+)", line)
        if m and float(m.group(3)) > -0.5:  # -1 marks weeks that have not happened yet
            rows.append([int(m.group(1)), int(m.group(2))] + [float(m.group(i)) for i in range(3, 8)])
    return pd.DataFrame(rows, columns=["year", "week"] + COLS)


def fetch(province, timeout=30.0):
    """Live series for one province's cropland, 1982 to now. Raises on any failure."""
    params = {"provinceID": PROVINCE_ID[province], "country": "CAN", "adminVHversion": "GC_current",
              "yearlyTag": "weekly", "type": "Mean", "TagCropland": "crop", "year1": FIRST_YEAR,
              "year2": datetime.date.today().year}
    r = requests.get(URL, params=params, timeout=timeout, headers={"User-Agent": "jsa-canada-crop-conditions"})
    r.raise_for_status()
    df = parse(r.text)
    if df.empty or province not in r.text[:400]:
        raise RuntimeError(f"NOAA STAR returned no {province} series")
    return df


def build():
    """Refresh data/vh.csv for every province."""
    frames = []
    for p in PROVINCE_ID:
        df = fetch(p)
        df.insert(0, "province", p)
        frames.append(df)
        print(f"{p}: {len(df)} weeks, {df['year'].min()}-{df['year'].max()}")
    DATA.parent.mkdir(exist_ok=True)
    pd.concat(frames).round(3).to_csv(DATA, index=False)


def load(province):
    df = pd.read_csv(DATA)
    return df[df["province"] == province].drop(columns="province").reset_index(drop=True)


def week_start(year, week):
    return datetime.date(int(year), 1, 1) + datetime.timedelta(days=7 * (int(week) - 1))


def last_week(df):
    y = int(df["year"].max())
    return y, int(df[df["year"] == y]["week"].max())


def window_mean(df, year, window, col="SMN"):
    a, b = window
    s = df[(df["year"] == year) & df["week"].between(a, b)]
    return float(s[col].mean()) if len(s) == b - a + 1 else None


def matrix(df, col):
    """Weeks down, years across."""
    return df.pivot(index="week", columns="year", values=col)


def season_table(df, crop, year):
    """The crop window's mean for each index in `year` against every other year:
    one row per index with this year's value, the average of the others, rank (1 = best)."""
    win = WINDOWS[crop]
    rows = []
    for col in ("SMN", "VCI", "VHI", "TCI"):
        vals = {y: window_mean(df, y, win, col) for y in sorted(df["year"].unique())}
        vals = {y: v for y, v in vals.items() if v is not None}
        if year not in vals:
            continue
        others = [v for y, v in vals.items() if y != year]
        rows.append({"index": col, "this_year": vals[year], "average": float(np.mean(others)),
                     "rank": int(sum(v > vals[year] for v in others)) + 1, "of": len(vals),
                     "first": min(vals)})
    return pd.DataFrame(rows)


def peak(df, year):
    """(peak NDVI, week) between weeks 20 and 42 of `year`, or None."""
    s = df[(df["year"] == year) & df["week"].between(20, 42)]
    if s.empty:
        return None
    i = s["SMN"].idxmax()
    return float(s.loc[i, "SMN"]), int(s.loc[i, "week"])


def season_rank(df, crop, year, col="SMN"):
    """The crop window's mean against every other year: (value, average, rank with 1 = best, years compared)."""
    win = WINDOWS[crop]
    vals = {y: window_mean(df, y, win, col) for y in sorted(df["year"].unique())}
    vals = {y: v for y, v in vals.items() if v is not None}
    if year not in vals:
        return None
    others = [v for y, v in vals.items() if y != year]
    return vals[year], float(np.mean(others)), int(sum(v > vals[year] for v in others)) + 1, len(vals)


def yield_model(df, crop, yields, year, col="SMN"):
    """yield = a + b x (year - 2000) + c x (crop-window mean of `col`), fitted on completed years before `year`.
    Leave-one-out error is compared with the same trend without the satellite term: that is the honest measure of
    what the index adds."""
    win = WINDOWS[crop]
    yrs = [y for y in sorted(yields) if FIRST_YEAR <= y < year and window_mean(df, y, win, col) is not None]
    if len(yrs) < 8:
        return None
    x = np.array([window_mean(df, y, win, col) for y in yrs])
    y_ = np.array([yields[y] for y in yrs])
    t = np.array([y - 2000 for y in yrs], dtype=float)
    n = len(yrs)

    def fit(mask, with_x):
        a = np.c_[np.ones(mask.sum()), t[mask]]
        if with_x:
            a = np.c_[a, x[mask]]
        return np.linalg.lstsq(a, y_[mask], rcond=None)[0]

    e1, e0 = [], []
    for i in range(n):
        m = np.arange(n) != i
        b1, b0 = fit(m, True), fit(m, False)
        e1.append(y_[i] - (b1[0] + b1[1] * t[i] + b1[2] * x[i]))
        e0.append(y_[i] - (b0[0] + b0[1] * t[i]))
    full, base = fit(np.ones(n, bool), True), fit(np.ones(n, bool), False)
    x_now = window_mean(df, year, win, col)
    anomaly = y_ - (base[0] + base[1] * t)  # yield minus its linear trend, per past year
    out = {"n": n, "years": yrs, "window": win, "x_now": x_now, "x": x, "anomaly": anomaly,
           "rmse_loo": float(np.sqrt(np.mean(np.square(e1)))),
           "rmse_trend_loo": float(np.sqrt(np.mean(np.square(e0)))),
           "trend_year": float(base[0] + base[1] * (year - 2000)),
           "predicted": None if x_now is None else float(full[0] + full[1] * (year - 2000) + full[2] * x_now)}
    out["skill"] = 1 - out["rmse_loo"] / out["rmse_trend_loo"]
    return out


if __name__ == "__main__":
    build()

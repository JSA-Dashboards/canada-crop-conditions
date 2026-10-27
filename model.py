"""Data access and the condition-based yield model (pure functions, no Streamlit)."""
from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).parent / "data"

# app crop name -> label used in the Alberta / Manitoba report tables
AB_LABEL = {"Canola": "Canola", "Spring wheat": "Spring Wheat", "Durum": "Durum",
            "Barley": "Barley"}
MB_LABEL = {"Canola": "Canola", "Spring wheat": "Spring Wheat", "Barley": "Barley",
            "Durum": "Spring Wheat"}
CROPS = list(AB_LABEL)
# crops offered per province (Ontario has no weekly report, so corn and soybeans run on satellite data)
PROV_CROPS = {"Alberta": CROPS, "Saskatchewan": CROPS,
              "Manitoba": ["Canola", "Spring wheat", "Barley"], "Ontario": ["Corn", "Soybeans"]}
RATED = ("Alberta", "Saskatchewan")  # provinces with numeric good-to-excellent ratings
RATING_DOY = 209  # ~July 28: the report whose rating the yield model keys on
TREND_FROM = 1995
BU_PER_T = {"Canola": 44.092, "Spring wheat": 36.744, "Durum": 36.744, "Barley": 45.93}


def _reports(name):
    p = DATA / name
    if not p.exists():
        return pd.DataFrame(columns=["date", "kind", "crop", "region", "value"])
    df = pd.read_csv(p, parse_dates=["date"])
    df["year"] = df["date"].dt.year
    # overlay on a common leap year so day-of-year lines up across years
    df["season_date"] = df["date"].apply(lambda d: d.replace(year=2000) if not (
        d.month == 2 and d.day == 29) else d.replace(year=2000, day=28))
    return df


def ab_reports():
    return _reports("ab_reports.csv")


def mb_reports():
    return _reports("mb_reports.csv")


def sk_reports():
    return _reports("sk_reports.csv")


def province_reports(geo):
    """Report table that carries good-to-excellent ratings for a province."""
    return {"Alberta": ab_reports, "Saskatchewan": sk_reports}[geo]()


def yields():
    return pd.read_csv(DATA / "yields.csv")


STOCK_CROP = {"Canola": "Canola", "Spring wheat": "Wheat ex-durum", "Durum": "Durum",
              "Barley": "Barley", "Corn": "Corn", "Soybeans": "Soybeans"}


def farm_stocks(geo, crop):
    """Latest Dec 31, Mar 31 and Jul 31 farm stocks (kt) against a year earlier and the prior
    five-year average (StatCan 32-10-0007-01). Empty when the table has none."""
    p = DATA / "stocks.csv"
    if not p.exists():
        return pd.DataFrame()
    d = pd.read_csv(p)
    s = d[(d["geo"] == geo) & (d["crop"] == STOCK_CROP[crop])].set_index("date")["kt"]
    if s.empty:
        return pd.DataFrame()
    last = s.index.max()
    rows = []
    for mm, lab in (("12", "Dec 31"), ("03", "Mar 31"), ("07", "Jul 31")):
        ys = sorted(int(k[:4]) for k in s.index if k.endswith("-" + mm))
        ys = [y for y in ys if f"{y}-{mm}" <= last]
        if not ys:
            continue
        y = ys[-1]
        prev5 = [s[f"{yy}-{mm}"] for yy in range(y - 5, y) if f"{yy}-{mm}" in s.index]
        rows.append({"date": f"{lab} {y}", "kt": s[f"{y}-{mm}"], "year_ago": s.get(f"{y - 1}-{mm}"),
                     "avg5": sum(prev5) / len(prev5) if prev5 else np.nan})
    df = pd.DataFrame(rows)
    df["vs_year_ago"] = df["kt"] / df["year_ago"] - 1
    df["vs_avg5"] = df["kt"] / df["avg5"] - 1
    return df


def series(df, kind, crop, region):
    s = df[(df["kind"] == kind) & (df["crop"] == crop) & (df["region"] == region)]
    return s.sort_values("date")


def olympic_avg(values):
    """Mean after dropping the high and low (needs 3+ values)."""
    v = sorted(x for x in values if pd.notna(x))
    if len(v) < 3:
        return float(np.mean(v)) if v else np.nan
    return float(np.mean(v[1:-1]))


def rating_near(df, crop, region, year, doy=RATING_DOY, window=10):
    """Good-to-excellent rating from the report closest to day-of-year `doy`."""
    s = series(df, "rating", crop, region)
    s = s[s["year"] == year]
    if s.empty:
        return np.nan, None
    gap = (s["date"].dt.dayofyear - doy).abs()
    i = gap.idxmin()
    return (s.loc[i, "value"], s.loc[i, "date"]) if gap[i] <= window else (np.nan, None)


def trend_fit(y, first=TREND_FROM, last=None):
    """OLS yield-on-year trend. Returns (slope, intercept, years, yields)."""
    y = y.dropna(subset=["bu_ac"])
    y = y[(y["year"] >= first) & ((y["year"] <= last) if last else True)]
    slope, icpt = np.polyfit(y["year"], y["bu_ac"], 1)
    return slope, icpt, y["year"].to_numpy(), y["bu_ac"].to_numpy()


def build_model(crop, geo="Alberta", year=None):
    """Condition model: yield deviation from trend ~ late-July good-to-excellent rating.

    Fit on completed years that have both a rating and a final StatCan yield.
    Returns a dict (or None when there is not enough data).
    """
    ab = province_reports(geo)
    yl = yields()
    y = yl[(yl["geo"] == geo) & (yl["crop"] == crop)].copy()
    y["year"] = y["year"].astype(int)
    label = AB_LABEL[crop]  # same crop names in the Alberta and Saskatchewan tables
    year = year or int(ab["year"].max())
    # StatCan's current-year number is a model estimate until December: keep it out of the fit
    final = y[y["year"] < year]
    slope, icpt, _, _ = trend_fit(final)
    rows = []
    for yr in sorted(ab["year"].unique()):
        rating, rdate = rating_near(ab, label, geo, yr)
        act = final.loc[final["year"] == yr, "bu_ac"]
        trend = slope * yr + icpt
        rows.append({"year": yr, "rating": rating, "rating_date": rdate, "trend": trend,
                     "actual": act.iloc[0] if len(act) else np.nan})
    t = pd.DataFrame(rows)
    t["dev_pct"] = (t["actual"] / t["trend"] - 1) * 100
    fit = t.dropna(subset=["rating", "dev_pct"])
    cur = t[t["year"] == year].iloc[0]
    out = {"table": t, "year": year, "n": len(fit), "slope": slope,
           "trend_cur": cur["trend"], "rating_cur": cur["rating"],
           "statcan_cur": y.loc[y["year"] == year, "bu_ac"].max()}
    if len(fit) < 4 or np.isnan(cur["rating"]):
        return {**out, "b": np.nan, "a": np.nan, "r2": np.nan, "forecast": np.nan,
                "low": np.nan, "high": np.nan}
    b, a = np.polyfit(fit["rating"], fit["dev_pct"], 1)
    pred = a + b * fit["rating"]
    resid = fit["dev_pct"] - pred
    r2 = 1 - (resid ** 2).sum() / ((fit["dev_pct"] - fit["dev_pct"].mean()) ** 2).sum()
    se = float(np.sqrt((resid ** 2).sum() / max(len(fit) - 2, 1)))
    dev = a + b * cur["rating"]
    f = cur["trend"] * (1 + dev / 100)
    return {**out, "a": a, "b": b, "r2": r2, "se_pct": se, "dev_cur": dev, "forecast": f,
            "low": cur["trend"] * (1 + (dev - se) / 100),
            "high": cur["trend"] * (1 + (dev + se) / 100)}

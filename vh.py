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


MX_DATA = Path(__file__).parent / "data" / "vh_mx.csv"
# NOAA STAR's Mexican state ids (getProvinceNames.php?country_code=MEX)
MX_STATES = {1: "Aguascalientes", 2: "Baja California", 3: "Baja California Sur", 4: "Campeche",
             5: "Chiapas", 6: "Chihuahua", 7: "Coahuila", 8: "Colima", 9: "Ciudad de México",
             10: "Durango", 11: "Guanajuato", 12: "Guerrero", 13: "Hidalgo", 14: "Jalisco",
             15: "México", 16: "Michoacán", 17: "Morelos", 18: "Nayarit", 19: "Nuevo León",
             20: "Oaxaca", 21: "Puebla", 22: "Querétaro", 23: "Quintana Roo",
             24: "San Luis Potosí", 25: "Sinaloa", 26: "Sonora", 27: "Tabasco", 28: "Tamaulipas",
             29: "Tlaxcala", 30: "Veracruz", 31: "Yucatán", 32: "Zacatecas"}
# Windows fixed in advance on crop stage: autumn-winter crops (Sinaloa and Sonora irrigated corn
# and wheat, planted Nov-Jan) fill in Feb-Apr; spring-summer crops (rainfed corn, sorghum,
# soy, planted Jun-Jul) fill in Aug-Sep.
MX_WINDOWS = {"Otoño-Invierno": (6, 16), "Primavera-Verano": (29, 38)}


def fetch_mx(state_id, timeout=30.0):
    params = {"provinceID": state_id, "country": "MEX", "adminVHversion": "GC_current",
              "yearlyTag": "weekly", "type": "Mean", "TagCropland": "crop", "year1": FIRST_YEAR,
              "year2": datetime.date.today().year}
    r = requests.get(URL, params=params, timeout=timeout,
                     headers={"User-Agent": "jsa-canada-crop-conditions"})
    r.raise_for_status()
    df = parse(r.text)
    if df.empty or f"{state_id}: " not in r.text[:400]:
        raise RuntimeError(f"NOAA STAR returned no series for Mexican state {state_id}")
    return df


def build_mx():
    """Refresh data/vh_mx.csv: weekly cropland NDVI/VCI/TCI/VHI for all 32 Mexican states."""
    frames = []
    skipped = []
    for sid, name in MX_STATES.items():
        try:
            df = fetch_mx(sid)
        except RuntimeError:  # a state with no cropland pixels returns an empty series
            skipped.append(name)
            continue
        df.insert(0, "state", name)
        frames.append(df)
    out = pd.concat(frames).round(3)
    MX_DATA.parent.mkdir(exist_ok=True)
    out.to_csv(MX_DATA, index=False)
    print(f"vh_mx.csv: {len(out)} rows, {out['year'].min()}-{out['year'].max()}, "
          f"{len(frames)} states; no series for: {', '.join(skipped) or 'none'}")


FR_DATA = Path(__file__).parent / "data" / "vh_fr.csv"
# NOAA STAR's French regions are the PRE-2016 ones (getProvinceNames.php?country_code=FRA)
FR_REGIONS = {1: "Alsace", 2: "Aquitaine", 3: "Auvergne", 4: "Basse-Normandie", 5: "Bourgogne",
              6: "Bretagne", 7: "Centre", 8: "Champagne-Ardenne", 9: "Corse",
              10: "Franche-Comté", 11: "Haute-Normandie", 12: "Île-de-France",
              13: "Languedoc-Roussillon", 14: "Limousin", 15: "Lorraine", 16: "Midi-Pyrénées",
              17: "Nord-Pas-de-Calais", 18: "Pays de la Loire", 19: "Picardie",
              20: "Poitou-Charentes", 21: "Provence-Alpes-Côte d'Azur", 22: "Rhône-Alpes"}
# Windows fixed in advance on crop stage: winter wheat and barley stem extension to grain
# fill (about Apr-Jun), grain maize flowering to grain fill (about Jul-Sep).
FR_WINDOWS = {"Winter cereals": (14, 26), "Grain maize": (29, 37)}


def fetch_fr(region_id, timeout=30.0):
    params = {"provinceID": region_id, "country": "FRA", "adminVHversion": "GC_current",
              "yearlyTag": "weekly", "type": "Mean", "TagCropland": "crop", "year1": FIRST_YEAR,
              "year2": datetime.date.today().year}
    r = requests.get(URL, params=params, timeout=timeout,
                     headers={"User-Agent": "jsa-canada-crop-conditions"})
    r.raise_for_status()
    df = parse(r.text)
    if df.empty or f"{region_id}: " not in r.text[:400]:
        raise RuntimeError(f"NOAA STAR returned no series for French region {region_id}")
    return df


def build_fr():
    """Refresh data/vh_fr.csv: weekly cropland NDVI/VCI/TCI/VHI for the 22 pre-2016 regions."""
    frames, skipped = [], []
    for rid, name in FR_REGIONS.items():
        try:
            df = fetch_fr(rid)
        except RuntimeError:
            skipped.append(name)
            continue
        df.insert(0, "region", name)
        frames.append(df)
    out = pd.concat(frames).round(3)
    FR_DATA.parent.mkdir(exist_ok=True)
    out.to_csv(FR_DATA, index=False)
    print(f"vh_fr.csv: {len(out)} rows, {out['year'].min()}-{out['year'].max()}, {len(frames)} "
          f"regions; no series for: {', '.join(skipped) or 'none'}")


def load_fr(region):
    df = pd.read_csv(FR_DATA)
    return df[df["region"] == region].drop(columns="region").reset_index(drop=True)


# Current French region (Agreste SAA) -> the pre-2016 regions NOAA STAR reports
FR_REGION_MAP = {
    "Île-de-France": ["Île-de-France"], "Centre-Val de Loire": ["Centre"],
    "Bourgogne-Franche-Comté": ["Bourgogne", "Franche-Comté"],
    "Normandie": ["Basse-Normandie", "Haute-Normandie"],
    "Hauts de France": ["Nord-Pas-de-Calais", "Picardie"],
    "Grand Est": ["Alsace", "Champagne-Ardenne", "Lorraine"],
    "Pays de la Loire": ["Pays de la Loire"], "Bretagne": ["Bretagne"],
    "Nouvelle Aquitaine": ["Aquitaine", "Limousin", "Poitou-Charentes"],
    "Occitanie": ["Languedoc-Roussillon", "Midi-Pyrénées"],
    "Auvergne-Rhône-Alpes": ["Auvergne", "Rhône-Alpes"],
    "Provence-Alpes-Côte d'Azur": ["Provence-Alpes-Côte d'Azur"], "Corse": ["Corse"]}
# Windows fixed in advance by crop stage (rapeseed flowers and fills pods with the cereals' window)
FR_CROP_WINDOW = {"Soft wheat": (14, 26), "Durum": (14, 26), "Barley": (14, 26),
                  "Rapeseed": (14, 26), "Grain maize": (29, 37)}


def combine_fr(regions, weights=None):
    """Weighted mean of NOAA regions' weekly series (a current region is several old ones)."""
    allv = pd.read_csv(FR_DATA)
    sub = allv[allv["region"].isin(regions)].copy()
    w = pd.Series({r: (weights or {}).get(r, 1.0) for r in regions})
    sub["w"] = sub["region"].map(w)
    cols = [c for c in COLS]
    g = sub.groupby(["year", "week"])
    out = g.apply(lambda d: pd.Series({c: (d[c] * d["w"]).sum() / d["w"].sum() for c in cols}),
                  include_groups=False)
    return out.reset_index()


BR_DATA = Path(__file__).parent / "data" / "vh_br.csv"
# Brazilian state: UF -> (name, NOAA STAR provinceID); ids from getProvinceNames.php?country_code=BRA
BR_STATES = {"AC": ("Acre", 1), "AL": ("Alagoas", 2), "AP": ("Amapá", 3), "AM": ("Amazonas", 4),
             "BA": ("Bahia", 5), "CE": ("Ceará", 6), "DF": ("Distrito Federal", 7),
             "ES": ("Espírito Santo", 8), "GO": ("Goiás", 9), "MA": ("Maranhão", 10),
             "MT": ("Mato Grosso", 11), "MS": ("Mato Grosso do Sul", 12), "MG": ("Minas Gerais", 13),
             "PA": ("Pará", 14), "PB": ("Paraíba", 15), "PR": ("Paraná", 16), "PE": ("Pernambuco", 17),
             "PI": ("Piauí", 18), "RJ": ("Rio de Janeiro", 19), "RN": ("Rio Grande do Norte", 20),
             "RS": ("Rio Grande do Sul", 21), "RO": ("Rondônia", 22), "RR": ("Roraima", 23),
             "SC": ("Santa Catarina", 24), "SP": ("São Paulo", 25), "SE": ("Sergipe", 26),
             "TO": ("Tocantins", 27)}
# Windows fixed in advance by crop stage, in the calendar year the crop is harvested: soybeans
# and first-crop corn flower and fill grain in Dec-Feb (weeks 1-9 of the harvest year), second-crop
# corn (safrinha, sown Jan-Mar) in Mar-Jun, wheat (sown May-Jul, harvested Oct-Dec) in Aug-Oct.
BR_WINDOWS = {"Soybeans": (1, 9), "Corn 1st crop": (1, 9), "Corn 2nd crop": (12, 24), "Wheat": (31, 41)}


def fetch_br(state_id, timeout=30.0):
    params = {"provinceID": state_id, "country": "BRA", "adminVHversion": "GC_current",
              "yearlyTag": "weekly", "type": "Mean", "TagCropland": "crop", "year1": FIRST_YEAR,
              "year2": datetime.date.today().year}
    r = requests.get(URL, params=params, timeout=timeout,
                     headers={"User-Agent": "jsa-canada-crop-conditions"})
    r.raise_for_status()
    df = parse(r.text)
    if df.empty or f"{state_id}: " not in r.text[:400]:
        raise RuntimeError(f"NOAA STAR returned no series for Brazilian state {state_id}")
    return df


def build_br():
    """Refresh data/vh_br.csv: weekly cropland NDVI/VCI/TCI/VHI for the 27 Brazilian states."""
    frames, skipped = [], []
    for uf, (name, sid) in BR_STATES.items():
        try:
            df = fetch_br(sid)
        except RuntimeError:  # a state with no cropland pixels returns an empty series
            skipped.append(name)
            continue
        df.insert(0, "uf", uf)
        frames.append(df)
    out = pd.concat(frames).round(3)
    BR_DATA.parent.mkdir(exist_ok=True)
    out.to_csv(BR_DATA, index=False)
    print(f"vh_br.csv: {len(out)} rows, {out['year'].min()}-{out['year'].max()}, {len(frames)} "
          f"states; no series for: {', '.join(skipped) or 'none'}")


def load_br(uf):
    df = pd.read_csv(BR_DATA)
    return df[df["uf"] == uf].drop(columns="uf").reset_index(drop=True)


AR_DATA = Path(__file__).parent / "data" / "vh_ar.csv"
# Argentine province -> NOAA STAR provinceID (getProvinceNames.php?country_code=ARG)
AR_PROVINCES = {"Buenos Aires": 1, "Catamarca": 2, "Chaco": 3, "Chubut": 4, "Córdoba": 6,
                "Corrientes": 7, "Entre Ríos": 8, "Formosa": 9, "Jujuy": 10, "La Pampa": 11,
                "La Rioja": 12, "Mendoza": 13, "Misiones": 14, "Neuquén": 15, "Río Negro": 16,
                "Salta": 17, "San Juan": 18, "San Luis": 19, "Santa Cruz": 20, "Santa Fe": 21,
                "Santiago del Estero": 22, "Tierra del Fuego": 23, "Tucumán": 24}
# Windows fixed in advance by crop stage: (first week, last week, years after the campaign's first
# calendar year). Soybeans (sown Oct-Dec) fill pods Jan-Mar, corn (sown Sep-Dec) flowers and fills
# grain Dec-Mar, sunflower (sown Sep-Oct) fills Jan-Feb, sorghum (sown Nov-Dec) Feb-Mar; wheat
# (sown May-Jul, harvested Dec-Jan) flowers and fills grain in Sep-Oct of the first calendar year.
AR_WINDOWS = {"Soybeans": (2, 10, 1), "Corn": (1, 12, 1), "Sunflower": (1, 8, 1),
              "Sorghum": (4, 14, 1), "Wheat": (36, 44, 0)}


def fetch_ar(province_id, timeout=30.0):
    params = {"provinceID": province_id, "country": "ARG", "adminVHversion": "GC_current",
              "yearlyTag": "weekly", "type": "Mean", "TagCropland": "crop", "year1": FIRST_YEAR,
              "year2": datetime.date.today().year}
    r = requests.get(URL, params=params, timeout=timeout,
                     headers={"User-Agent": "jsa-canada-crop-conditions"})
    r.raise_for_status()
    df = parse(r.text)
    if df.empty or f"{province_id}: " not in r.text[:400]:
        raise RuntimeError(f"NOAA STAR returned no series for Argentine province {province_id}")
    return df


def build_ar():
    """Refresh data/vh_ar.csv: weekly cropland NDVI/VCI/TCI/VHI for the Argentine provinces."""
    frames, skipped = [], []
    for name, pid in AR_PROVINCES.items():
        try:
            df = fetch_ar(pid)
        except RuntimeError:  # a province with no cropland pixels returns an empty series
            skipped.append(name)
            continue
        df.insert(0, "province", name)
        frames.append(df)
    out = pd.concat(frames).round(3)
    AR_DATA.parent.mkdir(exist_ok=True)
    out.to_csv(AR_DATA, index=False)
    print(f"vh_ar.csv: {len(out)} rows, {out['year'].min()}-{out['year'].max()}, {len(frames)} "
          f"provinces; no series for: {', '.join(skipped) or 'none'}")


def load_ar(province):
    df = pd.read_csv(AR_DATA)
    return df[df["province"] == province].drop(columns="province").reset_index(drop=True)


def load_mx(state):
    df = pd.read_csv(MX_DATA)
    return df[df["state"] == state].drop(columns="state").reset_index(drop=True)


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


def season_table(df, crop, year, win=None):
    """The crop window's mean for each index in `year` against every other year:
    one row per index with this year's value, the average of the others, rank (1 = best)."""
    win = win or WINDOWS[crop]
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


def peak(df, year, lo=20, hi=42):
    """(peak NDVI, week) between weeks `lo` and `hi` of `year`, or None."""
    s = df[(df["year"] == year) & df["week"].between(lo, hi)]
    if s.empty:
        return None
    i = s["SMN"].idxmax()
    return float(s.loc[i, "SMN"]), int(s.loc[i, "week"])


def season_rank(df, crop, year, col="SMN", win=None):
    """The crop window's mean against every other year: (value, average, rank with 1 = best, years compared)."""
    win = win or WINDOWS[crop]
    vals = {y: window_mean(df, y, win, col) for y in sorted(df["year"].unique())}
    vals = {y: v for y, v in vals.items() if v is not None}
    if year not in vals:
        return None
    others = [v for y, v in vals.items() if y != year]
    return vals[year], float(np.mean(others)), int(sum(v > vals[year] for v in others)) + 1, len(vals)


def yield_model(df, crop, yields, year, col="SMN", win=None):
    """yield = a + b x (year - 2000) + c x (crop-window mean of `col`), fitted on completed years before `year`.
    Leave-one-out error is compared with the same trend without the satellite term: that is the honest measure of
    what the index adds."""
    win = win or WINDOWS[crop]
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

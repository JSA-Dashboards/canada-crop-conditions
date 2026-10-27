"""Great Ontario Yield Tour (Farms.com Risk Management) against StatCan, Ontario only (no Streamlit import).

The tour publishes a provincial yield forecast in late August. The history below is typed in from the
results pages (riskmanagement.farms.com/events/ontario-yield-tour-YYYY/tour-results); it does not update
itself, so add each new year by hand.
"""
import numpy as np
import pandas as pd

# year: (corn bu/ac, soybean bu/ac)
TOUR = {2016: (149.0, 43.0), 2017: (163.2, 45.7), 2018: (179.5, 50.2), 2019: (173.2, 43.6),
        2020: (183.3, 53.2), 2021: (191.5, 51.7), 2022: (186.6, 50.3), 2023: (203.0, 53.5),
        2024: (194.75, 54.12), 2025: (178.93, 46.61), 2026: (206.0, 55.0)}
SOURCE = ("Great Ontario Yield Tour results pages, riskmanagement.farms.com "
          "(provincial estimate announced in August)")
COLUMN = {"Corn": 0, "Soybeans": 1}


def available(crop):
    return crop in COLUMN


def table(crop, statcan, current_year):
    """Tour forecast against StatCan's yield for each year (the current year is StatCan's
    model estimate, not a final figure). `statcan` is {year: bu/ac}."""
    i = COLUMN[crop]
    rows = [{"year": y, "tour": v[i], "statcan": statcan[y], "ratio": statcan[y] / v[i],
             "final": y < current_year}
            for y, v in sorted(TOUR.items()) if y in statcan]
    return pd.DataFrame(rows)


def factor(tbl):
    """Median StatCan-to-tour yield ratio over finalised years: the tour's bias."""
    return float(tbl[tbl["final"]]["ratio"].median())


def miss(tbl):
    """Typical miss (mean absolute error) after scaling the tour by its median ratio."""
    fin = tbl[tbl["final"]]
    return float((fin["ratio"] / factor(tbl) - 1).abs().mean())


def estimates(tbl, crop, statcan_prod_t, year):
    """StatCan's model against the tour, as published and calibrated: [{label, yield_bu, kt}].
    Production is scaled from StatCan's own figure so no bushel weights are needed."""
    row = tbl[tbl["year"] == year]
    if row.empty:
        return []
    sc_yield = float(row["statcan"].iloc[0])
    raw = float(row["tour"].iloc[0])
    f = factor(tbl)
    out = [{"label": "StatCan model-based estimate", "yield_bu": sc_yield, "kt": statcan_prod_t / 1000.0}]
    for label, y in ((f"Yield tour, calibrated (x{f:.2f})", raw * f), ("Yield tour, as published", raw)):
        out.append({"label": label, "yield_bu": y, "kt": statcan_prod_t / 1000.0 * y / sc_yield})
    return out

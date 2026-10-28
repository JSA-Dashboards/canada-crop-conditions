"""Balance Sheet tab: USDA PSD supply-and-demand history for the selected crop, laid out like the
WASDE dashboard's Balance Sheet (same engine: balance_sheet.py, psd_meta.py)."""
from pathlib import Path

import pandas as pd
import streamlit as st

import balance_sheet as bs
import psd_meta as pm

DATA = Path(__file__).parent / "data" / "psd_history.csv"
COUNTRY = {"Canada": ("CA", "Canada"), "Mexico": ("MX", "Mexico"),
           "France": ("E4", "European Union"), "Brazil": ("BR", "Brazil"),
           "Argentina": ("AR", "Argentina"), "South Africa": ("SF", "South Africa")}
# the view's own crop key -> PSD commodity
CROP_PSD = {
    "Canada": {"Canola": "Canola (Rapeseed)", "Spring wheat": "Wheat", "Durum": "Wheat",
               "Barley": "Barley", "Corn": "Corn", "Soybeans": "Soybeans"},
    "Mexico": {"Maíz grano": "Corn", "Sorgo grano": "Sorghum", "Trigo grano": "Wheat",
               "Soya": "Soybeans", "Cebada grano": "Barley"},
    "France": {"Soft wheat": "Wheat", "Winter barley": "Barley", "Grain maize": "Corn"},
    "Brazil": {"Soybeans": "Soybeans", "Corn 1st crop": "Corn", "Corn 2nd crop": "Corn", "Wheat": "Wheat"},
    "Argentina": {"Soybeans": "Soybeans", "Corn": "Corn", "Sunflower": "Sunflowerseed",
                  "Sorghum": "Sorghum", "Wheat": "Wheat"},
    "South Africa": {"Maize": "Corn", "Soybeans": "Soybeans", "Sunflower": "Sunflowerseed",
                     "Sorghum": "Sorghum", "Wheat": "Wheat"},
}
NOTES = {
    ("Canada", "Durum"): "USDA does not split durum out of wheat, so this is all Canadian wheat.",
    ("Canada", "Spring wheat"): "USDA does not split spring wheat out of wheat, so this is all Canadian wheat.",
    ("France", "Soft wheat"): "USDA does not publish France on its own: this is the European Union, "
                              "and it is all wheat.",
    ("Brazil", "Corn 1st crop"): "USDA reports one Brazilian corn crop: this is both crops combined.",
    ("Brazil", "Corn 2nd crop"): "USDA reports one Brazilian corn crop: this is both crops combined.",
}
COLORS = {"border": "#d7e2dc", "text": "#32373c", "muted": "#5f7267", "green": "#5e7164",
          "dark": "#3f4f44", "good": "#1f7a3d", "bad": "#dc2626"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


@st.cache_data(ttl=3600, show_spinner=False)
def _history():
    if not DATA.exists():
        return pd.DataFrame()
    return pd.read_csv(DATA, dtype={"commodity_code": str})


def mkt(y):
    return f"{y}/{str(y + 1)[-2:]}"


@st.fragment
def balance_tab(country, crop, crop_label=None):
    label = crop_label or crop
    code, region = COUNTRY[country]
    commodity = CROP_PSD[country].get(crop)
    st.subheader(f"{region} Balance Sheet")
    if commodity is None:
        st.info(f"USDA does not publish a supply and demand balance sheet for {label.lower()}.")
        return
    h = _history()
    d = h[(h["commodity_code"] == pm.COMMODITIES[commodity]) & (h["country_code"] == code)] if len(h) else h
    if d is None or d.empty:
        st.info("No USDA balance sheet loaded yet. Run build_data.py psd (needs FAS_API_KEY).")
        return
    if (country, crop) in NOTES:
        st.caption(NOTES[(country, crop)])
    N = bs.derive(bs.basics(d))
    latest = int(N.index.max())
    first = int(N.index.min())
    c1, c2 = st.columns([3, 2])
    with c1:
        view_label = st.segmented_control("Show", ["Current", "Δ LY", "Δ 5YA"], default="Current",
                                          key=f"bs_view_{country}_{commodity}") or "Current"
    with c2:
        system = (st.segmented_control("Units", ["Imperial", "Metric"], default="Imperial",
                                       key=f"bs_units_{country}_{commodity}") or "Imperial").lower()
    lo_default = max(first, 2000)
    b0, e0 = st.select_slider("Marketing years", options=list(range(first, latest + 1)),
                              value=(lo_default, latest), format_func=mkt,
                              key=f"bs_years_{country}_{commodity}")
    view = bs.VIEWS[view_label]
    years = [y for y in range(b0, e0 + 1) if y in N.index]
    keys = bs.visible_keys(N, years, commodity)
    V = bs.make_view(N, view)
    D = bs.to_display(V, commodity, system, keys)
    labels = pm.unit_labels(commodity, system)
    title = (f"{region} {commodity}: Supply & Demand Balance Sheet",
             f"Units: {labels['qty']} · area {labels['area']} · yield {labels['yield']} · "
             f"{mkt(b0)} – {mkt(e0)}{'' if view == 'current' else ' · ' + view_label}")
    st.markdown(bs.render_html(D, years, keys, commodity, system, view, latest, COLORS, title=title),
                unsafe_allow_html=True)
    as_of = int(d["as_of"].max())
    when = f", updated {MONTHS[as_of % 100 - 1]} {as_of // 100}" if as_of else ""
    st.caption(f"Source: USDA FAS Production, Supply and Distribution (PSD){when}. The shaded column is "
               "the current marketing year. Δ LY is the change from the prior year (Stocks-to-Use in "
               "percentage points); Δ 5YA is the change from the average of the five years before it.")
    st.download_button("Download CSV", bs.to_csv(D, years, keys, commodity, system),
                       file_name=f"{region}_{commodity}_balance_sheet.csv".replace(" ", "_"),
                       mime="text/csv", key=f"bs_dl_{country}_{commodity}")

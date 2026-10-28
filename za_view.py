"""South Africa view: NOAA satellite by province, CEC forecasts, and a yield model."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import balance
import production
import vh
from charts import AMBER, BLUE, GREY, vh_chart

DATA = Path(__file__).parent / "data"
CROPS = ["Maize", "Soybeans", "Sunflower", "Sorghum", "Wheat"]
NATIONAL = {"Maize": "Maize commercial", "Soybeans": "Soybeans", "Sunflower": "Sunflower",
            "Sorghum": "Sorghum", "Wheat": "Wheat"}
ALL = "South Africa (national)"
WEIGHT_PROV = {"Free State": "Free State"}


@st.cache_data(ttl=3600)
def _csv(name):
    p = DATA / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def _vh(province):
    return vh.load_za(province)


def _finals(crop):
    """Province final crop by harvest year (area ha, production t, yield t/ha) from the CEC
    releases: each release carries the previous season's final figures."""
    r = _csv("za_cec_records.csv")
    f = r[(r["crop"] == crop) & r["prod_prev"].notna() & (r["province"] != "Total")].copy()
    f["fy"] = f["year"] - 1
    f = f.sort_values("release").drop_duplicates(["fy", "province"], keep="last")
    f = f.rename(columns={"area_prev": "area_ha", "prod_prev": "prod_t"})
    f["yield_tha"] = f["prod_t"] / f["area_ha"]
    return f[["fy", "province", "area_ha", "prod_t", "yield_tha"]]


def _latest_forecast(crop):
    """Newest release's current-season province table for `crop`."""
    r = _csv("za_cec_records.csv")
    c = r[(r["crop"] == crop) & r["prod_cur"].notna()]
    if c.empty:
        return pd.DataFrame(), None
    last = c["release"].max()
    t = c[c["release"] == last]
    return t, last


def _combine(provinces, weights):
    frames = []
    for p in provinces:
        d = _vh(p).copy()
        d["w"] = weights.get(p, 1.0)
        frames.append(d)
    allv = pd.concat(frames)
    cols = vh.COLS
    g = allv.groupby(["year", "week"])
    out = g.apply(lambda d: pd.Series({c: (d[c] * d["w"]).sum() / d["w"].sum() for c in cols}),
                  include_groups=False)
    return out.reset_index()


@st.cache_data(ttl=3600)
def _ndvi(area, crop):
    if area == ALL:
        f = _finals(crop)
        w = f.groupby("province")["area_ha"].mean().to_dict()
        return _combine(list(w), w)
    return _vh(area)


def render():
    st.title("South Africa crop conditions and yields")
    st.caption("NOAA STAR satellite crop condition by province, the Crop Estimates Committee's (CEC) "
               "forecasts, and a yield model. South Africa publishes no weekly progress or condition "
               "ratings; the CEC forecasts monthly.")
    with st.sidebar:
        crop = st.selectbox("Crop", CROPS, key="za_crop")
        provs = [ALL] + list(vh.ZA_PROVINCES)
        area = st.selectbox("Area", provs, key="za_area")
        st.caption("Summer crops (maize, soybeans, sunflower, sorghum) are sown Oct to Dec and "
                   "harvested Apr to Jul; the CEC labels a season by its harvest year (2025/26 = 2026). "
                   "Wheat is winter-sown and labelled by its calendar year.")
    t1, t2, t3, t5, t6, t4 = st.tabs(["CEC Forecasts", "Satellite", "Yield Model",
                                      "Areas and Calendar", "Balance Sheet", "Sources"])
    with t5:
        production.areas_tab("South Africa", crop)
    with t6:
        balance.balance_tab("South Africa", crop)
    with t1:
        _forecasts(crop)
    with t2:
        _satellite(crop, area)
    with t3:
        _model(crop, area)
    with t4:
        st.markdown("""
**CEC forecasts** - Crop Estimates Committee releases on SAGIS (sagis.org.za, Crop Estimates
Committee page): province area planted, the current forecast and the previous season's final crop,
monthly from the first forecast (Jan-Feb) to the final one (Oct-Nov), parsed from the PDFs. Province
sums were checked against each release's Total row and the SAGIS national series: they match for
every season 2014-2025 except 2017, for which no release with province tables is online.

**Satellite** - NOAA STAR Vegetation Health, province average of cropland pixels, weekly from 1982,
labelled experimental. Windows are fixed in advance in the harvest year: maize weeks 3-14,
soybeans 5-15, sunflower 4-13, sorghum 5-15, wheat 36-44 (its calendar year). A province average
mixes crops, so read it as a regional greenness signal.

**Yield model** - the year trend with and without the mean NDVI over the window; skill is the cut in
leave-one-out error. Province models have only 11 completed seasons (the CEC province history
online starts with 2014), so treat them as indicative; the national model uses the SAGIS series
(commercial crop, back to 1920, fitted from 1982) with an area-weighted province NDVI. The current
season is a forecast, shown against the CEC's own latest figure.

Refresh with `python build_data.py zacec` (releases), `zanat` (national history) and `zavh`.
""")


def _forecasts(crop):
    t, last = _latest_forecast(crop)
    if t.empty:
        st.info("No CEC data for this crop. Run build_data.py zacec.")
        return
    yr = int(t["year"].iloc[0])
    st.subheader(f"{crop}: CEC forecast for {yr}, release of {last}")
    tot = t[t["province"] == "Total"]
    prov = t[t["province"] != "Total"].copy()
    if len(tot):
        a, p = float(tot["area_cur"].iloc[0]), float(tot["prod_cur"].iloc[0])
        pa, pp = float(tot["area_prev"].iloc[0]), float(tot["prod_prev"].iloc[0])
        c = st.columns(4)
        c[0].metric("Area planted", f"{a / 1e6:.2f} M ha", f"{a / pa - 1:+.1%} vs last year")
        c[1].metric("Forecast production", f"{p / 1e6:.2f} Mt", f"{p / pp - 1:+.1%} vs last year final")
        c[2].metric("Forecast yield", f"{p / a:.2f} t/ha", f"{(p / a) / (pp / pa) - 1:+.1%} vs last year")
        c[3].metric("Last year final", f"{pp / 1e6:.2f} Mt")
    prov["Yield (t/ha)"] = prov["prod_cur"] / prov["area_cur"]
    prov["Last year (t/ha)"] = prov["prod_prev"] / prov["area_prev"]
    prov["Share of production"] = prov["prod_cur"] / prov["prod_cur"].sum()
    show = prov.sort_values("prod_cur", ascending=False)[
        ["province", "area_cur", "prod_cur", "Yield (t/ha)", "area_prev", "prod_prev",
         "Last year (t/ha)", "Share of production"]].rename(columns={
            "province": "Province", "area_cur": f"Area {yr} (ha)", "prod_cur": f"Forecast {yr} (t)",
            "area_prev": f"Area {yr - 1} (ha)", "prod_prev": f"Final {yr - 1} (t)"})
    fmt = {c: "{:,.0f}" for c in show.columns if "(ha)" in c or "(t)" in c}
    fmt |= {"Yield (t/ha)": "{:.2f}", "Last year (t/ha)": "{:.2f}", "Share of production": "{:.0%}"}
    st.dataframe(show.style.format(fmt, na_rep="n/a"), width="stretch", hide_index=True)
    r = _csv("za_cec_records.csv")
    path = r[(r["crop"] == crop) & (r["province"] == "Total") & (r["year"] == yr)
             & r["prod_cur"].notna()].sort_values("release")
    if len(path) > 1:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=path["release"], y=path["prod_cur"] / 1e6, mode="lines+markers",
                                 name=f"{yr} forecast", line=dict(color=BLUE, width=3)))
        fig.add_hline(y=float(path["prod_prev"].iloc[-1]) / 1e6, line_dash="dash", line_color=AMBER,
                      annotation_text=f"{yr - 1} final")
        fig.update_layout(title=f"{crop}: how the CEC forecast for {yr} has moved", height=340,
                          template="plotly_white", yaxis_title="Mt", margin=dict(t=50, b=30))
        st.plotly_chart(fig, width="stretch")
    fin = _finals(crop)
    if len(fin):
        nat = fin.groupby("fy")[["area_ha", "prod_t"]].sum()
        nat["yield"] = nat["prod_t"] / nat["area_ha"]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=nat.index, y=nat["prod_t"] / 1e6, name="Final production (Mt)",
                             marker_color=BLUE, opacity=0.75))
        fig.add_trace(go.Scatter(x=nat.index, y=nat["yield"], yaxis="y2", name="Yield (t/ha)",
                                 line=dict(color=AMBER, width=3)))
        fig.update_layout(title=f"{crop}: final crops in the CEC releases", height=320,
                          template="plotly_white", yaxis=dict(title="Mt"),
                          yaxis2=dict(title="t/ha", overlaying="y", side="right", showgrid=False),
                          margin=dict(t=50, b=30), legend=dict(orientation="h", y=-0.2))
        st.plotly_chart(fig, width="stretch")


def _satellite(crop, area):
    df = _ndvi(area, crop)
    a, b = vh.ZA_WINDOWS[crop]
    ly, lw = vh.last_week(df)
    who = "area-weighted national" if area == ALL else area
    st.caption(f"NOAA STAR Vegetation Health, {who} cropland, through week {lw} of {ly} "
               f"(about {vh.week_start(ly, lw):%b %d}).")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="za_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, _ = vh_chart(df, col, ly, span=(1, 52))
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, a)),
                  x1=pd.Timestamp(vh.week_start(2001, b + 1)), fillcolor=BLUE, opacity=0.08,
                  line_width=0, annotation_text=f"{crop} window")
    fig.update_layout(title=f"{area} cropland, weekly {vh.LABEL[col]}", height=400,
                      template="plotly_white", margin=dict(t=50, b=30), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b %d")
    st.plotly_chart(fig, width="stretch")
    year = ly if vh.window_mean(df, ly, (a, b)) is not None else ly - 1
    season = vh.season_table(df, None, year, win=(a, b))
    if season.empty:
        return
    st.markdown(f"**{crop} window: weeks {a} to {b} (about {vh.week_start(year, a):%b %d} to "
                f"{pd.Timestamp(vh.week_start(year, b)) + pd.Timedelta(days=6):%b %d}), {year}**")

    def f(c, v):
        return f"{v:.3f}" if c == "SMN" else f"{v:.1f}"
    st.dataframe(pd.DataFrame({
        "Index": [vh.LABEL[c] for c in season["index"]],
        str(year): [f(c, v) for c, v in zip(season["index"], season["this_year"])],
        "Average": [f(c, v) for c, v in zip(season["index"], season["average"])],
        "Rank (1 = best)": [f"{r} of {n}" for r, n in zip(season["rank"], season["of"])]}),
        width="stretch", hide_index=True)
    pk = vh.peak(df, year, 1, 52)
    if pk:
        st.caption(f"Peak NDVI in {year} (any week): {pk[0]:.3f} in week {pk[1]}. Rank compares the "
                   f"same window in every year since {int(season['first'].iloc[0])}.")


def _history(crop, area):
    """({harvest year: t/ha}, source note)."""
    if area == ALL:
        n = _csv("za_national.csv")
        s = n[(n["crop"] == NATIONAL[crop])]
        return {int(y): float(v) for y, v in zip(s["year"], s["yield_tha"])}, \
            "SAGIS national commercial series"
    f = _finals(crop)
    s = f[f["province"] == area]
    return {int(y): float(v) for y, v in zip(s["fy"], s["yield_tha"])}, "CEC province finals"


def _fit(crop, area):
    hist, src = _history(crop, area)
    win = vh.ZA_WINDOWS[crop]
    if len(hist) < 8:
        return None, hist, src, None
    df = _ndvi(area, crop)
    ly = int(df["year"].max())
    target = ly if vh.window_mean(df, ly, win) is not None else ly - 1
    done = {k: v for k, v in hist.items() if k < target}
    m = vh.yield_model(df, None, done, target, win=win) if len(done) >= 8 else None
    return m, hist, src, target


def _cec_yield(crop, area, target):
    """The CEC's own latest estimate (t/ha) for the target year, for comparison."""
    r = _csv("za_cec_records.csv")
    c = r[(r["crop"] == crop) & (r["year"] == target) & r["prod_cur"].notna()
          & (r["province"] == ("Total" if area == ALL else area))]
    if c.empty:
        return None, None
    last = c.sort_values("release").iloc[-1]
    return float(last["prod_cur"] / last["area_cur"]), last["release"]


@st.cache_data(ttl=3600)
def _scan(crop):
    f = _finals(crop)
    rows = []
    for prov in vh.ZA_PROVINCES:
        s = f[f["province"] == prov]
        if len(s) < 8:
            continue
        m, hist, _, target = _fit(crop, prov)
        if m and m["predicted"] is not None:
            cy, _ = _cec_yield(crop, prov, target)
            rows.append({"Province": prov, "Mean area (kha)": s["area_ha"].mean() / 1000,
                         "Trend (t/ha)": m["trend_year"], "Trend + NDVI (t/ha)": m["predicted"],
                         "CEC forecast (t/ha)": cy if cy else np.nan,
                         "Skill vs trend": m["skill"], "n": m["n"]})
    return pd.DataFrame(rows).sort_values("Mean area (kha)", ascending=False) if rows else pd.DataFrame()


def _model(crop, area):
    if _csv("za_cec_records.csv").empty:
        st.info("No CEC data. Run build_data.py zacec.")
        return
    m, hist, src, target = _fit(crop, area)
    win = vh.ZA_WINDOWS[crop]
    st.subheader(f"{area} {crop.lower()}: trend vs trend plus greenness")
    if not m or m["predicted"] is None:
        st.info(f"{area} has too little {crop.lower()} history for a model "
                f"({len(hist)} seasons; at least 8 are needed).")
        return
    cy, cdate = _cec_yield(crop, area, target)
    last = max(k for k in hist if k < target)
    c = st.columns(4)
    c[0].metric(f"Trend, {target}", f"{m['trend_year']:.2f} t/ha")
    c[1].metric(f"Trend + NDVI, {target}", f"{m['predicted']:.2f} t/ha",
                f"{m['predicted'] / m['trend_year'] - 1:+.0%} vs trend", delta_color="off")
    c[2].metric(f"CEC forecast, {target}", f"{cy:.2f} t/ha" if cy else "n/a",
                f"release {cdate}" if cdate else None, delta_color="off")
    c[3].metric("Skill vs trend (leave-one-out)", f"{m['skill'] * 100:+.0f}%")
    if m["skill"] <= 0.03:
        st.warning("For this area and crop the satellite reading adds nothing measurable to the "
                   "yield trend: the leave-one-out error is no lower with NDVI. Use the trend.")
    small = " Province histories are short, so treat this as indicative." if area != ALL else ""
    st.caption(
        f"Fit on {m['n']} completed seasons ({src}, {min(hist)}-{last}). The window (weeks "
        f"{win[0]}-{win[1]}) was fixed by crop stage, not searched. Leave-one-out error is "
        f"{m['rmse_loo']:.2f} t/ha with NDVI against {m['rmse_trend_loo']:.2f} for trend alone.{small}")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(hist), y=list(hist.values()), mode="lines+markers",
                             name="Yield", line=dict(color=GREY)))
    done = {k: v for k, v in hist.items() if k < target}
    ks, b0 = np.polyfit(list(done), list(done.values()), 1)
    yrs = list(range(min(done), target + 1))
    fig.add_trace(go.Scatter(x=yrs, y=[ks * v + b0 for v in yrs], name="Trend",
                             line=dict(color=AMBER, dash="dash")))
    fig.add_trace(go.Scatter(x=[target], y=[m["predicted"]], mode="markers", name="Trend + NDVI",
                             marker=dict(size=13, color=BLUE)))
    if cy:
        fig.add_trace(go.Scatter(x=[target], y=[cy], mode="markers", name="CEC forecast",
                                 marker=dict(size=11, color="#2e7d32", symbol="diamond")))
    fig.update_layout(height=360, template="plotly_white", yaxis_title="t/ha",
                      margin=dict(t=30, b=30), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")
    with st.expander("How the satellite reading maps to yield", expanded=False):
        yrs_ = list(m["years"])
        sc = go.Figure()
        sc.add_trace(go.Scatter(
            x=m["x"], y=m["anomaly"], mode="markers+text", name="Seasons", customdata=yrs_,
            text=[str(v) if v >= 2015 or abs(an) > m["rmse_trend_loo"] * 1.5 else ""
                  for v, an in zip(yrs_, m["anomaly"])], textposition="top center",
            textfont=dict(size=9), marker=dict(size=8, color="#5e7164"),
            hovertemplate="%{customdata}: NDVI %{x:.3f}, %{y:+.2f} t/ha vs trend<extra></extra>"))
        kk, ii = np.polyfit(m["x"], m["anomaly"], 1)
        xs = [float(min(m["x"])), float(max(m["x"]))]
        sc.add_trace(go.Scatter(x=xs, y=[kk * v + ii for v in xs], mode="lines", name="Fit",
                                line=dict(color=AMBER, dash="dash")))
        if m["x_now"] is not None:
            sc.add_vline(x=m["x_now"], line_color=BLUE, line_width=2.5,
                         annotation_text=str(target), annotation_font_color=BLUE)
        sc.update_layout(title="Yield minus trend against the window NDVI", height=340,
                         template="plotly_white", showlegend=False, margin=dict(t=50, b=40),
                         xaxis_title="Mean NDVI over the window", yaxis_title="Yield minus trend (t/ha)")
        st.plotly_chart(sc, width="stretch")
    scan = _scan(crop)
    if scan.empty:
        return
    st.subheader(f"Where the satellite helps: {crop.lower()}, by province")
    fmt = {c: "{:.2f}" for c in scan.columns if "t/ha" in c}
    fmt |= {"Mean area (kha)": "{:,.0f}", "Skill vs trend": "{:+.0%}", "n": "{:.0f}"}
    st.dataframe(scan.style.format(fmt, na_rep="n/a"), width="stretch", hide_index=True)
    helped = int((scan["Skill vs trend"] > 0.03).sum())
    st.caption(f"Skill is the cut in leave-one-out yield error from adding the window NDVI to the "
               f"trend; with 11 seasons of province history it is a noisy measure. The satellite helps "
               f"in {helped} of {len(scan)} provinces.")

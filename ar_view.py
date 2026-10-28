"""Argentina view: NOAA satellite by province and a province yield model on MAGyP estimates."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import production
import vh
from charts import AMBER, BLUE, GREY, vh_chart

DATA = Path(__file__).parent / "data" / "ar_yields.csv"
CROPS = list(vh.AR_WINDOWS)
NO_NDVI = {"Chubut", "Formosa", "Santa Cruz", "Tierra del Fuego"}  # NOAA returns no cropland series


@st.cache_data(ttl=3600)
def _yields():
    return pd.read_csv(DATA) if DATA.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def _vh(province):
    return vh.load_ar(province)


def _campaign(sy):
    return f"{int(sy)}/{(int(sy) + 1) % 100:02d}"


def render():
    st.title("Argentina crop conditions and yields")
    st.caption("NOAA STAR satellite crop condition by province and a province yield model on the "
               "agriculture ministry's (MAGyP) estimates. Argentina's weekly progress and condition "
               "reports (Bolsa de Cereales de Buenos Aires) block automated access, so this view "
               "has no weekly ratings.")
    provs = [p for p in vh.AR_PROVINCES if p not in NO_NDVI]
    with st.sidebar:
        crop = st.selectbox("Crop", CROPS, key="ar_crop")
        province = st.selectbox("Province", provs, index=provs.index("Córdoba"), key="ar_province")
        st.caption("Soybeans, corn and sunflower are sown from Sep to Dec and harvested Feb to "
                   "Jun; wheat is sown May to Jul and harvested Dec to Jan.")
    t0, t1, t2, t4, t3 = st.tabs(["National progress", "Satellite", "Yield model",
                                  "Areas and calendar", "Sources"])
    with t4:
        production.areas_tab("Argentina", crop)
    with t0:
        _progress()
    with t1:
        _satellite(crop, province)
    with t2:
        _model(crop, province)
    with t3:
        st.markdown("""
**Satellite** - NOAA STAR Vegetation Health, province average of cropland pixels, weekly from
1982, labelled experimental. Windows are fixed in advance by crop stage: soybeans weeks 2-10 of
the calendar year the crop is harvested, corn weeks 1-12, sunflower weeks 1-8, sorghum weeks 4-14,
wheat weeks 36-44 of the year it is sown. Chubut, Formosa, Santa Cruz and Tierra del Fuego return
no cropland series. A province average mixes crops, so read it as a regional greenness signal.

**Yield model** - MAGyP "Estimaciones agrícolas" (CC BY 4.0), summed from departments to
provinces: production over harvested area, campaigns 1969/70 onward. The file in use ends with
campaign 2024/25; the 2025/26 campaign is therefore a forecast from the satellite window, not a
check against an official figure. The model is the year trend with and without the mean NDVI over
the window; skill is the cut in leave-one-out error. The implied national figure weights each
province by its latest harvested area.

**National progress** - the agriculture ministry's weekly "Informe Semanal" PDF states the national
sown (or harvested) share of each crop only as a sentence in the crop's paragraph, so that sentence
is what is read, with last year's figure when the sentence gives one. The delegation grids in the
PDF do not extract cleanly and are not used. The reports page lists only the current month and the
site blocks bursts of requests, so the history starts in October 2026 and grows by the weekly
`arprog` job (a few requests a week). Weeks where the report gives no national figure for a crop
are simply absent.

**Not here** - weekly condition reports (Bolsa de Cereales de Buenos Aires
and Rosario publish them as PDFs or behind bot checks), and private estimates (BAGE, BCR), which
are typed into the WASDE dashboard's Alt. Groups page.

The MAGyP file is hosted on datos.magyp.gob.ar, which the JSA droplet cannot reach: refresh it from
a PC with `python build_data.py aryields` (it changes only a few times a year). The satellite series
refreshes weekly with `arvh`.
""")


def _progress():
    p = DATA.parent / "ar_progress.csv"
    d = pd.read_csv(p) if p.exists() else pd.DataFrame()
    d = d[d["kind"].isin(["seeding", "harvest"])] if len(d) else d
    if d.empty:
        st.info("No national progress yet. It is read from the ministry's weekly report: run "
                "build_data.py arprog.")
        return
    d["date"] = pd.to_datetime(d["date"])
    st.caption("Ministry (MAGyP) Informe Semanal, national share of the expected area sown or "
               "harvested, as stated in the report text. History starts October 2026.")
    latest = d.sort_values("date").groupby(["kind", "crop"]).tail(1).copy()
    latest["vs last year"] = latest["value"] - latest["last_year"]
    show = latest.rename(columns={"kind": "Activity", "crop": "Crop", "date": "As of",
                                  "value": "% done", "last_year": "Last year %"})
    show["As of"] = show["As of"].dt.strftime("%b %d, %Y")
    st.dataframe(show[["Crop", "Activity", "As of", "% done", "Last year %", "vs last year"]]
                 .sort_values(["Activity", "Crop"]).reset_index(drop=True), width="stretch",
                 hide_index=True)
    fig = go.Figure()
    for (kind, c), g in d.sort_values("date").groupby(["kind", "crop"]):
        fig.add_trace(go.Scatter(x=g["date"], y=g["value"], mode="lines+markers",
                                 name=f"{c} ({kind})"))
    fig.update_layout(title="National progress by report date", yaxis_title="% of expected area",
                      height=360, template="plotly_white", margin=dict(t=50, b=30),
                      legend=dict(orientation="h", y=-0.2))
    st.plotly_chart(fig, width="stretch")


def _satellite(crop, province):
    df = _vh(province)
    a, b, off = vh.AR_WINDOWS[crop]
    ly, lw = vh.last_week(df)
    st.caption(f"NOAA STAR Vegetation Health, {province} cropland only, through week {lw} of {ly} "
               f"(about {vh.week_start(ly, lw):%b %d}).")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="ar_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, _ = vh_chart(df, col, ly, span=(1, 52))
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, a)),
                  x1=pd.Timestamp(vh.week_start(2001, b + 1)), fillcolor=BLUE, opacity=0.08,
                  line_width=0, annotation_text=f"{crop} window")
    fig.update_layout(title=f"{province} cropland, weekly {vh.LABEL[col]}", height=400,
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


def _fit(crop, province):
    y = _yields()
    s = y[(y["crop"] == crop) & (y["provincia"] == province)]
    a, b, off = vh.AR_WINDOWS[crop]
    hist = {int(sy) + off: float(v) for sy, v in zip(s["start_year"], s["yield_kgha"])}
    if province in NO_NDVI or len(hist) < 12:
        return None, hist, None
    df = _vh(province)
    ly = int(df["year"].max())
    target = ly if vh.window_mean(df, ly, (a, b)) is not None else ly - 1
    done = {k: v for k, v in hist.items() if k < target}
    m = vh.yield_model(df, None, done, target, win=(a, b)) if len(done) >= 12 else None
    return m, hist, target


@st.cache_data(ttl=3600)
def _scan(crop):
    y = _yields()
    d = y[y["crop"] == crop]
    last = int(d["start_year"].max())
    rows = []
    for prov in d["provincia"].unique():
        m, hist, target = _fit(crop, prov)
        cur = d[(d["provincia"] == prov) & (d["start_year"] == last)]
        if m and m["predicted"] is not None and len(cur):
            rows.append({"Province": prov, f"Harvested {_campaign(last)} (kha)": cur["harvested_ha"].sum() / 1000,
                         f"Production {_campaign(last)} (kt)": cur["prod_t"].sum() / 1000,
                         "Trend (kg/ha)": m["trend_year"], "Trend + NDVI (kg/ha)": m["predicted"],
                         "Satellite vs trend": m["predicted"] / m["trend_year"] - 1,
                         "Skill vs trend": m["skill"], "n": m["n"]})
    return pd.DataFrame(rows).sort_values(f"Production {_campaign(last)} (kt)", ascending=False) if rows \
        else pd.DataFrame()


def _model(crop, province):
    y = _yields()
    if y.empty:
        st.info("No MAGyP data. Run build_data.py aryields (from a PC).")
        return
    m, hist, target = _fit(crop, province)
    a, b, off = vh.AR_WINDOWS[crop]
    st.subheader(f"{province} {crop.lower()}: trend vs trend plus greenness")
    if not m or m["predicted"] is None:
        st.info(f"{province} has too little {crop.lower()} history for a model.")
        return
    last = max(k for k in hist if k < target + 1)
    camp = _campaign(target - off)
    c = st.columns(4)
    c[0].metric(f"Trend, campaign {camp}", f"{m['trend_year']:,.0f} kg/ha")
    c[1].metric(f"Trend + NDVI, campaign {camp}", f"{m['predicted']:,.0f} kg/ha",
                f"{m['predicted'] / m['trend_year'] - 1:+.0%} vs trend", delta_color="off")
    c[2].metric(f"Last MAGyP yield ({_campaign(last - off)})", f"{hist[last]:,.0f} kg/ha")
    c[3].metric("Skill vs trend (leave-one-out)", f"{m['skill'] * 100:+.0f}%")
    if m["skill"] <= 0.03:
        st.warning("For this province and crop the satellite reading adds nothing measurable to the "
                   "yield trend: the leave-one-out error is no lower with NDVI. Use the trend.")
    st.caption(
        f"Fit on {m['n']} completed campaigns (MAGyP, {_campaign(min(hist) - off)} to "
        f"{_campaign(max(k for k in hist if k < target) - off)}). The window (weeks {a}-{b}) was fixed "
        f"by crop stage, not searched. Leave-one-out error is {m['rmse_loo']:,.0f} kg/ha with NDVI "
        f"against {m['rmse_trend_loo']:,.0f} for trend alone. MAGyP's file does not yet include "
        f"campaign {camp}, so that campaign is a forecast, not a check.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[k - off for k in hist], y=list(hist.values()), mode="lines+markers",
                             name="MAGyP yield", line=dict(color=GREY)))
    done = {k: v for k, v in hist.items() if k < target}
    ks, b0 = np.polyfit(list(done), list(done.values()), 1)
    yrs = list(range(min(done), target + 1))
    fig.add_trace(go.Scatter(x=[v - off for v in yrs], y=[ks * v + b0 for v in yrs], name="Trend",
                             line=dict(color=AMBER, dash="dash")))
    fig.add_trace(go.Scatter(x=[target - off], y=[m["predicted"]], mode="markers", name="Trend + NDVI",
                             marker=dict(size=13, color=BLUE)))
    fig.update_layout(height=360, template="plotly_white", yaxis_title="kg/ha",
                      xaxis_title="Campaign start year", margin=dict(t=30, b=30),
                      legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")
    with st.expander("How the satellite reading maps to yield", expanded=False):
        yrs_ = [v - off for v in m["years"]]
        sc = go.Figure()
        sc.add_trace(go.Scatter(
            x=m["x"], y=m["anomaly"], mode="markers+text", name="Campaigns", customdata=[_campaign(v) for v in yrs_],
            text=[_campaign(v) if v >= 2015 or abs(an) > m["rmse_trend_loo"] * 1.5 else ""
                  for v, an in zip(yrs_, m["anomaly"])], textposition="top center",
            textfont=dict(size=9), marker=dict(size=8, color="#5e7164"),
            hovertemplate="%{customdata}: NDVI %{x:.3f}, %{y:+,.0f} kg/ha vs trend<extra></extra>"))
        kk, ii = np.polyfit(m["x"], m["anomaly"], 1)
        xs = [float(min(m["x"])), float(max(m["x"]))]
        sc.add_trace(go.Scatter(x=xs, y=[kk * v + ii for v in xs], mode="lines", name="Fit",
                                line=dict(color=AMBER, dash="dash")))
        if m["x_now"] is not None:
            sc.add_vline(x=m["x_now"], line_color=BLUE, line_width=2.5,
                         annotation_text=camp, annotation_font_color=BLUE)
        sc.update_layout(title="Yield minus trend against the window NDVI", height=340,
                         template="plotly_white", showlegend=False, margin=dict(t=50, b=40),
                         xaxis_title="Mean NDVI over the window",
                         yaxis_title="Yield minus trend (kg/ha)")
        st.plotly_chart(sc, width="stretch")
    scan = _scan(crop)
    if scan.empty:
        return
    st.subheader(f"Where the satellite helps: {crop.lower()}, by province")
    area_col = scan.columns[1]
    w = scan[area_col]
    implied = float((w * scan["Trend + NDVI (kg/ha)"]).sum() / (w * scan["Trend (kg/ha)"]).sum() - 1)
    st.metric(f"Implied national yield vs trend, campaign {camp} (area-weighted, {len(scan)} provinces)",
              f"{implied:+.1%}", delta_color="off")
    fmt = {c: "{:,.0f}" for c in scan.columns if c not in ("Province", "Satellite vs trend",
                                                           "Skill vs trend", "n")}
    fmt |= {"Satellite vs trend": "{:+.1%}", "Skill vs trend": "{:+.0%}", "n": "{:.0f}"}
    st.dataframe(scan.head(14).style.format(fmt), width="stretch", hide_index=True)
    helped = int((scan["Skill vs trend"] > 0.03).sum())
    st.caption(f"Skill is the cut in leave-one-out yield error from adding the window NDVI to the "
               f"trend; the satellite helps in {helped} of {len(scan)} provinces. The implied "
               "national figure applies each province's satellite-vs-trend gap to its latest "
               "harvested area, so it moves with the big provinces.")

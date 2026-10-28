"""France view: Céré'Obs maize conditions, NOAA satellite by region, Agreste estimates, MARS notes."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import vh
from charts import AMBER, BLUE, GREY, vh_chart

DATA = Path(__file__).parent / "data"
STAGES = {"Sowing": "sowing", "Emergence": "emergence", "6-8 leaves": "leaves_6_8",
          "Flowering (female)": "flowering", "Grain moisture 50%": "grain_moisture_50",
          "Harvest": "harvest"}
CLASSES = [("very_poor", "Very poor", "#b3261e"), ("poor", "Poor", "#e57c5b"),
           ("fair", "Fair", "#f2c14e"), ("good", "Good", "#7bb661"), ("very_good", "Very good", "#2e7d32")]
CROP_WINDOW = {"Soft wheat": "Winter cereals", "Winter barley": "Winter cereals",
               "Grain maize": "Grain maize"}


@st.cache_data(ttl=3600)
def _csv(name):
    p = DATA / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def _vh(region):
    return vh.load_fr(region)


def _week_lines(df, ycol, title, ylabel, cur_year):
    fig = go.Figure()
    for y in sorted(df["year"].unique()):
        d = df[df["year"] == y].sort_values("wk")
        cur = y == cur_year
        fig.add_trace(go.Scatter(x=d["wk"], y=d[ycol], name=str(y), mode="lines+markers",
                                 line=dict(width=4 if cur else 1.5, color=BLUE if cur else None),
                                 opacity=1 if cur else 0.55, marker=dict(size=6 if cur else 3)))
    fig.update_layout(title=title, yaxis_title=ylabel, xaxis_title="Week of year", height=360,
                      template="plotly_white", margin=dict(t=50, b=30),
                      legend=dict(orientation="h", y=-0.2))
    return fig


def render():
    st.title("France crop conditions and estimates")
    st.caption("FranceAgriMer Céré'Obs maize conditions, NOAA satellite by region, Agreste estimates "
               "and JRC MARS notes. Céré'Obs wheat and barley ratings are not open data, so the "
               "conditions tab covers grain maize only.")
    with st.sidebar:
        crop = st.selectbox("Crop (satellite window)", list(CROP_WINDOW), index=2, key="fr_crop")
        region = st.selectbox("NOAA region", list(vh.FR_REGIONS.values()),
                              index=list(vh.FR_REGIONS.values()).index("Centre"), key="fr_region")
        st.caption("NOAA STAR uses France's 22 pre-2016 regions; Céré'Obs and Agreste use the "
                   "13 current ones.")
    t1, t2, t3, t4, t5 = st.tabs(["Maize conditions", "Satellite", "Agreste estimates", "MARS notes",
                                  "Sources"])
    with t1:
        _cereobs()
    with t2:
        _satellite(crop, region)
    with t3:
        _agreste()
    with t4:
        _mars()
    with t5:
        st.markdown("""
**Maize conditions** - FranceAgriMer Céré'Obs, weekly field-technician ratings of grain maize as a
share of area in five classes (very poor to very good) and stage progress, for France, the
regions and agronomic zones, 2015 onward (open data, Licence Ouverte 2.0, updated Fridays). Soft
wheat, durum and barley ratings are published only through the Céré'Obs app and weekly reports,
not as open files, so they are not here.

**Satellite** - NOAA STAR Vegetation Health, region average of cropland pixels, weekly from 1982,
labelled experimental. Windows are fixed by crop stage in advance (winter cereals weeks 14-26,
grain maize weeks 29-37), not fitted. NOAA's regions are the pre-2016 ones.

**Agreste estimates** - Agreste "Infos rapides - Grandes cultures" figure workbooks: early
estimates of area, yield and production against last year, and the national soft wheat and barley
yield series since 1996. Issue ids are not predictable, so new issues are added by hand in
`build_data.AGRESTE_ISSUES`; only the July 2026 issue is loaded so far.

**MARS notes** - monthly JRC MARS crop-monitoring summaries (paragraphs that mention France). The
bulletin PDFs and the Agri4Cast portal reject scripted downloads, so the yield-forecast tables are
not available here.

Refresh with `python build_data.py frcereobs`, `frvh`, `fragreste` and `frmars`.
""")


def _cereobs():
    d = _csv("fr_cereobs.csv")
    if d.empty:
        st.info("No Céré'Obs data. Run build_data.py frcereobs.")
        return
    level = st.radio("Area", ["France", "Région", "Zone"], horizontal=True, key="fr_level",
                     format_func={"France": "France", "Région": "Region", "Zone": "Agronomic zone"}.get)
    names = sorted(d[d["level"] == level]["name"].unique())
    name = names[0] if level == "France" else st.selectbox("Name", names, key="fr_name")
    a = d[(d["level"] == level) & (d["name"] == name)].copy()
    a["ge"] = a[["good", "very_good"]].sum(axis=1, min_count=1)
    years = sorted(a["year"].unique())
    cur = int(years[-1])
    ca = a[a["year"] == cur].dropna(subset=["ge"]).sort_values("wk")
    if ca.empty:
        st.info("No condition ratings for this area in the latest season.")
        return
    last = ca.iloc[-1]
    prev = ca.iloc[-2]["ge"] if len(ca) > 1 else np.nan

    def at_week(y, w):
        s = a[(a["year"] == y) & (a["wk"] <= w)].dropna(subset=["ge"]).sort_values("wk")
        return s.iloc[-1]["ge"] if len(s) else np.nan
    ly = at_week(cur - 1, int(last["wk"]))
    hist = sorted(v for v in (at_week(y, int(last["wk"])) for y in years if y < cur) if not np.isnan(v))
    oly = float(np.mean(hist[1:-1])) if len(hist) >= 3 else (float(np.mean(hist)) if hist else np.nan)
    c = st.columns(4)
    c[0].metric(f"Maize good + very good, week {int(last['wk'])}", f"{last['ge']:.0f}%",
                f"{last['ge'] - prev:+.0f} pts vs prior week" if not np.isnan(prev) else None)
    c[1].metric("vs last year (same week)", f"{last['ge'] - ly:+.0f} pts" if not np.isnan(ly) else "n/a")
    c[2].metric("vs olympic average", f"{last['ge'] - oly:+.0f} pts" if not np.isnan(oly) else "n/a")
    c[3].metric("Harvested", f"{last['harvest']:.0f}%" if pd.notna(last["harvest"]) else "n/a")
    st.plotly_chart(_week_lines(a.dropna(subset=["ge"]), "ge", f"{name}: grain maize, % of area in "
                                "good or very good condition", "% good + very good", cur),
                    width="stretch")
    left, right = st.columns(2)
    with left:
        fig = go.Figure()
        for col, label, color in CLASSES:
            fig.add_trace(go.Bar(x=ca["wk"], y=ca[col], name=label, marker_color=color))
        fig.update_layout(barmode="stack", title=f"{cur} condition classes", height=340,
                          template="plotly_white", margin=dict(t=50, b=30),
                          yaxis_title="% of area", xaxis_title="Week of year",
                          legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig, width="stretch")
    with right:
        stage = st.radio("Stage", list(STAGES), horizontal=True, index=3, key="fr_stage")
        st.plotly_chart(_week_lines(a.dropna(subset=[STAGES[stage]]), STAGES[stage],
                                    f"{name}: {stage.lower()}, % of area", "% of area", cur),
                        width="stretch")
    st.caption("Céré'Obs rates the share of area in each class from field observations. Good plus "
               "very good is the headline figure, comparable to USDA's good-excellent. Weeks are "
               "ISO-style week numbers; the latest week is provisional.")


def _satellite(crop, region):
    df = _vh(region)
    win = vh.FR_WINDOWS[CROP_WINDOW[crop]]
    ly, lw = vh.last_week(df)
    st.caption(f"NOAA STAR Vegetation Health, {region} cropland only, through week {lw} of {ly} "
               f"(about {vh.week_start(ly, lw):%b %d}).")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="fr_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, _ = vh_chart(df, col, ly, span=(1, 52))
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, win[0])),
                  x1=pd.Timestamp(vh.week_start(2001, win[1] + 1)), fillcolor=BLUE, opacity=0.08,
                  line_width=0, annotation_text=f"{crop} window")
    fig.update_layout(title=f"{region} cropland, weekly {vh.LABEL[col]}", height=400,
                      template="plotly_white", margin=dict(t=50, b=30), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b %d")
    st.plotly_chart(fig, width="stretch")
    year = ly if vh.window_mean(df, ly, win) is not None else ly - 1
    season = vh.season_table(df, None, year, win=win)
    if season.empty:
        return
    a, b = win
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


def _agreste():
    est = _csv("fr_agreste_estimates.csv")
    ser = _csv("fr_agreste_series.csv")
    if est.empty:
        st.info("No Agreste data. Run build_data.py fragreste.")
        return
    issue = est["issue"].max()
    e = est[est["issue"] == issue]
    st.subheader(f"Agreste early estimates, issue {issue}")
    cur_year = int(issue[:4])
    show = e.rename(columns={
        "group": "Group", "crop": "Crop", "area25_kha": f"Area {cur_year - 1} (kha)",
        "yield25_qha": f"Yield {cur_year - 1} (q/ha)", "prod25_kt": f"Production {cur_year - 1} (kt)",
        "area26_kha": f"Area {cur_year} (kha)", "yield26_qha": f"Yield {cur_year} (q/ha)",
        "prod26_kt": f"Production {cur_year} (kt)", "chg_prod_pct": "Production vs last year (%)",
        "chg_vs_5yr_pct": "vs 5-yr average (%)"}).drop(columns="issue")
    num = [c for c in show.columns if c not in ("Group", "Crop")]
    st.dataframe(show.style.format({c: "{:,.1f}" for c in num}), width="stretch", hide_index=True)
    st.caption("Agreste Infos rapides, estimates at the first of the month, against the semi-final "
               f"{cur_year - 1} figures. Sub-rows are winter and spring types.")
    if len(ser):
        crop = st.radio("National series", ["Soft wheat", "Barley"], horizontal=True, key="fr_ser")
        s = ser[ser["crop"] == crop].sort_values("year")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=s["year"], y=s["prod_mt"], name="Production (Mt)", marker_color=BLUE,
                             opacity=0.75))
        fig.add_trace(go.Scatter(x=s["year"], y=s["yield_qha"], name="Yield (q/ha)", yaxis="y2",
                                 line=dict(color=AMBER, width=3)))
        last = s.iloc[-1]
        fig.add_trace(go.Scatter(x=[last["year"]], y=[last["yield_qha"]], yaxis="y2", mode="markers",
                                 name=f"{int(last['year'])} estimate", marker=dict(size=12, color=GREY)))
        fig.update_layout(title=f"France {crop.lower()}: production and yield, 1996-{int(last['year'])}",
                          height=380, template="plotly_white", margin=dict(t=50, b=30),
                          yaxis=dict(title="Mt"), yaxis2=dict(title="q/ha", overlaying="y",
                                                              side="right", showgrid=False),
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"The last point is Agreste's {int(last['year'])} early estimate, not a final figure.")


def _mars():
    m = _csv("mars_news.csv")
    if m.empty:
        st.info("No MARS notes. Run build_data.py frmars.")
        return
    st.subheader("JRC MARS crop-monitoring bulletins: what they say about France")
    st.caption("Monthly summaries from the JRC. Only paragraphs that mention France are shown; the "
               "yield-forecast tables in the PDF bulletins are not available to scripts.")
    for _, r in m.head(8).iterrows():
        with st.expander(f"{r['date']}: {r['title']}", expanded=r.name == 0):
            if isinstance(r["france"], str) and r["france"]:
                st.write(r["france"])
            else:
                st.write("No paragraph in this summary mentions France.")
            st.markdown(f"[Full summary on the JRC site]({r['url']})")

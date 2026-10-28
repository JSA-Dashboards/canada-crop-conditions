"""Brazil view: CONAB weekly progress by state, NOAA satellite by state, CONAB state yield model."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import production
import vh
from charts import AMBER, BLUE, GREY, vh_chart

DATA = Path(__file__).parent / "data"
MODEL_CROPS = ["Soybeans", "Corn 1st crop", "Corn 2nd crop", "Wheat"]
UF_OF = {name: uf for uf, (name, _) in vh.BR_STATES.items()}


@st.cache_data(ttl=3600)
def _csv(name):
    p = DATA / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def _vh(uf):
    return vh.load_br(uf)


def _common_x(week_end, safra):
    """Place a weekly date on a common axis so every crop year overlays (a season that runs
    from Sep to Jun spills into a second axis year)."""
    d = pd.Timestamp(week_end)
    start = int(str(safra)[:4])
    off = max(d.year - start, 0)
    m, day = (d.month, min(d.day, 28)) if d.month == 2 and d.day == 29 else (d.month, d.day)
    return pd.Timestamp(2001 + off, m, day)


def render():
    st.title("Brazil crop progress and yields")
    st.caption("CONAB weekly planting and harvest progress by state, NOAA STAR satellite crop "
               "condition by state, and a state yield model on CONAB's series. CONAB publishes no "
               "numeric condition ratings: its weekly condition report is narrative.")
    prog = _csv("br_progress.csv")
    series = _csv("br_series.csv")
    with st.sidebar:
        crop = st.selectbox("Crop", MODEL_CROPS, key="br_crop")
        state = st.selectbox("State", [n for n, _ in vh.BR_STATES.values()
                                       if n not in ("Acre", "Amapá")],
                             index=[n for n, _ in vh.BR_STATES.values()
                                    if n not in ("Acre", "Amapá")].index("Mato Grosso"),
                             key="br_state")
        st.caption("Corn is split into first crop (summer, planted Sep-Nov) and second crop "
                   "(safrinha, planted after soybeans from Jan). Wheat is a southern winter crop.")
    t1, t2, t3, t5, t4 = st.tabs(["Weekly progress", "Satellite", "Yield model",
                                  "Areas and calendar", "Sources"])
    with t5:
        production.areas_tab("Brazil", crop)
    with t1:
        _progress(prog, crop, state)
    with t2:
        _satellite(crop, state)
    with t3:
        _model(series, crop, state)
    with t4:
        st.markdown("""
**Weekly progress** - CONAB "Progresso de Safra" weekly workbook (`plantio-e-colheita`): share of
area sown or harvested by state, against the same week last year, the previous week and the
five-year average. Crop years are labelled as CONAB does (soybeans 2025/26, wheat 2026). CONAB's
site is licensed CC BY-ND 3.0: figures are shown with attribution and unchanged. CONAB's weekly
condition report (`monitoramento-das-condicoes-das-lavouras.pdf`) is narrative and is not parsed.

**Satellite** - NOAA STAR Vegetation Health, state average of cropland pixels, weekly from 1982,
labelled experimental. Windows are fixed in advance in the calendar year the crop is harvested:
soybeans and first-crop corn weeks 1-9, second-crop corn weeks 12-24, wheat weeks 31-41. Acre
and Amapá return no cropland series.

**Yield model** - CONAB historical series by state (1976/77 onward; the newest year is a
forecast) against the year trend, with and without the mean NDVI over the window. Skill is the cut
in leave-one-out error. The latest harvested crop is shown as a check against its actual yield.

Refresh with `python build_data.py brprog`, `brvh` and `brseries`.
""")


def _progress(prog, crop, state):
    if prog.empty:
        st.info("No CONAB progress data. Run build_data.py brprog.")
        return
    d0 = prog[prog["crop"] == crop]
    if d0.empty:
        st.info(f"No weekly progress for {crop.lower()} yet.")
        return
    acts = sorted(d0["activity"].unique())
    newest = d0.sort_values("week_end").iloc[-1]["activity"]  # open on what is happening now
    act = st.radio("Activity", acts, horizontal=True, key=f"br_act_{crop}", index=acts.index(newest),
                   format_func={"sowing": "Sowing", "harvest": "Harvest"}.get)
    d = d0[d0["activity"] == act]
    names = ["Total"] + sorted(n for n in d["state"].unique() if n != "Total")
    name = state if state in names else "Total"
    area = st.selectbox("Area", names, index=names.index(name), key=f"br_area_{crop}_{act}_{state}")
    a = d[d["state"] == area].copy()
    if a.empty:
        st.info("No data for this area.")
        return
    a["week_end"] = pd.to_datetime(a["week_end"])
    latest_safra = a.sort_values("week_end").iloc[-1]["safra"]
    last = a[a["safra"] == latest_safra].sort_values("week_end").iloc[-1]
    c = st.columns(4)
    word = "sown" if act == "sowing" else "harvested"
    c[0].metric(f"{area} {crop.lower()} {word}, {latest_safra}", f"{last['this_week'] * 100:.0f}%",
                f"{(last['this_week'] - last['prev_week']) * 100:+.0f} pts on the week"
                if pd.notna(last["prev_week"]) else None)
    c[1].metric("Week ending", f"{last['week_end']:%b %d, %Y}")
    c[2].metric("vs last year", f"{(last['this_week'] - last['last_year']) * 100:+.0f} pts"
                if pd.notna(last["last_year"]) else "n/a")
    c[3].metric("vs 5-year average", f"{(last['this_week'] - last['avg5']) * 100:+.0f} pts"
                if pd.notna(last["avg5"]) else "n/a")
    fig = go.Figure()
    for safra in sorted(a["safra"].unique()):
        s = a[a["safra"] == safra].sort_values("week_end")
        cur = safra == latest_safra
        fig.add_trace(go.Scatter(
            x=[_common_x(w, safra) for w in s["week_end"]], y=s["this_week"] * 100, name=str(safra),
            mode="lines+markers", line=dict(width=4 if cur else 1.5, color=BLUE if cur else None),
            opacity=1 if cur else 0.55, marker=dict(size=7 if cur else 3)))
    s = a[a["safra"] == latest_safra].sort_values("week_end")
    if s["avg5"].notna().any():
        fig.add_trace(go.Scatter(x=[_common_x(w, latest_safra) for w in s["week_end"]],
                                 y=s["avg5"] * 100, name="5-year average",
                                 line=dict(color=GREY, dash="dash")))
    fig.update_layout(title=f"{area}: {crop.lower()} {word}, % of area", yaxis_title="% of area",
                      height=380, template="plotly_white", margin=dict(t=50, b=30),
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b")
    st.plotly_chart(fig, width="stretch")
    wk = d[(d["week_end"] == d[d["safra"] == latest_safra]["week_end"].max())
           & (d["safra"] == latest_safra)].copy()
    wk = wk.assign(vs_avg=(wk["this_week"] - wk["avg5"]) * 100).sort_values("this_week", ascending=False)
    st.subheader(f"All states, week ending {pd.Timestamp(wk['week_end'].iloc[0]):%b %d, %Y}")
    show = pd.DataFrame({"State": wk["state"], "This week": wk["this_week"], "Previous week": wk["prev_week"],
                         "Same week last year": wk["last_year"], "5-year average": wk["avg5"],
                         "vs 5-yr avg (pts)": wk["vs_avg"]})
    st.dataframe(show.style.format({c: "{:.0%}" for c in ("This week", "Previous week",
                                                           "Same week last year", "5-year average")}
                                   | {"vs 5-yr avg (pts)": "{:+.0f}"}, na_rep="n/a"),
                 width="stretch", hide_index=True)
    st.caption("Source: CONAB, Progresso de Safra. Series by crop year; states are those CONAB "
               "reports for the crop.")


def _satellite(crop, state):
    uf = UF_OF[state]
    df = _vh(uf)
    win = vh.BR_WINDOWS[crop]
    ly, lw = vh.last_week(df)
    st.caption(f"NOAA STAR Vegetation Health, {state} cropland only, through week {lw} of {ly} "
               f"(about {vh.week_start(ly, lw):%b %d}).")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="br_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, _ = vh_chart(df, col, ly, span=(1, 52))
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, win[0])),
                  x1=pd.Timestamp(vh.week_start(2001, win[1] + 1)), fillcolor=BLUE, opacity=0.08,
                  line_width=0, annotation_text=f"{crop} window")
    fig.update_layout(title=f"{state} cropland, weekly {vh.LABEL[col]}", height=400,
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


def _history(series, crop, uf):
    """({harvest year: kg/ha}, {harvest year: forecast flag}). Soybeans and corn crop years run
    across the new year (2025/26 is harvested in 2026); CONAB labels wheat by calendar year."""
    d = series[(series["crop"] == crop) & (series["uf"] == uf) & (series["yield_kgha"] > 0)]
    off = 0 if crop == "Wheat" else 1
    return ({int(a) + off: float(b) for a, b in zip(d["start_year"], d["yield_kgha"])},
            {int(a) + off: bool(f) for a, f in zip(d["start_year"], d["forecast"])})


def _fit(series, crop, uf):
    hist, fc = _history(series, crop, uf)
    df = _vh(uf)
    win = vh.BR_WINDOWS[crop]
    ly = int(df["year"].max())
    target = ly if vh.window_mean(df, ly, win) is not None else ly - 1
    done = {k: v for k, v in hist.items() if k < target and not fc.get(k, False)}
    m = vh.yield_model(df, None, done, target, win=win) if len(done) >= 12 else None
    return m, done, hist, fc, target


@st.cache_data(ttl=3600)
def _scan(crop):
    series = _csv("br_series.csv")
    d = series[(series["crop"] == crop) & (series["uf"] != "BRASIL") & (~series["forecast"])]
    last = int(d["start_year"].max())
    rows = []
    names = {uf: n for uf, (n, _) in vh.BR_STATES.items()}
    for uf in d["uf"].unique():
        if uf in ("AC", "AP") or uf not in names:
            continue
        m, done, hist, fc, target = _fit(series, crop, uf)
        prod = d[(d["uf"] == uf) & (d["start_year"] == last)]["prod_kt"].sum()
        if m and m["predicted"] is not None and prod > 0:
            actual = hist.get(target)
            rows.append({"State": names[uf], f"{last} production (kt)": prod,
                         "Target year": target, "Trend (kg/ha)": m["trend_year"],
                         "Trend + NDVI (kg/ha)": m["predicted"],
                         "Actual (kg/ha)": actual if actual and not fc.get(target) else np.nan,
                         "Skill vs trend": m["skill"]})
    return pd.DataFrame(rows).sort_values(f"{last} production (kt)", ascending=False).head(14) \
        if rows else pd.DataFrame()


def _model(series, crop, state):
    if series.empty:
        st.info("No CONAB series. Run build_data.py brseries.")
        return
    uf = UF_OF[state]
    m, done, hist, fc, target = _fit(series, crop, uf)
    st.subheader(f"{state} {crop.lower()}: trend vs trend plus greenness")
    if not m or m["predicted"] is None:
        st.info(f"{state} has too little {crop.lower()} history for a model (CONAB reports it in "
                "too few years).")
        return
    win = vh.BR_WINDOWS[crop]
    actual = hist.get(target)
    is_fc = fc.get(target, False)
    c = st.columns(4)
    c[0].metric(f"Trend, {target}", f"{m['trend_year']:,.0f} kg/ha")
    c[1].metric(f"Trend + NDVI, {target}", f"{m['predicted']:,.0f} kg/ha")
    c[2].metric(f"CONAB {'forecast' if is_fc else 'actual'}, {target}",
                f"{actual:,.0f} kg/ha" if actual else "n/a")
    c[3].metric("Skill vs trend (leave-one-out)", f"{m['skill'] * 100:+.0f}%")
    if m["skill"] <= 0.03:
        st.warning("For this state and crop the satellite reading adds nothing measurable to the "
                   "yield trend: the leave-one-out error is no lower with NDVI. Use the trend.")
    if actual and not is_fc:
        err_t, err_n = actual - m["trend_year"], actual - m["predicted"]
        st.info(f"Check on the latest harvested crop ({target}, fitted without it): actual "
                f"{actual:,.0f} kg/ha, trend missed by {err_t:+,.0f}, trend + NDVI by {err_n:+,.0f}.")
    st.caption(
        f"Fit on {m['n']} completed years (CONAB series, harvest years {min(done)}-{max(done)}). "
        f"The window (weeks {win[0]}-{win[1]} of the harvest year) was fixed by crop stage, not "
        f"searched. Leave-one-out error is {m['rmse_loo']:,.0f} kg/ha with NDVI against "
        f"{m['rmse_trend_loo']:,.0f} for trend alone. A state-wide cropland NDVI averages every "
        "crop, so it dilutes the signal for any one crop.")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=list(hist), y=list(hist.values()), mode="lines+markers",
                             name="CONAB yield", line=dict(color=GREY)))
    ks, b0 = np.polyfit(list(done), list(done.values()), 1)
    yrs = list(range(min(done), target + 1))
    fig.add_trace(go.Scatter(x=yrs, y=[ks * v + b0 for v in yrs], name="Trend",
                             line=dict(color=AMBER, dash="dash")))
    fig.add_trace(go.Scatter(x=[target], y=[m["predicted"]], mode="markers", name="Trend + NDVI",
                             marker=dict(size=13, color=BLUE)))
    fig.update_layout(height=360, template="plotly_white", yaxis_title="kg/ha",
                      margin=dict(t=30, b=30), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")
    with st.expander("How the satellite reading maps to yield", expanded=False):
        yrs_ = list(m["years"])
        sc = go.Figure()
        sc.add_trace(go.Scatter(
            x=m["x"], y=m["anomaly"], mode="markers+text", name="Years", customdata=yrs_,
            text=[str(v) if v >= 2018 or abs(a) > m["rmse_trend_loo"] * 1.5 else ""
                  for v, a in zip(yrs_, m["anomaly"])], textposition="top center",
            textfont=dict(size=9), marker=dict(size=8, color="#5e7164"),
            hovertemplate="%{customdata}: NDVI %{x:.3f}, %{y:+,.0f} kg/ha vs trend<extra></extra>"))
        kk, ii = np.polyfit(m["x"], m["anomaly"], 1)
        xs = [float(min(m["x"])), float(max(m["x"]))]
        sc.add_trace(go.Scatter(x=xs, y=[kk * v + ii for v in xs], mode="lines", name="Fit",
                                line=dict(color=AMBER, dash="dash")))
        if m["x_now"] is not None:
            sc.add_vline(x=m["x_now"], line_color=BLUE, line_width=2.5,
                         annotation_text=str(target), annotation_font_color=BLUE)
        sc.update_layout(title="Yield minus trend against the window NDVI", height=340,
                         template="plotly_white", showlegend=False, margin=dict(t=50, b=40),
                         xaxis_title="Mean NDVI over the window",
                         yaxis_title="Yield minus trend (kg/ha)")
        st.plotly_chart(sc, width="stretch")
    nxt = series[(series["crop"] == crop) & (series["uf"] == uf) & (series["forecast"])]
    if len(nxt):
        r = nxt.iloc[0]
        st.info(f"CONAB's first estimate for the {int(r['start_year'])} crop "
                f"({'harvested in ' + str(int(r['start_year']) + (0 if crop == 'Wheat' else 1))}): "
                f"{r['yield_kgha']:,.0f} kg/ha on {r['area_kha']:,.0f} kha, "
                f"{r['prod_kt']:,.0f} kt. The satellite window for that crop has not opened yet.")
    st.subheader(f"Where the satellite helps: {crop.lower()}, by state")
    scan = _scan(crop)
    if scan.empty:
        st.info("No state has enough history for this crop.")
        return
    cols = [c for c in scan.columns if c not in ("State", "Target year", "Skill vs trend")]
    st.dataframe(scan.style.format({c: "{:,.0f}" for c in cols} | {"Skill vs trend": "{:+.0%}",
                                                                    "Target year": "{:.0f}"},
                                   na_rep="n/a"), width="stretch", hide_index=True)
    helped = int((scan["Skill vs trend"] > 0.03).sum())
    st.caption(f"Skill is the cut in leave-one-out yield error from adding the window NDVI to the "
               f"trend; the satellite helps in {helped} of {len(scan)} leading states here. Sorted "
               "by latest CONAB production.")

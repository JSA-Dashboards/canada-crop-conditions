"""Mexico view: NOAA satellite by state, SIAP annual production, SIAP monthly progress."""
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import production
import vh
from charts import AMBER, BLUE, GREY, vh_chart

DATA = Path(__file__).parent / "data"
CROPS = {"Maíz grano": "Corn (grain)", "Sorgo grano": "Sorghum", "Trigo grano": "Wheat",
         "Soya": "Soybeans", "Frijol": "Dry beans", "Cebada grano": "Barley",
         "Garbanzo grano": "Chickpeas", "Cártamo": "Safflower"}
CYCLES = {"Otoño-Invierno": "Autumn-winter (O-I)", "Primavera-Verano": "Spring-summer (P-V)"}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


@st.cache_data(ttl=3600)
def _csv(name):
    p = DATA / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


@st.cache_data(ttl=3600)
def _vh(state):
    return vh.load_mx(state)


# A cycle straddles the calendar year (SIAP's "year" resets in January, mid-harvest), so the
# progress lines are drawn by season: spring-summer starts in April, autumn-winter in October.
CYCLE_START = {"Otoño-Invierno": 10, "Primavera-Verano": 4}


def _seasonal(df, cycle):
    start = CYCLE_START[cycle]
    out = df.copy()
    out["season"] = out["year"] - (out["month"] < start).astype(int)
    out["pos"] = (out["month"] - start) % 12
    return out


def _season_label(season, cycle):
    return f"{season}/{(season + 1) % 100:02d}" if cycle == "Otoño-Invierno" else str(season)


def _lines(df, ycol, title, ylabel, cycle):
    """One line per season, months in cycle order."""
    start = CYCLE_START[cycle]
    order = [MONTHS[(start - 1 + i) % 12] for i in range(12)]
    cur_season = int(df["season"].max())
    fig = go.Figure()
    for s_ in sorted(df["season"].unique()):
        d = df[df["season"] == s_].sort_values("pos")
        cur = s_ == cur_season
        fig.add_trace(go.Scatter(
            x=[MONTHS[m - 1] for m in d["month"]], y=d[ycol], name=_season_label(s_, cycle),
            mode="lines+markers", line=dict(width=4 if cur else 1.5, color=BLUE if cur else None),
            opacity=1 if cur else 0.55, marker=dict(size=7 if cur else 4)))
    fig.update_layout(title=title, yaxis_title=ylabel, height=360, template="plotly_white",
                      margin=dict(t=50, b=30), legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(categoryorder="array", categoryarray=order)
    return fig


def render():
    prod, prog, states_now = _csv("mx_production.csv"), _csv("mx_progress.csv"), \
        _csv("mx_progress_states.csv")
    st.title("Mexico crop conditions and production")
    st.caption("NOAA STAR satellite crop condition by state, and SIAP (SADER) production and "
               "monthly planting and harvest progress. Mexico publishes no weekly condition "
               "ratings like the US or Canadian provinces.")
    with st.sidebar:
        state = st.selectbox("State", [s for s in vh.MX_STATES.values() if s != "Baja California Sur"],
                             index=list(vh.MX_STATES.values()).index("Sinaloa") - 1, key="mx_state")
        crop = st.selectbox("Crop", list(CROPS), format_func=CROPS.get, key="mx_crop")
        cycle = st.selectbox("Cycle", list(CYCLES), format_func=CYCLES.get, index=1, key="mx_cycle")
        st.caption("Autumn-winter crops are planted Oct-Jan (irrigated Sinaloa and Sonora corn "
                   "and wheat); spring-summer crops Apr-Jul, mostly rainfed.")

    t1, t2, t5, t3, t6, t4 = st.tabs(["Satellite", "Production", "Yield model",
                                      "Monthly progress", "Areas and calendar", "Sources"])
    with t1:
        _satellite(state, cycle)
    with t2:
        _production(prod, state, crop, cycle)
    with t5:
        _model(prod, state, crop, cycle)
    with t3:
        _progress(prog, states_now, crop, cycle)
    with t6:
        production.areas_tab("Mexico", crop, CROPS[crop])
    with t4:
        st.markdown("""
**Satellite** - NOAA STAR Vegetation Health, state average of cropland pixels, weekly from
1982, labelled experimental. Baja California Sur returns no cropland series. The window is fixed
in advance by cycle (autumn-winter weeks 6-16, spring-summer weeks 29-38), not fitted. A state
average mixes crops and irrigated and rainfed land, so read it as a regional greenness signal.

**Production** - SIAP "Cierre de la producción agrícola" municipal open data (2003 onward),
summed to state, cycle and water regime. Final figures for completed years only.

**Monthly progress** - SIAP "Avance de siembras y cosechas" query tool, cumulative to month-end,
all water regimes combined, national. The latest month is provisional and is refetched each
refresh. Sown area is the cycle's total sown to date; harvested and lost area likewise.

**Yield model** - SIAP state yield (production over harvested area, 2003 onward) against the
year trend, with and without the mean NDVI over the cycle's fixed window. Skill is the cut in
leave-one-out error. Most states show none: a state-wide NDVI averages all crops and water
regimes. The current year is a forecast because SIAP publishes yields only after the year closes.

Refresh with `python build_data.py mxvh`, `mxprod`, `mxprog` and `mxstates`.
""")


def _yields(prod, state, crop, cycle):
    """SIAP state yield (t/ha, harvested area weighted) by year; thin years dropped."""
    d = prod[(prod["state"] == state) & (prod["crop"] == crop) & (prod["cycle"] == cycle)]
    g = d.groupby("year")[["harvested_ha", "volume_t"]].sum()
    g = g[g["harvested_ha"] >= 1000]
    return g["volume_t"] / g["harvested_ha"]


def _target_year(df, win):
    """Latest year whose crop window is complete in the NOAA series."""
    ly = int(df["year"].max())
    return ly if vh.window_mean(df, ly, win) is not None else ly - 1


@st.cache_data(ttl=3600)
def _scan(crop, cycle):
    """Trend vs trend + NDVI for every state that grows the crop in the cycle."""
    prod = _csv("mx_production.csv")
    win = vh.MX_WINDOWS[cycle]
    d = prod[(prod["crop"] == crop) & (prod["cycle"] == cycle)]
    last = int(d["year"].max())
    rows = []
    for state in d["state"].unique():
        y = _yields(prod, state, crop, cycle)
        if len(y) < 12 or state not in vh.MX_STATES.values() or state == "Baja California Sur":
            continue
        df = vh.load_mx(state)
        if df.empty:
            continue
        target = _target_year(df, win)
        m = vh.yield_model(df, None, {int(k): v for k, v in y.items() if k < target}, target,
                           win=win)
        vol = d[(d["state"] == state) & (d["year"] == last)]["volume_t"].sum()
        if m and m["predicted"] is not None:
            rows.append({"State": state, "Years": m["n"], f"{last} production (kt)": vol / 1000,
                         "Trend (t/ha)": m["trend_year"], "Trend + NDVI (t/ha)": m["predicted"],
                         "Skill vs trend": m["skill"], "Target year": target})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(f"{last} production (kt)", ascending=False)


def _model(prod, state, crop, cycle):
    if prod.empty:
        st.info("No SIAP production data. Run build_data.py mxprod.")
        return
    y = _yields(prod, state, crop, cycle)
    st.subheader(f"{state} {CROPS[crop]}, {CYCLES[cycle]}: trend vs trend plus greenness")
    if len(y) < 12:
        st.info(f"{state} has too few years of {CROPS[crop].lower()} yields in this cycle "
                f"({len(y)}) for a model.")
        return
    df = _vh(state)
    win = vh.MX_WINDOWS[cycle]
    target = _target_year(df, win)
    hist = {int(k): v for k, v in y.items() if k < target}
    m = vh.yield_model(df, None, hist, target, win=win)
    if not m or m["predicted"] is None:
        st.info("The satellite window has not finished, so there is no model estimate yet.")
        return
    last = int(y.index.max())
    c = st.columns(4)
    c[0].metric(f"Trend, {target}", f"{m['trend_year']:.2f} t/ha")
    c[1].metric(f"Trend + NDVI, {target}", f"{m['predicted']:.2f} t/ha")
    c[2].metric(f"Last SIAP yield ({last})", f"{y.loc[last]:.2f} t/ha")
    c[3].metric("Skill vs trend (leave-one-out)", f"{m['skill'] * 100:+.0f}%")
    if m["skill"] <= 0.03:
        st.warning("For this state and crop the satellite reading adds nothing measurable to the "
                   "yield trend: the leave-one-out error is no lower with NDVI. Use the trend.")
    note = (f"SIAP has not published {target} yields yet, so {target} is a forecast. "
            if target > last else "")
    st.caption(
        f"Fit on {m['n']} completed years (SIAP {int(y.index.min())}-{int(max(hist))}). The window "
        f"(weeks {win[0]}-{win[1]}) was fixed by cycle, not searched. Leave-one-out error is "
        f"{m['rmse_loo']:.2f} t/ha with NDVI against {m['rmse_trend_loo']:.2f} for trend alone. "
        "A state-wide NDVI averages every crop and both water regimes, so it dilutes the signal "
        f"for any one crop. {note}")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=y.index, y=y.values, mode="lines+markers", name="SIAP yield",
                             line=dict(color=GREY)))
    yrs = list(range(int(y.index.min()), target + 1))
    k, b0 = np.polyfit(list(hist), list(hist.values()), 1)
    fig.add_trace(go.Scatter(x=yrs, y=[k * v + b0 for v in yrs], name="Trend",
                             line=dict(color=AMBER, dash="dash")))
    fig.add_trace(go.Scatter(x=[target], y=[m["predicted"]], mode="markers", name="Trend + NDVI",
                             marker=dict(size=13, color=BLUE)))
    fig.update_layout(height=360, template="plotly_white", yaxis_title="t/ha",
                      margin=dict(t=30, b=30), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")
    with st.expander("How the satellite reading maps to yield", expanded=False):
        yrs_ = list(m["years"])
        sc = go.Figure()
        sc.add_trace(go.Scatter(
            x=m["x"], y=m["anomaly"], mode="markers+text", name="Years", customdata=yrs_,
            text=[str(v) if v >= 2018 or abs(a) > m["rmse_trend_loo"] * 1.5 else ""
                  for v, a in zip(yrs_, m["anomaly"])],
            textposition="top center", textfont=dict(size=9), marker=dict(size=8, color="#5e7164"),
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
                         xaxis_title="Mean NDVI over the window",
                         yaxis_title="Yield minus trend (t/ha)")
        st.plotly_chart(sc, width="stretch")
    st.subheader(f"Where the satellite helps: {CROPS[crop]}, {CYCLES[cycle]}, by state")
    scan = _scan(crop, cycle)
    if scan.empty:
        st.info("No state has enough history for this crop and cycle.")
        return
    st.dataframe(scan.head(15).style.format(
        {"Years": "{:.0f}", scan.columns[2]: "{:,.0f}", "Trend (t/ha)": "{:.2f}",
         "Trend + NDVI (t/ha)": "{:.2f}", "Skill vs trend": "{:+.0%}", "Target year": "{:.0f}"}),
        width="stretch", hide_index=True)
    helped = int((scan["Skill vs trend"] > 0.03).sum())
    st.caption("Skill is the cut in leave-one-out yield error from adding the window NDVI to the "
               f"trend; the satellite helps in {helped} of {len(scan)} states here. Sorted by "
               "latest SIAP production.")


def _satellite(state, cycle):
    df = _vh(state)
    ly, lw = vh.last_week(df)
    win = vh.MX_WINDOWS[cycle]
    st.caption(f"NOAA STAR Vegetation Health, {state} cropland only, through week {lw} of {ly} "
               f"(about {vh.week_start(ly, lw):%b %d}).")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="mx_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, _ = vh_chart(df, col, ly, span=(1, 52))
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, win[0])),
                  x1=pd.Timestamp(vh.week_start(2001, win[1] + 1)), fillcolor=BLUE, opacity=0.08,
                  line_width=0, annotation_text=f"{CYCLES[cycle]} window")
    fig.update_layout(title=f"{state} cropland, weekly {vh.LABEL[col]}", height=400,
                      template="plotly_white", margin=dict(t=50, b=30), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b %d")
    st.plotly_chart(fig, width="stretch")
    # the window can straddle the year-end only for autumn-winter crops reported at harvest,
    # so score the current window when it has finished and otherwise the last finished one
    year = ly if vh.window_mean(df, ly, win) is not None else ly - 1
    season = vh.season_table(df, None, year, win=win)
    if season.empty:
        return
    a, b = win
    st.markdown(f"**{CYCLES[cycle]} window: weeks {a} to {b} (about "
                f"{vh.week_start(year, a):%b %d} to "
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
        st.caption(f"Peak NDVI in {year} (any week): {pk[0]:.3f} in week {pk[1]}. Rank compares the same "
                   f"window in every year since {int(season['first'].iloc[0])}.")


def _production(prod, state, crop, cycle):
    if prod.empty:
        st.info("No SIAP production data. Run build_data.py mxprod.")
        return
    water = st.radio("Water regime", ["All", "Riego", "Temporal"], horizontal=True, key="mx_water",
                     format_func={"All": "All", "Riego": "Irrigated", "Temporal": "Rainfed"}.get)
    d = prod[(prod["crop"] == crop) & (prod["cycle"] == cycle)]
    if water != "All":
        d = d[d["water"].str.startswith(water)]
    nat = d.groupby("year")[["sown_ha", "harvested_ha", "volume_t"]].sum()
    st_ = d[d["state"] == state].groupby("year")[["sown_ha", "harvested_ha", "volume_t"]].sum()
    if st_.empty:
        st.info(f"{state} reports no {CROPS[crop].lower()} in the {CYCLES[cycle]} cycle"
                + ("" if water == "All" else f" ({water.lower()})") + ".")
    else:
        st_["yield"] = st_["volume_t"] / st_["harvested_ha"]
        last = int(st_.index.max())
        prev = st_.loc[last - 1] if last - 1 in st_.index else None
        c = st.columns(4)
        c[0].metric(f"{state} production, {last}", f"{st_.loc[last, 'volume_t'] / 1000:,.0f} kt",
                    f"{st_.loc[last, 'volume_t'] / prev['volume_t'] - 1:+.0%} vs {last - 1}"
                    if prev is not None and prev["volume_t"] else None)
        c[1].metric("Harvested area", f"{st_.loc[last, 'harvested_ha'] / 1000:,.0f} kha")
        c[2].metric("Yield", f"{st_.loc[last, 'yield']:.2f} t/ha")
        share = st_.loc[last, "volume_t"] / nat.loc[last, "volume_t"] if last in nat.index else None
        c[3].metric("Share of national", f"{share:.0%}" if share else "n/a")
        fig = go.Figure()
        fig.add_trace(go.Bar(x=st_.index, y=st_["volume_t"] / 1000, name="Production (kt)",
                             marker_color=BLUE, opacity=0.8))
        fig.add_trace(go.Scatter(x=st_.index, y=st_["yield"], name="Yield (t/ha)", yaxis="y2",
                                 line=dict(color=AMBER, width=3)))
        fig.update_layout(title=f"{state} {CROPS[crop]}, {CYCLES[cycle]}", height=380,
                          template="plotly_white", margin=dict(t=50, b=30),
                          yaxis=dict(title="kt"), yaxis2=dict(title="t/ha", overlaying="y",
                                                              side="right", showgrid=False),
                          legend=dict(orientation="h", y=-0.15))
        st.plotly_chart(fig, width="stretch")
    if len(nat):
        ny = int(nat.index.max())
        top = d[d["year"] == ny].groupby("state")[["sown_ha", "harvested_ha", "volume_t"]].sum()
        top = top.sort_values("volume_t", ascending=False).head(10)
        top["yield (t/ha)"] = top["volume_t"] / top["harvested_ha"]
        top["share"] = top["volume_t"] / nat.loc[ny, "volume_t"]
        st.subheader(f"Top states, {CROPS[crop]}, {CYCLES[cycle]}, {ny}")
        st.dataframe(top.rename(columns={"sown_ha": "sown (ha)", "harvested_ha": "harvested (ha)",
                                         "volume_t": "production (t)"}).style.format(
            {"sown (ha)": "{:,.0f}", "harvested (ha)": "{:,.0f}", "production (t)": "{:,.0f}",
             "yield (t/ha)": "{:.2f}", "share": "{:.0%}"}), width="stretch")
        fig = go.Figure(go.Scatter(x=nat.index, y=nat["volume_t"] / 1000, line=dict(color=GREY, width=3)))
        fig.update_layout(title=f"National {CROPS[crop]}, {CYCLES[cycle]}: production (kt)",
                          height=320, template="plotly_white", margin=dict(t=50, b=30))
        st.plotly_chart(fig, width="stretch")


def _progress(prog, states_now, crop, cycle):
    if prog.empty:
        st.info("No SIAP progress data. Run build_data.py mxprog.")
        return
    d = prog[(prog["crop"] == crop) & (prog["cycle"] == cycle)]
    if d.empty:
        st.info("No progress data for this crop and cycle.")
        return
    d = _seasonal(d, cycle)
    cur_season = int(d["season"].max())
    now = d[d["season"] == cur_season].sort_values("pos").iloc[-1]
    prior = d[(d["season"] == cur_season - 1) & (d["pos"] == now["pos"])]
    st.caption(f"National, all water regimes, {CYCLES[cycle]} {_season_label(cur_season, cycle)} "
               f"cycle, cumulative to the end of {MONTHS[int(now['month']) - 1]} {int(now['year'])} "
               "(the latest month is provisional).")
    c = st.columns(4)
    c[0].metric("Sown", f"{now['sown_ha'] / 1e6:.2f} M ha",
                f"{now['sown_ha'] / prior['sown_ha'].iloc[0] - 1:+.0%} vs a year earlier"
                if len(prior) and prior["sown_ha"].iloc[0] else None)
    c[1].metric("Harvested", f"{now['harvested_ha'] / 1e6:.2f} M ha")
    c[2].metric("Harvested share of sown",
                f"{now['harvested_ha'] / now['sown_ha']:.0%}" if now["sown_ha"] else "n/a")
    c[3].metric("Production so far", f"{now['volume_t'] / 1e6:.2f} Mt")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(_lines(d, "sown_ha", f"{CROPS[crop]}: sown area (ha)", "ha", cycle),
                        width="stretch")
    with right:
        d2 = d.assign(pct=d["harvested_ha"] / d["sown_ha"] * 100)
        st.plotly_chart(_lines(d2, "pct", f"{CROPS[crop]}: harvested share of sown",
                               "% of sown area", cycle), width="stretch")
    st.plotly_chart(_lines(d, "volume_t", f"{CROPS[crop]}: production to date (t)", "tonnes",
                           cycle), width="stretch")
    st.caption("Harvested shares in the first months of the 2025 spring-summer season are several "
               "times the 2018-2024 levels for the same month, which looks like a change in how "
               "SIAP reports early harvest; compare across that break with care.")
    if len(states_now):
        s = states_now[(states_now["crop"] == crop) & (states_now["cycle"] == cycle)]
        if len(s):
            y, m = int(s["year"].iloc[0]), int(s["month"].iloc[0])
            s = s.sort_values("volume_t", ascending=False).head(12).copy()
            s["harvested share"] = s["harvested_ha"] / s["sown_ha"]
            st.subheader(f"By state, to the end of {MONTHS[m - 1]} {y}")
            st.dataframe(s.drop(columns=["year", "month", "cycle", "crop"]).rename(columns={
                "sown_ha": "sown (ha)", "harvested_ha": "harvested (ha)", "lost_ha": "lost (ha)",
                "volume_t": "production (t)"}).style.format(
                {"sown (ha)": "{:,.0f}", "harvested (ha)": "{:,.0f}", "lost (ha)": "{:,.0f}",
                 "production (t)": "{:,.0f}", "harvested share": "{:.0%}"}),
                width="stretch", hide_index=True)

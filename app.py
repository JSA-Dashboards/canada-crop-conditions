"""Canada crop conditions and yield model (Alberta, Saskatchewan, Manitoba)."""
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import model as M
import tour
import vh

st.set_page_config(page_title="Canada crop conditions", page_icon=":material/grass:",
                   layout="wide")

BLUE, GREY, AMBER, RED = "#0693e3", "#32373c", "#f59e0b", "#d64545"
PROVINCES = {
    "Alberta": ["South", "Central", "N East", "N West", "Peace", "Alberta"],
    "Saskatchewan": ["Southeast", "Southwest", "East-central", "West-central", "Northeast",
                     "Northwest", "Saskatchewan"],
}
MB_REGIONS = ["Southwest", "Northwest", "Central", "Eastern", "Interlake", "Manitoba"]
TABLE_CROPS = ["Spring Wheat", "Durum", "Barley", "Oats", "Canola", "Flax", "Dry Peas",
               "Field Pea", "Lentil", "Soybean", "Major Crops", "All Crops", "5-yr avg",
               "10-yr avg"]


@st.cache_data(ttl=3600)
def load():
    return M.ab_reports(), M.sk_reports(), M.mb_reports(), M.yields()


ab, sk, mb, yl = load()
REPORTS = {"Alberta": ab, "Saskatchewan": sk}

st.title("Canada crop conditions and yield model")
st.caption("Provincial crop reports (Alberta, Saskatchewan, Manitoba) and Statistics Canada yields.")

with st.sidebar:
    prov = st.selectbox("Province", ["Alberta", "Saskatchewan", "Manitoba", "Ontario"])
    crop = st.selectbox("Crop", M.PROV_CROPS[prov])
    rated = prov in M.RATED
    if rated:
        regions = PROVINCES[prov]
        region = st.selectbox(f"{prov} region", regions, index=len(regions) - 1)
        rep = REPORTS[prov]
        years = sorted(rep["year"].unique()) if len(rep) else []
        if not years:
            st.error(f"No {prov} data. Run build_data.py.")
            st.stop()
    else:
        regions, region, rep = [], prov, None
        years = list(range(2020, int(vh.load(prov)["year"].max()) + 1))
    cur_year = st.selectbox("Year", years[::-1])
    st.caption("Alberta full ratings tables come every second week. Saskatchewan ratings exist "
               "from 2024. Manitoba and Ontario publish no numeric ratings; use the Satellite tab.")


def shade(lo, hi, rgb_lo, rgb_hi):
    """Cell colouring without matplotlib: blend rgb_lo -> rgb_hi between lo and hi."""
    def f(v):
        if pd.isna(v):
            return ""
        k = min(max((v - lo) / (hi - lo), 0), 1)
        r, g, b = (int(a + (c - a) * k) for a, c in zip(rgb_lo, rgb_hi))
        return f"background-color: rgb({r},{g},{b}); color: #111"
    return f


RED_GREEN = ((240, 150, 140), (150, 215, 150))
WHITE_BLUE = ((255, 255, 255), (110, 180, 235))


def year_lines(df, title, ylabel, yr):
    fig = go.Figure()
    for y in sorted(df["year"].unique()):
        d = df[df["year"] == y]
        cur = y == yr
        fig.add_trace(go.Scatter(
            x=d["season_date"], y=d["value"], name=str(y), mode="lines+markers",
            line=dict(width=4 if cur else 1.5, color=BLUE if cur else None),
            opacity=1 if cur else 0.55, marker=dict(size=7 if cur else 4)))
    fig.update_layout(title=title, yaxis_title=ylabel, height=380, template="plotly_white",
                      margin=dict(t=50, b=30), legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b %d")
    return fig


def province_compare(label):
    """Current-year provincial good-to-excellent: Alberta vs Saskatchewan."""
    fig = go.Figure()
    for p, color in (("Alberta", BLUE), ("Saskatchewan", AMBER)):
        s = M.series(REPORTS[p], "rating", label, p)
        s = s[s["year"] == cur_year]
        if len(s):
            fig.add_trace(go.Scatter(x=s["season_date"], y=s["value"], name=p,
                                     mode="lines+markers", line=dict(color=color, width=3)))
    fig.update_layout(title=f"{crop} good to excellent, {cur_year}: Alberta vs Saskatchewan",
                      yaxis_title="% good-excellent", height=320, template="plotly_white",
                      margin=dict(t=50, b=30), legend=dict(orientation="h", y=-0.2))
    fig.update_xaxes(tickformat="%b %d")
    return fig


@st.fragment
def tab_conditions():
    if not rated:
        st.info(f"{prov} publishes no numeric weekly condition ratings. "
                "The Satellite tab shows crop greenness against history.")
        return
    label = M.AB_LABEL[crop]
    s = M.series(rep, "rating", label, region)
    this = s[s["year"] == cur_year]
    if this.empty:
        st.info(f"No {prov} {crop} ratings for {cur_year} in this region.")
        return
    last = this.iloc[-1]
    prev = this.iloc[-2]["value"] if len(this) > 1 else np.nan
    doy = last["date"].dayofyear
    same_ly = M.rating_near(rep, label, region, cur_year - 1, doy=doy, window=8)[0]
    hist = [M.rating_near(rep, label, region, y, doy=doy, window=8)[0]
            for y in years if y < cur_year]
    oly = M.olympic_avg(hist)
    c = st.columns(4)
    c[0].metric(f"{crop} good-excellent, {region}", f"{last['value']:.0f}%",
                f"{last['value'] - prev:+.0f} pts vs prior report" if pd.notna(prev) else None)
    c[1].metric("Report date", last["date"].strftime("%b %d, %Y"))
    c[2].metric("vs last year (same week)",
                f"{last['value'] - same_ly:+.0f} pts" if pd.notna(same_ly) else "n/a")
    c[3].metric("vs olympic average",
                f"{last['value'] - oly:+.0f} pts" if pd.notna(oly) else "n/a")
    st.plotly_chart(year_lines(s, f"{prov} {crop} - % rated good to excellent ({region})",
                               "% good-excellent", cur_year), width="stretch")
    st.plotly_chart(province_compare(label), width="stretch")
    latest_date = this["date"].max()
    t = rep[(rep["kind"] == "rating") & (rep["date"] == latest_date)
            & rep["crop"].isin(TABLE_CROPS)]
    wide = t.pivot_table(index="crop", columns="region", values="value")
    wide = wide[[r for r in regions if r in wide.columns]]
    st.subheader(f"Regional ratings, {latest_date:%b %d, %Y}")
    st.dataframe(wide.style.format("{:.0f}%", na_rep="-").map(
        shade(20, 90, *RED_GREEN)), width="stretch")


@st.fragment
def tab_progress():
    if rated:
        label = M.AB_LABEL[crop]
        reg = region if len(M.series(rep, "seeding", label, region)) or len(
            M.series(rep, "harvest", label, region)) else prov
        c1, c2 = st.columns(2)
        for col, kind, word in ((c1, "seeding", "seeded"), (c2, "harvest", "harvested")):
            with col:
                s = M.series(rep, kind, label, reg)
                if len(s):
                    st.plotly_chart(year_lines(s, f"{prov} {crop} {word} ({reg})",
                                               f"% {word}", cur_year), width="stretch")
                else:
                    st.info(f"No {prov} {word} data parsed for {crop}.")
    else:
        st.info(f"{prov} progress is not parsed here. Manitoba harvest progress is below.")
    st.subheader("Manitoba harvest progress")
    if mb.empty:
        st.info("No Manitoba data. Run build_data.py mb.")
        return
    latest = mb["date"].max()
    m = mb[(mb["date"] == latest) & (mb["kind"] == "harvest")]
    wide = m.pivot_table(index="crop", columns="region", values="value")
    wide = wide[[r for r in MB_REGIONS if r in wide.columns]]
    st.caption(f"Manitoba Agriculture weekly report, harvest completion to {latest:%b %d, %Y}")
    st.dataframe(wide.style.format("{:.0f}%", na_rep="-").map(
        shade(0, 100, *WHITE_BLUE)), width="stretch")
    mc = M.series(mb, "harvest", M.MB_LABEL.get(crop, ""), "Manitoba")
    if len(mc):
        st.plotly_chart(year_lines(mc, f"Manitoba {M.MB_LABEL[crop]} harvest (province)",
                                   "% harvested", cur_year), width="stretch")


@st.fragment
def tab_yield():
    if not rated:
        st.info(f"{prov} has no weekly ratings to build on. The Satellite tab has a "
                "trend plus greenness yield model instead.")
        return
    res = M.build_model(crop, prov, cur_year)
    t = res["table"]
    st.subheader(f"{prov} {crop} yield: trend plus condition adjustment")
    c = st.columns(4)
    c[0].metric("Trend yield", f"{res['trend_cur']:.1f} bu/ac")
    c[1].metric("Condition model", f"{res['forecast']:.1f} bu/ac"
                if pd.notna(res["forecast"]) else "n/a",
                f"{res['low']:.1f} - {res['high']:.1f} (1 s.e.)"
                if pd.notna(res["forecast"]) else None, delta_color="off")
    c[2].metric("StatCan latest", f"{res['statcan_cur']:.1f} bu/ac"
                if pd.notna(res["statcan_cur"]) else "n/a")
    c[3].metric("Late-July rating", f"{res['rating_cur']:.0f}%"
                if pd.notna(res["rating_cur"]) else "n/a")
    if pd.notna(res["r2"]):
        st.caption(f"Fit on {res['n']} completed years: yield deviation from trend = "
                   f"{res['a']:.1f}% + {res['b']:.2f}% x rating point; R-squared "
                   f"{res['r2']:.2f}. This is a small sample - treat the range as indicative, "
                   "not precise.")
    else:
        st.warning("Not enough years with both a late-July rating and a final yield.")
    yh = yl[(yl["geo"] == prov) & (yl["crop"] == crop) & (yl["year"] >= 1990)]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=yh["year"], y=yh["bu_ac"], mode="lines+markers",
                             name="StatCan yield", line=dict(color=GREY)))
    yrs = np.arange(M.TREND_FROM, cur_year + 1)
    fig.add_trace(go.Scatter(x=yrs, y=res["slope"] * yrs + (res["trend_cur"]
                  - res["slope"] * cur_year), name="Trend", line=dict(color=AMBER, dash="dash")))
    if pd.notna(res["forecast"]):
        fig.add_trace(go.Scatter(x=[cur_year], y=[res["forecast"]], mode="markers",
                                 name="Condition model", marker=dict(size=13, color=BLUE),
                                 error_y=dict(type="data", symmetric=False,
                                              array=[res["high"] - res["forecast"]],
                                              arrayminus=[res["forecast"] - res["low"]])))
    fig.update_layout(height=380, template="plotly_white", yaxis_title="bu/ac",
                      margin=dict(t=30, b=30), legend=dict(orientation="h", y=-0.15))
    st.plotly_chart(fig, width="stretch")
    show = t.copy()
    show["rating_date"] = show["rating_date"].dt.strftime("%b %d").fillna("-")
    show = show.rename(columns={"rating": "G/E %", "rating_date": "report", "trend": "trend bu/ac",
                                "actual": "StatCan bu/ac", "dev_pct": "vs trend %"})
    st.dataframe(show.set_index("year").style.format(
        {"G/E %": "{:.0f}", "trend bu/ac": "{:.1f}", "StatCan bu/ac": "{:.1f}",
         "vs trend %": "{:+.1f}"}, na_rep="-"), width="stretch")
    ab_est = ab[(ab["kind"] == "yield") & (ab["region"] == "Alberta")
                & (ab["crop"] == M.AB_LABEL[crop]) & (ab["year"] == cur_year)]
    if prov == "Alberta" and len(ab_est):
        e = ab_est.sort_values("date").iloc[-1]
        st.info(f"Alberta Agriculture's own dryland survey estimate ({e['date']:%b %d}): "
                f"{e['value']:.1f} bu/ac. StatCan's figure is the model estimate until the "
                "December survey.")


@st.cache_data(ttl=3600)
def load_vh(province):
    return vh.load(province)


def vh_chart(df, col, year):
    """One index by week for `year` and the two before it, over the min-max band and the
    average of all earlier years."""
    m = vh.matrix(df, col)
    weeks = [w for w in m.index if 14 <= w <= 44]
    hist = m[[y for y in m.columns if y < year]].loc[weeks]
    x = [pd.Timestamp(vh.week_start(2001, w)) for w in weeks]  # common axis year
    fmt = ":.3f" if col == "SMN" else ":.1f"
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=hist.max(axis=1), line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=hist.min(axis=1), fill="tonexty", line=dict(width=0),
                             fillcolor="rgba(50,55,60,0.15)", hoverinfo="skip",
                             name=f"Range {hist.columns.min()}-{hist.columns.max()}"))
    fig.add_trace(go.Scatter(x=x, y=hist.mean(axis=1), name="Average",
                             line=dict(color=GREY, dash="dash"),
                             hovertemplate="Average: %{y" + fmt + "}<extra></extra>"))
    for yr, color, width, dash in ((year - 2, "#9ca3af", 1.5, "dot"), (year - 1, AMBER, 1.8, "solid"),
                                   (year, BLUE, 4, "solid")):
        if yr in m.columns:
            last = df[df["year"] == yr]["week"].max()
            s = m[yr].loc[weeks].where(lambda v: v.index <= last)
            fig.add_trace(go.Scatter(x=x, y=s, name=str(yr), line=dict(color=color, width=width,
                                                                          dash=dash)))
    return fig, weeks


@st.fragment
def tab_satellite():
    df = load_vh(prov)
    win = vh.WINDOWS[crop]
    if df[df["year"] == cur_year].empty:
        st.info(f"No satellite data for {prov} in {cur_year}.")
        return
    ly, lw = vh.last_week(df)
    st.caption(f"NOAA STAR Vegetation Health, {prov} cropland only, weekly, through week {lw} of "
               f"{ly} (about {vh.week_start(ly, lw):%b %d}). StatCan's own weekly NDVI table stopped "
               "in 2024, so this is the nearest current series. A province-wide average, not a "
               "county or field measure; NOAA labels it experimental.")
    col = st.radio("Index", ["SMN", "VCI", "VHI", "TCI"], horizontal=True, key="vh_index",
                   format_func=lambda c: vh.LABEL[c])
    fig, weeks = vh_chart(df, col, cur_year)
    fig.add_vrect(x0=pd.Timestamp(vh.week_start(2001, win[0])),
                  x1=pd.Timestamp(vh.week_start(2001, win[1] + 1)), fillcolor=BLUE,
                  opacity=0.08, line_width=0, annotation_text=f"{crop} window")
    fig.update_layout(title=f"{prov} cropland, weekly {vh.LABEL[col]}", height=400,
                      template="plotly_white", margin=dict(t=50, b=30), hovermode="x unified",
                      legend=dict(orientation="h", y=-0.15))
    fig.update_xaxes(tickformat="%b %d")
    st.plotly_chart(fig, width="stretch")

    season = vh.season_table(df, crop, cur_year)
    if not season.empty:
        a, b = win
        end = pd.Timestamp(vh.week_start(cur_year, b)) + pd.Timedelta(days=6)
        st.markdown(f"**{crop} crop window: weeks {a} to {b} (about "
                    f"{vh.week_start(cur_year, a):%b %d} to {end:%b %d})**")

        def f(c, v):
            return f"{v:.3f}" if c == "SMN" else f"{v:.1f}"
        st.dataframe(pd.DataFrame({
            "Index": [vh.LABEL[c] for c in season["index"]],
            str(cur_year): [f(c, v) for c, v in zip(season["index"], season["this_year"])],
            "Average": [f(c, v) for c, v in zip(season["index"], season["average"])],
            "Rank (1 = best)": [f"{r} of {n}" for r, n in zip(season["rank"], season["of"])]}),
            width="stretch", hide_index=True)
        pk, pk_prev = vh.peak(df, cur_year), vh.peak(df, cur_year - 1)
        if pk:
            st.caption(f"Peak NDVI this season: {pk[0]:.3f} in week {pk[1]}"
                       + (f"; last year {pk_prev[0]:.3f}" if pk_prev else "")
                       + f". Rank compares the same window in every year since "
                         f"{int(season['first'].iloc[0])}.")
    else:
        st.info("The crop window has not finished yet, so there is no window readout.")

    s = yl[(yl["geo"] == prov) & (yl["crop"] == crop)].dropna(subset=["bu_ac"])
    done = {int(a): b for a, b in zip(s["year"], s["bu_ac"]) if a < cur_year}
    mod = vh.yield_model(df, crop, done, cur_year)
    latest = s[s["year"] == cur_year]["bu_ac"]
    if not mod or mod["predicted"] is None:
        st.warning("Not enough data for the satellite yield model yet.")
        return
    st.subheader(f"{prov} {crop}: trend vs trend plus greenness")
    c = st.columns(4)
    c[0].metric("Trend yield", f"{mod['trend_year']:.1f} bu/ac")
    c[1].metric("Trend + NDVI", f"{mod['predicted']:.1f} bu/ac")
    c[2].metric("StatCan latest", f"{latest.iloc[0]:.1f} bu/ac" if len(latest) else "n/a")
    c[3].metric("Skill vs trend (leave-one-out)", f"{mod['skill'] * 100:+.0f}%")
    order = np.argsort(mod["x"])[::-1]
    top, bottom = mod["anomaly"][order[:10]].mean(), mod["anomaly"][order[-10:]].mean()
    rk = vh.season_rank(df, crop, cur_year)
    st.markdown(
        f"Using only the {cur_year} satellite reading and the yield trend, {prov} {crop.lower()} "
        f"yield would be about **{mod['predicted']:.1f} bu/ac** (trend alone "
        f"{mod['trend_year']:.1f}). **The signal is weak:** over {mod['n']} past years the "
        f"satellite term cuts the leave-one-out error from {mod['rmse_trend_loo']:.1f} to "
        f"{mod['rmse_loo']:.1f} bu/ac ({mod['skill']:.0%} better), and the window was fixed in "
        f"advance rather than searched for the best fit. Years with a top-10 window finished "
        f"{top:+.1f} bu/ac against trend on average, the 10 weakest {bottom:+.1f}."
        + (f" The {cur_year} window ranks {rk[2]} of {rk[3]}: a good year, not a record, so the "
           "satellite does not back a record-yield call." if rk and rk[2] > 3 else ""))
    with st.expander("How the satellite reading maps to yield", expanded=False):
        sc = go.Figure()
        yrs = list(mod["years"])
        sc.add_trace(go.Scatter(
            x=mod["x"], y=mod["anomaly"], mode="markers+text", name="Years",
            text=[str(y) if y >= 2010 or abs(a) > 8 else "" for y, a in zip(yrs, mod["anomaly"])],
            textposition="top center", textfont=dict(size=9), marker=dict(size=8, color="#5e7164"),
            customdata=yrs, hovertemplate="%{customdata}: NDVI %{x:.3f}, %{y:+.1f} bu/ac vs trend"
                                          "<extra></extra>"))
        k, i0 = np.polyfit(mod["x"], mod["anomaly"], 1)
        xs = [float(min(mod["x"])), float(max(mod["x"]))]
        sc.add_trace(go.Scatter(x=xs, y=[k * v + i0 for v in xs], mode="lines", name="Fit",
                                line=dict(color=AMBER, dash="dash")))
        if mod["x_now"] is not None:
            sc.add_vline(x=mod["x_now"], line_color=BLUE, line_width=2.5,
                         annotation_text=str(cur_year), annotation_font_color=BLUE)
        sc.update_layout(title=f"{crop} yield vs trend against the crop-window NDVI",
                         height=360, template="plotly_white", showlegend=False,
                         margin=dict(t=50, b=40), xaxis_title="Mean NDVI over the crop window",
                         yaxis_title="Yield minus trend (bu/ac)")
        st.plotly_chart(sc, width="stretch")
        st.caption(f"Each dot is a year: mean NDVI over weeks {win[0]}-{win[1]} against that "
                   "year's StatCan yield minus the linear yield trend. NDVI saturates when crops "
                   "are healthy, so it is better at flagging stress years than at ranking good ones.")


def fmt_pct(v):
    return "n/a" if pd.isna(v) else f"{v:+.0%}"


@st.fragment
def tab_estimates():
    s = yl[(yl["geo"] == prov) & (yl["crop"] == crop)].dropna(subset=["bu_ac"])
    sc_year = int(s["year"].max()) if len(s) else None
    st.subheader(f"{prov} {crop}: how fresh is the crop estimate?")
    if tour.available(crop) and prov == "Ontario" and sc_year:
        stat = {int(a): b for a, b in zip(s["year"], s["bu_ac"])}
        tbl = tour.table(crop, stat, sc_year)
        prod = float(s[s["year"] == sc_year]["prod_t"].iloc[0])
        ests = tour.estimates(tbl, crop, prod, sc_year)
        st.caption("StatCan's mid-September model is the latest official figure and its final "
                   "survey number comes in early December. The yield tour is an independent "
                   "August cross-check.")
        if ests:
            st.dataframe(pd.DataFrame([{
                "Estimate": e["label"], "Yield (bu/ac)": e["yield_bu"],
                f"{sc_year} production (kt)": e["kt"],
                "vs StatCan model": e["kt"] / ests[0]["kt"] - 1} for e in ests]).style.format(
                {"Yield (bu/ac)": "{:.1f}", f"{sc_year} production (kt)": "{:,.0f}",
                 "vs StatCan model": "{:+.1%}"}), width="stretch", hide_index=True)
        with st.expander("How the August yield tour has compared with StatCan", expanded=False):
            fin = tbl[tbl["final"]]
            f = tour.factor(tbl)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=tbl["year"], y=tbl["tour"], name="Yield tour (August)",
                                 marker_color=AMBER))
            fig.add_trace(go.Bar(x=tbl["year"], y=tbl["statcan"], name="StatCan (latest = model)",
                                 marker_color="#5e7164"))
            fig.update_layout(barmode="group", height=340, template="plotly_white",
                              title="Yield tour vs StatCan yield (bu/ac)", margin=dict(t=50, b=30),
                              legend=dict(orientation="h", y=-0.15))
            fig.update_xaxes(tickvals=list(tbl["year"]))
            st.plotly_chart(fig, width="stretch")
            st.markdown(
                f"Across {len(fin)} years ({fin['year'].min()}-{fin['year'].max()}) StatCan's final "
                f"yield has been **{f:.2f}x** the tour's (median), so the tour "
                f"{'has run high' if f < 0.97 else 'has been close to unbiased'} for "
                f"{crop.lower()}. After scaling by that ratio the typical miss is about "
                f"**{tour.miss(tbl):.1%}**. The {sc_year} tour is compared with StatCan's model, "
                "not a final figure.")
            st.caption(tour.SOURCE + ". The tour is a private sample, not a survey; the history is "
                       "typed in by hand and does not update itself.")
    else:
        st.info("The Great Ontario Yield Tour covers Ontario corn and soybeans only. For the "
                f"Prairies, StatCan's {sc_year} figure is the model estimate until December; see "
                "the Yield model and Satellite tabs.")
    st.subheader(f"{prov} {crop}: farm stocks")
    fs = M.farm_stocks(prov, crop)
    if fs.empty:
        st.info("No StatCan farm stocks for this selection.")
        return
    st.dataframe(pd.DataFrame({
        "Farm stocks": fs["date"], "kt": fs["kt"], "A year earlier": fs["year_ago"],
        "Prior 5-yr average": fs["avg5"], "vs a year ago": fs["vs_year_ago"],
        "vs 5-yr average": fs["vs_avg5"]}).style.format(
        {"kt": "{:,.0f}", "A year earlier": "{:,.0f}", "Prior 5-yr average": "{:,.0f}",
         "vs a year ago": "{:+.0%}", "vs 5-yr average": "{:+.0%}"}, na_rep="n/a"),
        width="stretch", hide_index=True)
    note = " Spring wheat uses all wheat except durum, including winter wheat." \
        if crop == "Spring wheat" else ""
    st.caption(f"StatCan table 32-10-0007-01, through {fs['date'].iloc[-1]}: stocks on farms in "
               f"{prov}. Commercial stocks are not published by province." + note)


def tab_sources():
    st.markdown("""
**Satellite** - NOAA STAR Vegetation Health (province average of cropland pixels, weekly from
1982, labelled experimental). StatCan's own NDVI tables stopped in 2021 and May 2024.

**Farm stocks** - StatCan table 32-10-0007-01 (Mar 31, Jul 31, Dec 31, farm stocks only).

**Yield tour** - Great Ontario Yield Tour (Farms.com), typed in by hand each August.

**Ontario** - no weekly ratings are published, so corn and soybeans use the satellite model
and StatCan yields. County production and the supply balance are in the Soy Crush Calculator.
""")
    st.markdown("""
**Alberta** - Alberta Agriculture and Irrigation weekly crop report PDFs on open.alberta.ca
(ratings, seeding, harvest, dryland yield estimates). Full tables appear every second week.

**Saskatchewan** - Ministry of Agriculture weekly crop report PDFs on
publications.saskatchewan.ca: good plus excellent from the crop condition tables by crop and
region. Seeding and harvest progress are read from the report text (provincial, partial for
seeding).

**Manitoba** - Manitoba Agriculture weekly crop report PDFs: harvest completion by crop and
region. Manitoba does not publish numeric condition ratings.

**Yields** - Statistics Canada table 32-10-0359-01. The current year is a model estimate
until the December survey and is kept out of the model fit.

Refresh data with `python build_data.py ab`, `sk`, `mb`, `vh`, `stocks` and `yields`.
""")


t1, t2, t3, t4, t6, t5 = st.tabs(["Conditions", "Progress", "Yield model", "Satellite",
                                  "Estimates and stocks", "Sources"])
with t1:
    tab_conditions()
with t2:
    tab_progress()
with t3:
    tab_yield()
with t4:
    tab_satellite()
with t6:
    tab_estimates()
with t5:
    tab_sources()

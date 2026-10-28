"""Production-area maps: USDA-style choropleths of 3-year-average production by state/province."""
import json
import unicodedata
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

GEO = Path(__file__).parent / "data" / "geo"
SAGE_SCALE = [[0, "#e6f4e1"], [0.35, "#7bc47f"], [0.7, "#2e9e45"], [1, "#0b5d1e"]]


def key(name):
    """Join key for names across sources: accents, case, spaces and hyphens ignored."""
    s = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in s if ch.isalnum())


@st.cache_data(show_spinner=False)
def load(iso):
    return json.loads((GEO / f"{iso}.geojson").read_text(encoding="utf-8"))


@st.cache_data(show_spinner=False)
def centroids(iso):
    """key -> (lon, lat) label position of each unit (computed by build_geo.py)."""
    return {f["properties"]["key"]: (f["properties"]["lon"], f["properties"]["lat"])
            for f in load(iso)["features"]}


def production_map(iso, df, unit, title, label_top=8, fit_to_data=True):
    """df: columns name, value (3-yr-average production in `unit`). Shares of the national total
    are printed on the biggest units, as on the USDA maps."""
    gj = load(iso)
    d = df.copy()
    d["key"] = d["name"].map(key)
    total = d["value"].sum()
    d["share"] = d["value"] / total * 100 if total else 0
    names = {f["properties"]["key"]: f["properties"]["name"] for f in gj["features"]}
    d["place"] = d["key"].map(names).fillna(d["name"])
    fig = go.Figure(go.Choropleth(
        geojson=gj, featureidkey="properties.key", locations=d["key"], z=d["value"],
        colorscale=SAGE_SCALE, marker_line_color="#ffffff", marker_line_width=0.6,
        colorbar=dict(title=unit, thickness=12, len=0.6),
        customdata=d[["place", "share"]],
        hovertemplate="%{customdata[0]}<br>%{z:,.0f} " + unit + "<br>%{customdata[1]:.1f}% of total<extra></extra>"))
    top = d.sort_values("value", ascending=False).head(label_top)
    cen = centroids(iso)
    top = top[top["key"].isin(cen)]
    fig.add_trace(go.Scattergeo(
        lon=[cen[k][0] for k in top["key"]], lat=[cen[k][1] for k in top["key"]], mode="text",
        text=[f"{p}<br>{sh:.0f}%" for p, sh in zip(top["place"], top["share"])],
        textfont=dict(size=10, color="#1f2a22"), hoverinfo="skip", showlegend=False))
    fig.update_geos(fitbounds="locations" if fit_to_data else "geojson", visible=False,
                    bgcolor="rgba(0,0,0,0)")
    fig.update_layout(title=title, height=520, margin=dict(t=50, b=10, l=0, r=0),
                      paper_bgcolor="#ffffff")
    return fig, d.sort_values("value", ascending=False)


def top_table(d, unit, n=10):
    t = d.head(n)[["place", "value", "share"]].rename(
        columns={"place": "Area", "value": unit, "share": "% of total"})
    st.dataframe(t.style.format({unit: "{:,.0f}", "% of total": "{:.1f}%"}), hide_index=True,
                 width="stretch")

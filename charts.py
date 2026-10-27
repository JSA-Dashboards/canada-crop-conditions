"""Plotly chart builders shared by the Canada and Mexico views."""
import pandas as pd
import plotly.graph_objects as go

import vh

BLUE, GREY, AMBER = "#0693e3", "#32373c", "#f59e0b"


def vh_chart(df, col, year, span=(14, 44)):
    """One index by week for `year` and the two before it, over the min-max band and the
    average of all earlier years, for weeks `span`. Returns (figure, weeks)."""
    m = vh.matrix(df, col)
    weeks = [w for w in m.index if span[0] <= w <= span[1]]
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
            fig.add_trace(go.Scatter(x=x, y=s, name=str(yr),
                                     line=dict(color=color, width=width, dash=dash)))
    return fig, weeks

"""Look shared with the CFTC COT dashboard (sage palette, EB Garamond headings, bordered tiles).

Call apply() once, right after st.set_page_config. The Plotly built-in "plotly_white" template is
adjusted in place, so every figure that asks for it picks up the palette without per-chart edits.
"""
import plotly.io as pio
import streamlit as st

import titles

JSA_GREEN = "#5e7164"
BG, SURFACE, BORDER = "#f6f8f7", "#ffffff", "#d7e2dc"
TEXT, MUTED = "#32373c", "#5f7267"
COLORWAY = ["#6fa8c4", "#c4785a", "#5e7164", "#9b89c4", "#b8c4bc", "#d9a441", "#7bb661"]
LOGO = "https://www.jpsi.com/wp-content/themes/gate39media/img/logo-full.png"


def _plotly():
    t = pio.templates["plotly_white"]
    t.layout.update(colorway=COLORWAY, font=dict(color=TEXT), paper_bgcolor=SURFACE,
                    plot_bgcolor=SURFACE)
    axis = dict(gridcolor=BORDER, linecolor=BORDER, zerolinecolor=BORDER,
                tickfont=dict(color=MUTED, size=11), title_font=dict(color=MUTED, size=11))
    t.layout.xaxis.update(**axis)
    t.layout.yaxis.update(**axis)


def apply(title="Crop Conditions and Yields", subtitle="Satellite, Reports and Yield Models"):
    _plotly()
    titles.apply()
    st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=EB+Garamond:wght@500;600&family=Source+Sans+3:wght@400;600;700&display=swap');
html, body, [data-testid="stAppViewContainer"] {{ background-color:{BG}; color:{TEXT}; }}
html, body, p, span, div, label, button, td, th {{ font-family:'Source Sans 3','Source Sans Pro',sans-serif; }}
[data-testid="stSidebar"] {{ background-color:{SURFACE}; border-right:1px solid {BORDER}; }}
.block-container {{ padding-top: 3.2rem; max-width: 1400px; }}
h1, h2, h3, h1 *, h2 *, h3 * {{ font-family:'EB Garamond',Georgia,serif !important; color:{TEXT}; font-weight:600; }}
.dash-header {{ display:flex; align-items:center; gap:18px; padding-bottom:10px;
    border-bottom:1px solid {BORDER}; margin-bottom:14px; }}
.dash-header img {{ height:40px; }}
.dash-header .t b {{ font-family:'EB Garamond',Georgia,serif; font-size:1.7rem; color:{TEXT}; font-weight:600; }}
.dash-header .t div {{ font-size:.85rem; color:{MUTED}; }}
@media (max-width: 640px) {{ .dash-header img {{ display:none; }} }}
[data-testid="stMetric"] {{ background:{SURFACE}; border:1px solid {BORDER}; border-top:3px solid {JSA_GREEN};
    border-radius:10px; padding:14px 18px; }}
[data-testid="stMetricLabel"] p {{ color:{MUTED}; font-size:0.7rem; text-transform:uppercase; letter-spacing:0.09em; }}
[data-testid="stMetricValue"] {{ color:{TEXT}; font-weight:700; }}
[data-testid="stCaptionContainer"] {{ color:{MUTED}; }}
hr {{ border-color:{BORDER}; }}
#MainMenu, footer {{ visibility:hidden; }}
.stDeployButton {{ display:none; }}
</style>
<div class="dash-header">
  <img src="{LOGO}">
  <div class="t"><b>{title}</b><div>{subtitle} &middot; John Stewart &amp; Associates</div></div>
</div>
""", unsafe_allow_html=True)

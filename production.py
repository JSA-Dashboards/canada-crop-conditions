"""'Areas and calendar' tab for every country: where the selected crop is grown (USDA-style map of
3-year-average production by state/province) and its planting-growth-harvest timeline."""
from pathlib import Path

import pandas as pd
import streamlit as st

import geo
import json

DATA = Path(__file__).parent / "data"
BR_UF = {"AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá", "BA": "Bahia",
         "CE": "Ceará", "DF": "Distrito Federal", "ES": "Espírito Santo", "GO": "Goiás",
         "MA": "Maranhão", "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
         "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí", "PR": "Paraná",
         "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte", "RO": "Rondônia", "RR": "Roraima",
         "RS": "Rio Grande do Sul", "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
         "TO": "Tocantins"}
FR_NATIONAL = {"France", "DROM", "Guyane", "La Réunion", "Martinique"}


@st.cache_data(ttl=3600, show_spinner=False)
def _csv(name):
    p = DATA / name
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _avg(df, name_col, year_col, value_col, n=3, last=None):
    """Average of the last n years per area: returns (frame name/value, 'YYYY-YYYY' label)."""
    yrs = sorted(df[year_col].dropna().unique())
    if last is not None:
        yrs = [y for y in yrs if y <= last]
    yrs = yrs[-n:]
    d = df[df[year_col].isin(yrs)].groupby([name_col, year_col])[value_col].sum().reset_index()
    out = d.groupby(name_col)[value_col].sum().div(len(yrs)).reset_index()
    out.columns = ["name", "value"]
    label = f"{int(yrs[0])}-{int(yrs[-1])}" if len(yrs) > 1 else f"{int(yrs[0])}"
    return out[out["value"] > 0], label


# -- one provider per country: (crop) -> (frame, years label, unit) or None ------------------------
def _canada(crop):
    y = _csv("yields.csv")
    d = y[(y["crop"] == crop) & ~y["geo"].isin(["Canada", "Prairie provinces"]) & y["prod_t"].notna()]
    if d.empty:
        return None
    # the newest year is a model estimate until December: leave it out of the average
    f, lab = _avg(d, "geo", "year", "prod_t", last=d["year"].max() - 1)
    return f, lab, "t"


def _mexico(crop):
    p = _csv("mx_production.csv")
    d = p[p["crop"] == crop].copy()
    if d.empty:
        return None
    d["state"] = d["state"].replace({"Ciudad de México": "Distrito Federal",
                                     "Ciudad de México / DF": "Distrito Federal"})
    f, lab = _avg(d, "state", "year", "volume_t")
    return f, lab, "t"


def _brazil(crop):
    s = _csv("br_series.csv")
    d = s[(s["crop"] == crop) & (~s["forecast"]) & (s["uf"] != "BRASIL")].copy()
    if d.empty:
        return None
    d["name"] = d["uf"].map(BR_UF)
    d["prod_t"] = d["prod_kt"] * 1000
    f, lab = _avg(d.dropna(subset=["name"]), "name", "start_year", "prod_t")
    return f, lab, "t"


def _argentina(crop):
    y = _csv("ar_yields.csv")
    d = y[y["crop"] == crop]
    if d.empty:
        return None
    f, lab = _avg(d, "provincia", "start_year", "prod_t")
    return f, lab, "t"


def _france(crop):
    y = _csv("fr_yields.csv")
    d = y[(y["crop"] == {"Winter barley": "Barley"}.get(crop, crop)) & ~y["area"].isin(FR_NATIONAL)].copy()
    if d.empty:
        return None
    d["prod_t"] = d["area_ha"] * d["yield_qha"] / 10
    f, lab = _avg(d, "area", "year", "prod_t")
    return f, lab, "t"


def _south_africa(crop):
    r = _csv("za_cec_records.csv")
    f = r[(r["crop"] == crop) & r["prod_prev"].notna() & (r["province"] != "Total")].copy()
    if f.empty:
        return None
    f["fy"] = f["year"] - 1  # each release carries the previous season's final
    f = f.sort_values("release").drop_duplicates(["fy", "province"], keep="last")
    out, lab = _avg(f, "province", "fy", "prod_prev")
    return out, lab, "t"


PROVIDERS = {"Canada": ("CAN", _canada), "Mexico": ("MEX", _mexico), "Brazil": ("BRA", _brazil),
             "Argentina": ("ARG", _argentina), "France": ("FRA", _france),
             "South Africa": ("ZAF", _south_africa)}

# -- crop calendars: label -> 12 letters, January to December. P planting, G growing, H harvest,
# . nothing. Typical windows for the main producing zone; a given year moves by a few weeks. ----------
CAL = {
    "Brazil": {
        "Corn 1st crop": [("Corn - 1st crop", "GHHHHH...PPP")],
        "Corn 2nd crop": [("Corn - 2nd crop", "PPGGGHHHH...")],
        "Soybeans": [("Soybeans", "HHHHHH..PPPP")],
        "Wheat": [("Wheat (south)", "....PPGGGHHH")],
    },
    "Argentina": {
        "Corn": [("Corn", "PGGHHHHHPPPP")],
        "Soybeans": [("Soybeans - 1st", "GGGHH.....PP"), ("Soybeans - 2nd", "GGGGHH.....P")],
        "Sunflower": [("Sunflower", "GGHH....PPGG")],
        "Sorghum": [("Sorghum", "GGGHHH...PPP")],
        "Wheat": [("Wheat", "H...PPPGGGGH")],
    },
    "Canada": {
        "Canola": [("Canola", "....PPGHHH..")],
        "Spring wheat": [("Spring wheat", "....PPGHHH..")],
        "Durum": [("Durum", "....PPGHHH..")],
        "Barley": [("Barley", "....PPGHHH..")],
        "Corn": [("Corn (Ontario)", "....PPGGGHH.")],
        "Soybeans": [("Soybeans (Ontario)", "....PPGGGHH.")],
    },
    "Mexico": {
        "Maíz grano": [("Corn - spring-summer", "HH.PPPPPGHHH"),
                       ("Corn - autumn-winter", "PPGHHHH...PP")],
        "Sorgo grano": [("Sorghum - autumn-winter", "PPHHHHH..PPP"),
                        ("Sorghum - spring-summer", "HH.PPPPPPHHH")],
        "Trigo grano": [("Wheat - autumn-winter", "PPGHHHH...PP")],
        "Soya": [("Soybeans - spring-summer", "HH...PPPGGHH")],
        "Frijol": [("Dry beans - spring-summer", "......PPGGHH"),
                   ("Dry beans - autumn-winter", "GHHH......PP")],
        "Cebada grano": [("Barley - autumn-winter", "PPPHHHH....P")],
        "Garbanzo grano": [("Chickpeas - autumn-winter", "GGHHHH....PP")],
        "Cártamo": [("Safflower - autumn-winter", "GGGHHHHH..PP")],
    },
    "France": {
        "Soft wheat": [("Soft wheat", "GGGGGHHHPPPP")],
        "Winter barley": [("Winter barley", "GGGGGHH.PPGG")],
        "Grain maize": [("Grain maize", "..PPPGGGHHHH")],
    },
    "South Africa": {
        "Maize": [("Maize", "GGGGHHHH.PPP")],
        "Soybeans": [("Soybeans", "GGGHHH...PPP")],
        "Sunflower": [("Sunflower", "PGGHH.....PP")],
        "Sorghum": [("Sorghum", "PGGGGH.....P")],
        "Wheat": [("Wheat", "....PPGGGHH.")],
    },
}
assert all(len(pat) == 12 and set(pat) <= set("PGH.") for c in CAL.values() for v in c.values()
           for _, pat in v), "calendar pattern must be 12 letters of P/G/H/."
CAL_NOTE = {
    "Brazil": "Windows follow USDA FAS's crop calendar for Brazil (shown below). USDA shows no "
              "mid-season stage for soybeans.",
    "Argentina": "Windows follow USDA FAS's crop calendars for Argentina (shown below); the 2nd "
                 "soybean crop is read from the same calendar.",
    "Canada": "Windows follow USDA FAS's crop calendar for Canada (shown below) and match the "
              "Alberta and Saskatchewan weekly seeding and harvest series. Ontario corn and "
              "soybeans use the same national calendar.",
    "Mexico": "Windows follow USDA FAS's crop calendars for Mexico (shown below). Dry beans, "
              "chickpeas and safflower are not on USDA's calendar: they come from SIAP's monthly "
              "sown and harvested area.",
    "France": "Windows follow USDA FAS's crop calendars for the European Union (shown below, "
              "the nearest USDA publishes), and match Cere'Obs maize sowing and harvest stages.",
    "South Africa": "Windows follow USDA FAS's crop calendars for South Africa (shown below). "
                    "Maize is shown for the East and West regions combined.",
}
START_MONTH = {"Brazil": 7, "Argentina": 7, "South Africa": 7, "France": 7, "Canada": 1, "Mexico": 1}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
COLORS = {"P": "#19a24a", "G": "#bdbdbd", "H": "#f5b800", ".": "#ffffff"}
FLAT = {"Brazil": "Brazil", "Argentina": "Argentina", "Canada": "Canada", "Mexico": "Mexico",
        "France": "France", "South Africa": "South Africa"}


def calendar_html(country, crop):
    """All of the country's crops, the selected crop's rows in bold and the rest dimmed."""
    start = START_MONTH[country]
    order = [(start - 1 + i) % 12 for i in range(12)]
    head = "".join(f"<th style='font-weight:600;color:#5f7267;font-size:12px;padding:2px 0'>"
                   f"{MONTHS[m]}</th>" for m in order)
    rows = []
    for ckey, items in CAL[country].items():
        for label, pat in items:
            on = ckey == crop
            cells = "".join(
                f"<td style='background:{COLORS[pat[m]]};height:20px;border:1px solid #d7e2dc'></td>"
                for m in order)
            style = "font-weight:700;color:#32373c" if on else "font-weight:400;color:#8a9a90"
            op = "1" if on else "0.45"
            rows.append(f"<tr style='opacity:{op}'><td style='{style};padding:2px 10px 2px 0;"
                        f"white-space:nowrap;font-size:13px'>{label}</td>{cells}</tr>")
    legend = "".join(
        f"<span style='display:inline-block;width:14px;height:14px;background:{COLORS[k]};"
        f"border:1px solid #d7e2dc;vertical-align:middle;margin:0 4px 0 14px'></span>{t}"
        for k, t in (("P", "Planting"), ("G", "Growth"), ("H", "Harvest")))
    return (f"<table style='width:100%;border-collapse:collapse;table-layout:fixed'>"
            f"<colgroup><col style='width:190px'>{'<col>' * 12}</colgroup>"
            f"<tr><th></th>{head}</tr>{''.join(rows)}</table>"
            f"<div style='font-size:13px;color:#5f7267;margin-top:8px'>{legend}</div>")


@st.cache_data(ttl=3600, show_spinner=False)
def _usda_maps():
    p = DATA / "usda_maps.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def usda_map(country, crop, label):
    """USDA FAS's own production map for the crop, shown as published (never redrawn), with credit.
    Returns True when a map was shown."""
    m = _usda_maps()
    options = m.get("maps", {}).get(country, {}).get(crop, [])
    if not options:
        return False
    pick = options[0]
    if len(options) > 1:
        names = [o["label"] for o in options]
        choice = st.selectbox("USDA map", names, key=f"usda_map_{country}_{crop}")
        pick = options[names.index(choice)]
    shown = f'{m["thumb"]}{pick["path"]}?itok={pick["token"]}' if pick.get("token") else m["site"] + pick["path"]
    st.image(shown, width=650)
    page = m["pages"][country]
    who = "the European Union (USDA publishes no France-only map)" if country == "France" else country
    st.caption(f"Source: [USDA Foreign Agricultural Service, International Production Assessment Division]"
               f"({page}), crop production maps for {who}, {m['month']} release. Maps are USDA's, shown "
               "unaltered: production as a 3-year average, with each area's share of national production. "
               f"[Full-size image]({m['site'] + pick['path']}).")
    return True


@st.fragment
def areas_tab(country, crop, crop_label=None):
    """Render the map and the calendar for `crop` (the key the country's own selector uses)."""
    iso, provider = PROVIDERS[country]
    label = crop_label or crop
    st.subheader(f"{country} {label} Production Areas")
    if usda_map(country, crop, label):
        _calendar(country, crop, label)
        return
    st.caption("USDA publishes no map for this crop here, so this is JSA's own map of the same data "
               "the models use.")
    got = provider(crop)
    if got is None or got[0].empty:
        st.info(f"No production-by-area data for {label}.")
    else:
        d, years, unit = got
        fig, ranked = geo.production_map(iso, d, unit, f"{label}: production by area, {years} average")
        left, right = st.columns([3, 2])
        with left:
            st.plotly_chart(fig, width="stretch")
        with right:
            geo.top_table(ranked, "Avg production (t)")
        st.caption(f"Average annual production {years}, from the same series the yield model uses. "
                   "Shading shows tonnes; the table gives each area's share of the national total. "
                   "Boundaries: Natural Earth (public domain).")
    _calendar(country, crop, label)


def _calendar(country, crop, label):
    st.subheader(f"{country} {label} Crop Calendar")
    st.markdown(calendar_html(country, crop), unsafe_allow_html=True)
    st.caption(CAL_NOTE[country] + " A given year runs a few weeks early or late. The selected crop is "
               "highlighted.")
    _usda_calendars(country)


def _usda_calendars(country):
    """USDA FAS's own crop calendar pictures for the country, shown as published, with credit."""
    m = _usda_maps()
    cals = m.get("calendars", {}).get(country, [])
    if not cals:
        return
    st.subheader(f"USDA Crop Calendar: {country}")
    for c in cals:
        url = f'{m["thumb"]}{c["path"]}?itok={c["token"]}' if c.get("token") else m["site"] + c["path"]
        st.image(url, width=650)
    who = "the European Union (USDA publishes no France-only calendar)" if country == "France" else country
    st.caption(f"Source: [USDA Foreign Agricultural Service, International Production Assessment Division]"
               f"({m['pages'][country]}), crop calendars for {who}, {m['month']} release, shown unaltered. "
               "Planting, growth and harvest by month for the main crops.")

"""Build the Canada crop conditions data files (data/*.csv).

    python build_data.py yields            # StatCan 32-10-0359-01 -> data/yields.csv
    python build_data.py ab [year ...]     # Alberta weekly PDFs  -> data/ab_reports.csv
    python build_data.py mb [year ...]     # Manitoba weekly PDFs -> data/mb_reports.csv
    python build_data.py sk [year ...]     # Saskatchewan weekly PDFs -> data/sk_reports.csv
    python build_data.py vh                # NOAA satellite crop condition -> data/vh.csv
    python build_data.py stocks            # StatCan farm stocks (32-10-0007-01) -> data/stocks.csv
    python build_data.py frcereobs|fragreste|frvh|frmars   # France: Céré'Obs maize, Agreste estimates, NOAA by region
    python build_data.py mxprod|mxprog|mxstates|mxvh   # Mexico: SIAP production, SIAP monthly progress, state table, NOAA by state

Reports are parsed incrementally: report dates already in a CSV are skipped.
"""
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pdfplumber
import requests

HERE = Path(__file__).parent
DATA = HERE / "data"
UA = {"User-Agent": "Mozilla/5.0"}

AB_REGIONS = ["South", "Central", "N East", "N West", "Peace", "Alberta"]
MB_REGIONS = ["Southwest", "Northwest", "Central", "Eastern", "Interlake", "Manitoba"]
MB_URL = ("https://www.manitoba.ca/agriculture/crops/seasonal-reports/"
          "crop-report/pubs/crop-report-{d}.pdf")
YIELD_GEOS = ["Alberta", "Saskatchewan", "Manitoba", "Ontario", "Prairie provinces", "Canada"]
YIELD_CROPS = {
    "Canola (rapeseed)": "Canola", "Wheat, spring": "Spring wheat",
    "Wheat, durum": "Durum", "Barley": "Barley", "Corn for grain": "Corn",
    "Soybeans": "Soybeans", "Wheat, all": "All wheat",
}

TOKEN = re.compile(r"(?<![\w.])(-|\d+(?:\.\d+)?)%?(?![\w.])")


def _get(url):
    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    return r.content


def _row_label_values(row):
    """Label = first non-empty cell; values = numeric/dash tokens in the rest."""
    cells = [c for c in row]
    for i, c in enumerate(cells):
        if c and c.strip():
            label = c.strip().replace("\n", " ")
            rest = " ".join(x for x in cells[i + 1:] if x)
            vals = [None if t == "-" else float(t) for t in TOKEN.findall(rest)]
            return label, vals
    return None, []


def _clean_label(label):
    """Normalise row labels: the reports vary wording year to year."""
    label = re.sub(r"[^ -~]", "", label)  # symbol-font asterisks etc.
    low = re.sub(r"[\s*()]+", " ", label.lower()).strip()
    if "average" in low or "avg" in low:
        m = re.search(r"(5|10)[- ]?y", low)
        return f"{m.group(1)}-yr avg" if m else label.strip()
    is_last = "last year" in low or bool(re.search(r"(19|20)\d\d", low))
    if low.replace(" ", "").startswith("majorcro"):
        return "Major Crops (last year)" if is_last else "Major Crops"
    if low.replace(" ", "").startswith("allcrops"):
        return "All Crops (last year)" if is_last else "All Crops"
    if low.startswith("durum"):
        return "Durum"
    return label.replace("*", "").strip(" ,")


def _kind(table):
    head = " ".join(" ".join(c for c in r if c) for r in table[:2]).lower().replace("-", " ")
    if "good to excellent" in head:
        return "rating"
    if "% seeded" in head:
        return "seeding"
    if "harvested" in head or "crops combined" in head:
        return "harvest"
    if "dryland yield" in head or "estimated yield" in head:
        return "yield"
    return None


def parse_ab_pdf(content, report_date):
    rows = []
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            for t in page.extract_tables():
                kind = _kind(t)
                if not kind:
                    continue
                for r in t[1:]:
                    label, vals = _row_label_values(r)
                    if not label or len(vals) < 6 or label in AB_REGIONS:
                        continue
                    label = _clean_label(label)
                    for reg, v in zip(AB_REGIONS, vals[:6]):
                        if v is not None:
                            rows.append((report_date, kind, label, reg, v))
    return rows


def parse_mb_pdf(content, report_date):
    rows = []
    crops = {"Winter Wheat", "Fall Rye", "Spring Wheat", "Barley", "Oats", "Field Pea",
             "Canola", "Dry Bean", "Potatoes", "Soybeans", "Corn", "Sunflowers", "Flax",
             "Regional AVG"}
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page in pdf.pages:
            txt = page.extract_text() or ""
            if "Percentage of Harvest Completion" not in txt:
                continue
            for t in page.extract_tables():
                if not t or not t[0] or "Southwest" not in " ".join(c or "" for c in t[0]):
                    continue
                for r in t[1:]:
                    label, vals = _row_label_values(r)
                    if label not in crops or len(vals) < 6:
                        continue
                    label = "All crops" if label == "Regional AVG" else label
                    for reg, v in zip(MB_REGIONS, vals[:6]):
                        if v is not None:
                            rows.append((report_date, "harvest", label, reg, v))
    return rows


def _load(path):
    return pd.read_csv(path) if path.exists() else pd.DataFrame(
        columns=["date", "kind", "crop", "region", "value"])


def _save(df, path):
    df = df.drop_duplicates(["date", "kind", "crop", "region"]).sort_values(
        ["date", "kind", "crop", "region"])
    DATA.mkdir(exist_ok=True)
    df.to_csv(path, index=False)
    print(f"{path.name}: {len(df):,} rows, {df['date'].nunique()} reports")


def ab_datasets():
    """One Open Alberta dataset per crop year: {year: dataset id} via the CKAN API."""
    r = requests.get("https://open.alberta.ca/api/3/action/package_search", headers=UA,
                     params={"q": 'title:"alberta crop report"', "rows": 50}, timeout=60)
    out = {}
    for d in r.json()["result"]["results"]:
        m = re.fullmatch(r"Alberta crop report \[(\d{4})\]", d["title"])
        if m:
            out[int(m.group(1))] = d["id"]
    return out


def build_ab(years):
    path = DATA / "ab_reports.csv"
    df = _load(path)
    done = set(df["date"])
    new = []
    ids = ab_datasets()
    for y in years or sorted(ids):
        if y not in ids:
            print("  no Alberta dataset for", y)
            continue
        page = requests.get(f"https://open.alberta.ca/dataset/{ids[y]}",
                            headers=UA, timeout=60).text
        urls = sorted(set(re.findall(
            r'href="([^"]+/download/[^"]*alberta-crop-report-(\d{4}-\d\d-\d\d)\.pdf)"', page)))
        for url, d in urls:
            if d in done:
                continue
            try:
                got = parse_ab_pdf(_get(url), d)
            except Exception as e:  # keep going; report at the end
                print("  FAILED", d, e)
                continue
            print(" ", d, len(got), "values")
            new += got
    if new:
        df = pd.concat([df, pd.DataFrame(new, columns=df.columns)])
    _save(df, path)


def build_mb(years):
    path = DATA / "mb_reports.csv"
    df = _load(path)
    done = set(df["date"])
    new = []
    for y in years:
        d = date(y, 8, 1)
        while d.weekday() != 1:  # Tuesdays
            d += timedelta(days=1)
        while d <= min(date(y, 11, 30), date.today()):
            ds = d.isoformat()
            d += timedelta(days=7)
            if ds in done:
                continue
            r = requests.get(MB_URL.format(d=ds), headers=UA, timeout=60)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                continue
            got = parse_mb_pdf(r.content, ds)
            print(" ", ds, len(got), "values")
            new += got
    if new:
        df = pd.concat([df, pd.DataFrame(new, columns=df.columns)])
    _save(df, path)


SK_API = "https://publications.saskatchewan.ca/api/v1"
# Saskatchewan: 2023-26 are one "Crop Report" product per year (a PDF per week);
# 2020-22 are one product per week inside a yearly category.
SK_YEAR_PRODUCTS = {2026: 128638, 2025: 126049, 2024: 123595, 2023: 120880}
SK_YEAR_CATEGORIES = {2022: 5762, 2021: 5345, 2020: 4624}
SK_REGIONS = {"provincial": "Saskatchewan", "south east": "Southeast",
              "south west": "Southwest", "east central": "East-central",
              "west central": "West-central", "north east": "Northeast",
              "north west": "Northwest"}
SK_CROPS = ["Winter Wheat", "Fall Rye", "Spring Wheat", "Durum", "Oats", "Barley", "Flax",
            "Canola", "Triticale", "Mustard", "Soybean", "Lentil", "Field Pea",
            "Canaryseed", "Chickpea"]
SK_CROP_RE = re.compile("|".join(SK_CROPS))
SK_PROGRESS_NAMES = {"Soybeans": "Soybean", "Lentils": "Lentil", "Field Peas": "Field Pea",
                     "Chickpeas": "Chickpea", "Canary Seed": "Canaryseed"}
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August",
     "September", "October", "November", "December"], 1)}


def _period_end(text, year):
    """'July 7 to 13' / 'June 30 to July 6' -> ISO date of the period's last day."""
    m = re.search(r"([A-Z][a-z]+)\s+(\d{1,2})\s*,?\s*\S{0,2}\s*to\s*"
                  r"(?:([A-Z][a-z]+)\s+)?(\d{1,2})", text)
    if not m or m.group(1) not in MONTHS:
        return None
    mon = MONTHS.get(m.group(3) or m.group(1))
    return date(year, mon, int(m.group(4))).isoformat() if mon else None


SK_LANDING = ("https://www.saskatchewan.ca/business/agriculture-natural-resources-and-industry/"
              "agribusiness-farmers-and-ranchers/market-and-trade-statistics/crops-statistics/"
              "crop-report")


def sk_current_product():
    """Product id behind the landing page's 'Download the Crop Report' link: each new
    season gets a new product, so the current year is discovered, not hard-coded."""
    html = requests.get(SK_LANDING, headers=UA, timeout=60).text
    m = re.search(r'<a[^>]+href="[^"]*/products/(\d+)/formats/\d+/download"[^>]*>\s*'
                  r'Download the Crop Report', html)
    return int(m.group(1)) if m else None


def sk_listing(years):
    """[(period_end ISO date, pdf url)] for the requested Saskatchewan years."""
    out = []
    for y in years:
        pid = SK_YEAR_PRODUCTS.get(y) or (sk_current_product() if y == date.today().year
                                         else None)
        if pid:
            prod = requests.get(f"{SK_API}/products/{pid}", headers=UA, timeout=60).json()
            for f in prod["productFormats"]:
                if f.get("productFormatType") != "PDF":
                    continue
                d = _period_end(f.get("description") or "", y)
                if d:
                    out.append((d, f"{SK_API}/products/{pid}/formats/"
                                   f"{f['productFormatId']}/download"))
        elif y in SK_YEAR_CATEGORIES:
            prods = requests.get(f"{SK_API}/products", headers=UA, timeout=60,
                                 params={"categoryId": SK_YEAR_CATEGORIES[y]}).json()
            for pr in prods:
                name = pr["name"]
                if not re.search(r"crop report", name, re.I) or re.search(
                        r"condition|map|rain|temp|insect", name, re.I):
                    continue
                d = _period_end(name, y)
                if not d:
                    continue
                full = requests.get(f"{SK_API}/products/{pr['productId']}", headers=UA,
                                    timeout=60).json()
                pdfs = [f for f in full["productFormats"]
                        if f.get("productFormatType") == "PDF"]
                if pdfs:
                    out.append((d, f"{SK_API}/products/{pr['productId']}/formats/"
                                   f"{pdfs[0]['productFormatId']}/download"))
    return sorted(set(out))


def _sk_pcts(line):
    """'excellent 22% 19% No Response(s)' -> [22.0, 19.0, None]."""
    return [None if t.startswith("No") else float(t.rstrip("%"))
            for t in re.findall(r"\d+(?:\.\d+)?%|No Response\(s\)", line)]


def _page_texts(content):
    """Per-page text via poppler (fast); None when pdftotext is not installed."""
    exe = shutil.which("pdftotext")
    if not exe:
        return None
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(content)
    try:
        out = subprocess.run([exe, f.name, "-"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
    finally:
        os.unlink(f.name)
    return out.split("\f")


def parse_sk_pdf(content, report_date):
    """The reports are ~30 image-heavy pages; only the condition-table pages need
    pdfplumber, so find them with pdftotext first."""
    rows = []
    texts = _page_texts(content)
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        region, crops = None, []
        pages = pdf.pages if texts is None else [
            pdf.pages[i] for i, t in enumerate(texts[:len(pdf.pages)])
            if "Crop Conditions" in t and "excellent" in t]
        for page in pages:
            cells_all = [c for t in page.extract_tables() for r in t for c in r if c]
            for cell in cells_all:
                key = re.sub(r"\s+", " ", cell.replace("\n", " ")).strip().lower()
                if key in SK_REGIONS:
                    region, crops = SK_REGIONS[key], []
                elif cell.lower().startswith("excellent") and region and crops:
                    lines = {}
                    for ln in cell.split("\n"):
                        lines["very poor" if ln.startswith("very") else ln.split(" ")[0]] = ln
                    if "excellent" in lines and "good" in lines:
                        e, g = _sk_pcts(lines["excellent"]), _sk_pcts(lines["good"])
                        if len(e) == len(g) == len(crops):
                            for c, ev, gv in zip(crops, e, g):
                                if ev is not None and gv is not None:
                                    rows.append((report_date, "rating", c, region, ev + gv))
                elif SK_CROP_RE.search(cell):
                    crops = SK_CROP_RE.findall(cell)
        text = "\n".join(texts[:4]) if texts else "\n".join(
            (pg.extract_text() or "") for pg in pdf.pages[:4])
    # provincial seeding / harvest progress from the bullet lists on the first pages
    kind = None
    for line in text.split("\n"):
        low = line.lower()
        if "harvested:" in low:
            kind = "harvest"
        elif "seeded:" in low:
            kind = "seeding"
        m = re.search(r"([A-Za-z ]+?):\s*(\d+) per cent", line)
        if kind and m:
            name = re.sub(r"^(?:o|•)\s+", "", m.group(1).strip()).title()
            name = SK_PROGRESS_NAMES.get(name, name)
            if name in SK_CROPS:
                rows.append((report_date, kind, name, "Saskatchewan", float(m.group(2))))
    if "seeding progress in sk" in text.lower():
        for line in text.splitlines():
            m = re.match(r"\W*(\d+) per cent (?:for )?([A-Za-z ]+?)\s*(?:;|\.)?(?: and)?$", line.strip())
            if m:
                name = SK_PROGRESS_NAMES.get(m.group(2).strip().title(), m.group(2).strip().title())
                if name in SK_CROPS:
                    rows.append((report_date, "seeding", name, "Saskatchewan", float(m.group(1))))
        m = re.search(r"Per cent seeded\s+Historical all Crops\s+\w+ \d+, \d{4}\s+(\d+)", text)
        if m:
            rows.append((report_date, "seeding", "All crops", "Saskatchewan", float(m.group(1))))
    return rows


def build_sk(years):
    path = DATA / "sk_reports.csv"
    df = _load(path)
    done = set(df["date"])
    new = []
    for d, url in sk_listing(years or sorted({*SK_YEAR_PRODUCTS, *SK_YEAR_CATEGORIES})):
        if d in done:
            continue
        try:
            got = parse_sk_pdf(_get(url), d)
        except Exception as e:
            print("  FAILED", d, e)
            continue
        print(" ", d, len(got), "values", flush=True)
        new += got
        if len(new) >= 400:  # checkpoint: a long run should not lose its work
            df = pd.concat([df, pd.DataFrame(new, columns=df.columns)])
            _save(df, path)
            new = []
    if new:
        df = pd.concat([df, pd.DataFrame(new, columns=df.columns)])
    _save(df, path)


# ── Mexico (SIAP, SADER) ────────────────────────────────────────────────────────
SIAP_CIERRE = ("https://nube.agricultura.gob.mx/index.php?view=10AE434F-A2158368-A120BC5A-EDF4AFAA"
               "&ANIO={y}")
SIAP_AVANCE = "https://nube.agricultura.gob.mx/avance_agricola/"
# SIAP crop id (avance tool) -> name used in the Cierre CSV and in the app
MX_CROPS = {225: "Maíz grano", 374: "Sorgo grano", 395: "Trigo grano", 375: "Soya",
            152: "Frijol", 77: "Cebada grano", 159: "Garbanzo grano", 74: "Cártamo"}
MX_CYCLES = {1: "Otoño-Invierno", 2: "Primavera-Verano"}


def build_mx_production(years=None):
    """SIAP 'Cierre de la producción agrícola' municipal CSVs 2003+, aggregated to
    year x state x cycle x water regime x crop for the grains and oilseeds we follow."""
    path = DATA / "mx_production.csv"
    old = pd.read_csv(path) if path.exists() else pd.DataFrame()
    have = set(old["year"]) if len(old) else set()
    # a completed year is final; refresh the latest two so late revisions are caught
    redo = {date.today().year - 1, date.today().year - 2}
    new = []
    for y in years or range(2003, date.today().year):
        if y in have and y not in redo:
            continue
        for attempt in range(4):  # the server resets connections now and then
            try:
                r = requests.get(SIAP_CIERRE.format(y=y), headers={**UA, "Referer":
                                 "https://nube.agricultura.gob.mx/datosAbiertos/Agricola.php"},
                                 timeout=180)
                break
            except requests.ConnectionError:
                time.sleep(10 * (attempt + 1))
        else:
            raise RuntimeError(f"SIAP Cierre {y}: connection kept failing")
        if r.status_code != 200 or r.content[:5] == b"<!DOC":
            print("  no Cierre file for", y, flush=True)
            continue
        d = pd.read_csv(io.BytesIO(r.content), encoding="latin-1", low_memory=False)
        d = d.rename(columns={"Nomcultivo Sin Um": "Nomcultivo"})  # 2015+ files
        d = d[d["Nomcultivo"].isin(MX_CROPS.values())].copy()
        num = ["Sembrada", "Cosechada", "Siniestrada", "Volumenproduccion", "Valorproduccion"]
        d[num] = d[num].apply(pd.to_numeric, errors="coerce")  # some years carry text cells
        g = d.groupby(["Anio", "Nomestado", "Nomcicloproductivo", "Nommodalidad", "Nomcultivo"],
                      as_index=False)[["Sembrada", "Cosechada", "Siniestrada", "Volumenproduccion",
                                       "Valorproduccion"]].sum()
        g.columns = ["year", "state", "cycle", "water", "crop", "sown_ha", "harvested_ha",
                     "lost_ha", "volume_t", "value_kpesos"]
        print(" ", y, len(g), "rows", flush=True)
        new.append(g)
    if new:
        old = pd.concat([old[~old["year"].isin({int(g["year"].iloc[0]) for g in new})]] + new
                        if len(old) else new)
    old.sort_values(["year", "state", "cycle", "water", "crop"]).to_csv(path, index=False)
    print("mx_production.csv:", len(old), "rows", int(old["year"].min()), "-", int(old["year"].max()))


class _Siap:
    """The avance (monthly progress) tool is a small xajax web app: POST a function name and
    arguments, get XML wrapping an HTML table."""

    def __init__(self):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = UA["User-Agent"]
        self.s.get(SIAP_AVANCE, timeout=60)

    def call(self, fn, *args):
        data = [("xajax", fn)] + [("xajaxargs[]", str(a)) for a in args]
        r = self.s.post(SIAP_AVANCE, data=data, timeout=120)
        r.raise_for_status()
        return r.content.decode("iso-8859-1")

    def months(self, year):
        return sorted(int(m) for m in re.findall(r'<option value="(\d+)"', self.call("llenaMes", year)))

    def report(self, kind, year, cycle, state, crop, month):
        # tipo, anio, ciclo, modalidad (3 = riego + temporal), entidad (0 = national), distrito,
        # municipio, cultivo, unidad, variedad, opcionDDRMpio, agric, tiprod, timerc, mes
        return self.call("reporte", kind, year, cycle, 3, state, 0, 0, crop, 0, 0, 1, 0, 0, 0, month)


def _nums(row_html):
    vals = re.findall(r'<t[dh][^>]*class="tdNum"[^>]*>\s*([\d,.\-]+)\s*</t[dh]>', row_html)
    return [float(v.replace(",", "")) for v in vals]


def _siap_total(html):
    """(sown, harvested, lost, production, yield) from the Total row of a tipo-2 report."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    m = re.search(r"<tr><th colspan=\"2\">Total</th>(.*?)</tr>", html, re.S)
    n = _nums(m.group(1)) if m else []
    return n if len(n) == 5 else None


def build_mx_progress(years=None):
    """National monthly planting and harvest progress by crop and cycle, cumulative to month-end."""
    path = DATA / "mx_progress.csv"
    cols = ["year", "month", "cycle", "crop", "sown_ha", "harvested_ha", "lost_ha", "volume_t",
            "yield_t_ha"]
    old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=cols)
    siap = _Siap()
    this = date.today().year
    new = []
    for y in years or range(2018, this + 1):
        done = {(int(a), int(b), c, k) for a, b, c, k in
                zip(old["year"], old["month"], old["cycle"], old["crop"])}
        ms = siap.months(y)
        for month in ms:
            # the latest published month can still be revised: always refetch the newest two
            recent = y == this and month >= max(ms) - 1
            for cid, cname in MX_CYCLES.items():
                for crop_id, crop in MX_CROPS.items():
                    if (y, month, cname, crop) in done and not recent:
                        continue
                    n = _siap_total(siap.report(2, y, cid, 0, crop_id, month))
                    if n:
                        new.append((y, month, cname, crop, n[0], n[1], n[2], n[3], n[4]))
                    time.sleep(0.2)
            print(" ", y, month, len(new), "rows so far", flush=True)
            if len(new) >= 200:  # checkpoint: a long run should not lose its work
                old = _merge_progress(old, new, cols, path)
                new = []
    old = _merge_progress(old, new, cols, path)
    print("mx_progress.csv:", len(old), "rows")


def _merge_progress(old, new, cols, path):
    if new:
        add = pd.DataFrame(new, columns=cols)
        key = ["year", "month", "cycle", "crop"]
        old = pd.concat([old, add]).drop_duplicates(key, keep="last")
    old.sort_values(["year", "month", "cycle", "crop"]).to_csv(path, index=False)
    return old


def build_mx_states():
    """Latest-month state table (municipal tipo-1 report summed to state) for each crop and cycle."""
    siap = _Siap()
    y = date.today().year
    month = max(siap.months(y)) if siap.months(y) else None
    if month is None:
        y, month = y - 1, max(siap.months(y - 1))
    rows = []
    for cid, cname in MX_CYCLES.items():
        for crop_id, crop in MX_CROPS.items():
            html = re.sub(r"<!--.*?-->", "", siap.report(1, y, cid, 0, crop_id, month), flags=re.S)
            agg = {}
            for tr in re.findall(r"<tr>(.*?)</tr>", html, re.S):
                cells = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
                n = _nums(tr)
                if len(cells) >= 8 and len(n) == 5:
                    st_name = re.sub(r"<[^>]+>|&nbsp;", "", cells[1]).strip()
                    a = agg.setdefault(st_name, [0.0] * 4)
                    for i in range(4):
                        a[i] += n[i]
            for st_name, a in agg.items():
                rows.append((y, month, cname, crop, st_name, *a))
            time.sleep(0.3)
    out = pd.DataFrame(rows, columns=["year", "month", "cycle", "crop", "state", "sown_ha",
                                      "harvested_ha", "lost_ha", "volume_t"])
    out.to_csv(DATA / "mx_progress_states.csv", index=False)
    print("mx_progress_states.csv:", len(out), "rows", y, month)


# ── France (FranceAgriMer Céré'Obs, Agreste) ────────────────────────────────────
CEREOBS_MAIZE = ("https://visionet.franceagrimer.fr/Pages/OpenDocument.aspx?fileurl="
                 "SeriesChronologiques%2fproductions%20vegetales%2fgrandes%20cultures%2f"
                 "etats%20des%20cultures%2fSCR-GRC-CEREOBS_M_depuis_2015-A{yy}.xlsx"
                 "&telechargersanscomptage=oui")
CEREOBS_COLS = ["culture", "week", "sowing", "emergence", "leaves_6_8", "flowering",
                "grain_moisture_50", "harvest", "very_poor", "poor", "fair", "good", "very_good"]
# Agreste "Infos rapides - Grandes cultures" issues carry open xlsx workbooks of their tables.
# Issue ids are not predictable (the July 2026 issue is IraGcu2688): add each new issue here,
# from the "Données des figures" link on its agreste.agriculture.gouv.fr/agreste-web/disaron/<id>/detail/
# page. The workbook name is <year>_<NN>figuresgrandescultures.xlsx for id IraGcu<yy><NN>.
AGRESTE_ISSUES = {"2026-07": "IraGcu2688"}
AGRESTE_URL = ("https://agreste.agriculture.gouv.fr/agreste-web/download/publication/publie/"
               "{id}/20{yy}_{nn}figuresgrandescultures.xlsx")


def build_fr_cereobs():
    """Céré'Obs maize history 2015+: weekly stage progress and 5-class condition, as % of area,
    for France, the regions and the agronomic zones (open data, licence ouverte 2.0)."""
    got = None
    for yy in (date.today().year % 100, date.today().year % 100 - 1):
        r = requests.get(CEREOBS_MAIZE.format(yy=yy), headers=UA, timeout=180)
        if r.status_code == 200 and r.content[:2] == b"PK":
            got = r.content
            break
    if got is None:
        raise RuntimeError("Céré'Obs maize workbook not found")
    x = pd.ExcelFile(io.BytesIO(got))
    frames = []
    for sheet, level, namecol in (("Données France", "France", None),
                                  ("Données régions", "Région", "Région"),
                                  ("Données zones agronomiques", "Zone", "Zone agronomique")):
        d = x.parse(sheet, header=5).dropna(axis=1, how="all")
        d = d.rename(columns={"Culture": "culture", "Semaine": "week"})
        d["name"] = "France" if namecol is None else d[namecol]
        d["level"] = level
        order = ["Semis", "Levée", "6/8 feuilles visibles", "Floraison femelle", "Humidité du grain 50%",
                 "Récolte", "Très mauvaises", "Mauvaises", "Assez bonnes", "Bonnes", "Très bonnes"]
        d = d.rename(columns=dict(zip(order, CEREOBS_COLS[2:])))
        frames.append(d[["level", "name", "culture", "week"] + CEREOBS_COLS[2:]])
    out = pd.concat(frames, ignore_index=True)
    out["year"] = out["week"].str[:4].astype(int)
    out["wk"] = out["week"].str[-2:].astype(int)
    out = out.drop(columns="week")
    DATA.mkdir(exist_ok=True)
    out.to_csv(DATA / "fr_cereobs.csv", index=False)
    print(f"fr_cereobs.csv: {len(out)} rows, {out['year'].min()}-{out['year'].max()}, "
          f"{out['name'].nunique()} areas")


def _agreste_table(x, sheet, first_col):
    d = x.parse(sheet, header=None)
    rows, parent = [], ""
    for i in range(4, len(d)):
        name = d.iloc[i, 0]
        v = d.iloc[i, 1:7]
        if isinstance(name, str) and pd.notna(v).all() and not name.startswith(("Source", "*")):
            name = name.strip()
            if name in ("hiver", "printemps"):  # sub-rows of the crop above
                name = f"{parent} - {name}"
            else:
                parent = name
            rows.append([name, *[float(a) for a in v], float(d.iloc[i, 7]), float(d.iloc[i, 8])])
    return pd.DataFrame(rows, columns=[first_col, "area25_kha", "yield25_qha", "prod25_kt",
                                       "area26_kha", "yield26_qha", "prod26_kt",
                                       "chg_prod_pct", "chg_vs_5yr_pct"])


def build_fr_agreste():
    """Agreste early estimates (surface, yield, production, this year vs last) and the long
    national series for soft wheat and barley, from the issue workbooks in AGRESTE_ISSUES."""
    est, series = [], []
    for issue, iid in sorted(AGRESTE_ISSUES.items()):
        yy, nn = iid[6:8], iid[8:]
        r = requests.get(AGRESTE_URL.format(id=iid, yy=yy, nn=nn), headers=UA, timeout=180)
        r.raise_for_status()
        x = pd.ExcelFile(io.BytesIO(r.content))
        for sheet, grp in (("Figure 5", "Cereals"), ("Figure 6", "Oilseeds and pulses")):
            t = _agreste_table(x, sheet, "crop")
            t.insert(0, "group", grp)
            t.insert(0, "issue", issue)
            est.append(t)
        for sheet, crop in (("Figure 1", "Soft wheat"), ("Figure 3", "Barley")):
            d = x.parse(sheet, header=None)
            years = d.iloc[1, 1:].dropna().astype(int).tolist()
            yld = d.iloc[2, 1:1 + len(years)].astype(float).tolist()
            prod = d.iloc[3, 1:1 + len(years)].astype(float).tolist()
            for yr, a, b in zip(years, yld, prod):
                series.append((issue, crop, yr, a, b))
    DATA.mkdir(exist_ok=True)
    pd.concat(est).to_csv(DATA / "fr_agreste_estimates.csv", index=False)
    old = pd.DataFrame(series, columns=["issue", "crop", "year", "yield_qha", "prod_mt"])
    # the newest issue wins for each year (earlier issues carry earlier estimates)
    old = old.sort_values("issue").drop_duplicates(["crop", "year"], keep="last")
    old.to_csv(DATA / "fr_agreste_series.csv", index=False)
    print(f"fr_agreste: {sum(len(e) for e in est)} estimate rows, {len(old)} series rows, "
          f"issues {', '.join(sorted(AGRESTE_ISSUES))}")


MARS_LIST = "https://joint-research-centre.ec.europa.eu/jrc-mars-bulletins-crop-monitoring-europe_en"
MARS_BASE = "https://joint-research-centre.ec.europa.eu"
BROWSER_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/120 Safari/537.36"}


def build_fr_mars():
    """JRC MARS monthly crop-monitoring summaries: one row per bulletin news page with the
    paragraphs that mention France. The bulletin PDFs and the Agri4Cast data portal reject scripted
    requests (WAF), so yield-forecast tables are NOT available here; these summaries are."""
    html = requests.get(MARS_LIST, headers=BROWSER_UA, timeout=90).text
    links = sorted(set(re.findall(r'href="(/jrc-news-and-updates/[^"]*-(\d{4}-\d\d-\d\d)_en)"', html)),
                   key=lambda x: x[1], reverse=True)
    rows = []
    for path, d in links:
        page = requests.get(MARS_BASE + path, headers=BROWSER_UA, timeout=90).text
        body = re.sub(r"<script.*?</script>|<style.*?</style>", "", page, flags=re.S)
        title = re.search(r"<h1[^>]*>(.*?)</h1>", body, re.S)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", title.group(1))).strip() if title else path
        paras = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p)).strip()
                 for p in re.findall(r"<p[^>]*>(.*?)</p>", body, re.S)]
        fr = [p for p in paras if "France" in p]
        rows.append((d, title, MARS_BASE + path, " ".join(fr)))
    out = pd.DataFrame(rows, columns=["date", "title", "url", "france"])
    DATA.mkdir(exist_ok=True)
    out.to_csv(DATA / "mars_news.csv", index=False)
    print(f"mars_news.csv: {len(out)} bulletins, {int((out['france'] != '').sum())} mention France")


STOCK_GEOS = ["Alberta", "Saskatchewan", "Manitoba", "Ontario", "Canada"]
STOCK_CROPS = {"Canola (rapeseed)": "Canola", "Wheat, all excluding durum wheat": "Wheat ex-durum",
               "Wheat, durum": "Durum", "Barley": "Barley", "Corn for grain": "Corn",
               "Soybeans": "Soybeans"}


def build_stocks():
    """StatCan 32-10-0007-01: farm stocks (Mar 31, Jul 31, Dec 31) by province, in kt."""
    raw = _get("https://www150.statcan.gc.ca/n1/tbl/csv/32100007-eng.zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as z, z.open("32100007.csv") as f:
        df = pd.read_csv(f, encoding="utf-8-sig", usecols=[
            "REF_DATE", "GEO", "Type of stock", "Type of crop", "SCALAR_FACTOR", "VALUE"])
    df = df[df["GEO"].isin(STOCK_GEOS) & df["Type of crop"].isin(STOCK_CROPS)
            & (df["Type of stock"] == "Farm stocks")].dropna(subset=["VALUE"]).copy()
    df["kt"] = df["VALUE"] * df["SCALAR_FACTOR"].map({"thousands": 1.0, "units": 0.001})
    df["crop"] = df["Type of crop"].map(STOCK_CROPS)
    out = df.rename(columns={"REF_DATE": "date", "GEO": "geo"})[["date", "geo", "crop", "kt"]]
    DATA.mkdir(exist_ok=True)
    out.sort_values(["geo", "crop", "date"]).to_csv(DATA / "stocks.csv", index=False)
    print("stocks.csv:", len(out), "rows", out["date"].min(), "-", out["date"].max())


def build_yields():
    raw = _get("https://www150.statcan.gc.ca/n1/tbl/csv/32100359-eng.zip")
    with zipfile.ZipFile(io.BytesIO(raw)) as z, z.open("32100359.csv") as f:
        df = pd.read_csv(f, encoding="utf-8-sig", usecols=[
            "REF_DATE", "GEO", "Harvest disposition", "Type of crop", "VALUE"])
    df = df[df["GEO"].isin(YIELD_GEOS) & df["Type of crop"].isin(YIELD_CROPS)]
    print(sorted(df["Harvest disposition"].unique()))
    disp = {
        "Average yield (kilograms per hectare)": "kg_ha",
        "Average yield (bushels per acre)": "bu_ac",
        "Production (metric tonnes)": "prod_t",
        "Harvested area (hectares)": "harv_ha",
        "Seeded area (hectares)": "seed_ha",
    }
    df = df[df["Harvest disposition"].isin(disp)].copy()
    df["metric"] = df["Harvest disposition"].map(disp)
    df["crop"] = df["Type of crop"].map(YIELD_CROPS)
    out = df.pivot_table(index=["REF_DATE", "GEO", "crop"], columns="metric",
                         values="VALUE", aggfunc="first").reset_index()
    out = out.rename(columns={"REF_DATE": "year", "GEO": "geo"})
    DATA.mkdir(exist_ok=True)
    out.to_csv(DATA / "yields.csv", index=False)
    print("yields.csv:", len(out), "rows", out["year"].min(), "-", out["year"].max())


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    yrs = [int(a) for a in sys.argv[2:]]
    if what in ("yields", "all"):
        build_yields()
    if what in ("ab", "all"):
        build_ab(yrs)
    if what == "frcereobs":
        build_fr_cereobs()
    if what == "fragreste":
        build_fr_agreste()
    if what == "frmars":
        build_fr_mars()
    if what == "frvh":
        import vh
        vh.build_fr()
    if what == "mxprod":
        build_mx_production(yrs or None)
    if what == "mxprog":
        build_mx_progress(yrs or None)
    if what == "mxstates":
        build_mx_states()
    if what == "mxvh":
        import vh
        vh.build_mx()
    if what in ("stocks", "all"):
        build_stocks()
    if what in ("vh", "all"):
        import vh
        vh.build()
    if what in ("sk", "all"):
        build_sk(yrs)
    if what in ("mb", "all"):
        build_mb(yrs or [date.today().year])

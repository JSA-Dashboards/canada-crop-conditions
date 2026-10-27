"""Build the Canada crop conditions data files (data/*.csv).

    python build_data.py yields            # StatCan 32-10-0359-01 -> data/yields.csv
    python build_data.py ab [year ...]     # Alberta weekly PDFs  -> data/ab_reports.csv
    python build_data.py mb [year ...]     # Manitoba weekly PDFs -> data/mb_reports.csv
    python build_data.py sk [year ...]     # Saskatchewan weekly PDFs -> data/sk_reports.csv
    python build_data.py vh                # NOAA satellite crop condition -> data/vh.csv

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


def sk_listing(years):
    """[(period_end ISO date, pdf url)] for the requested Saskatchewan years."""
    out = []
    for y in years:
        if y in SK_YEAR_PRODUCTS:
            pid = SK_YEAR_PRODUCTS[y]
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
    if what in ("vh", "all"):
        import vh
        vh.build()
    if what in ("sk", "all"):
        build_sk(yrs)
    if what in ("mb", "all"):
        build_mb(yrs or [date.today().year])

"""Manifest of USDA FAS crop production map images: data/usda_maps.json.

The maps are USDA's own pictures (US government work) and are shown unaltered with credit. USDA's pages
block scripts, and the image folder carries the release month (e.g. 2026-09), so the addresses below were
read from each country's page in a normal browser session: https://www.fas.usda.gov/data/production/<code>
(the 'Crop Production Maps' links). When USDA publishes a new release, read the page again, change MONTH
and the file lists, refresh data/usda_itok.json (path -> the ?itok= token on the 650 px picture), and rerun:
python build_usda_maps.py
"""
import json
from datetime import date
from pathlib import Path

MONTH = "2026-09"
SITE = "https://www.fas.usda.gov/sites/default/files/ipad/"
PAGE = "https://www.fas.usda.gov/data/production/"
# country -> (page code, folder code, file prefix, {map file code: label}); file codes as listed by USDA
SPEC = {
    "Canada": ("ca", "CA", "can_CA_P_", {
        "production": ["barl", "maiz", "Oats", "rape", "soyb", "sunf", "whea"],
        "seasonal": ["Spring_Whea", "Winter_Whea"]}),
    "Mexico": ("mx", "MX", "mx_MX_P_", {
        "production": ["maiz", "State_maiz", "sorg", "State_sorg", "soyb", "State_soyb", "whea", "State_whea",
                       "Total_barl", "State_Total_barl", "State_Fall_maiz", "State_Spring_maiz",
                       "State_Summer_maiz", "State_Winter_maiz", "State_Fall_sorg", "State_Spring_sorg",
                       "State_Summer_sorg", "State_Winter_sorg", "State_Fall_soyb", "State_Summer_soyb",
                       "State_Fall_whea", "State_Spring_whea", "State_Winter_whea", "State_Spring_barl",
                       "State_Winter_barl"],
        "seasonal": ["Fall_maiz", "Spring_maiz", "Summer_maiz", "Winter_maiz", "Fall_sorg", "Spring_sorg",
                     "Summer_sorg", "Winter_sorg", "Fall_soyb", "Spring_soyb", "Summer_soyb", "Fall_whea",
                     "Spring_whea", "Winter_whea", "Spring_barl", "Winter_barl"]}),
    "Europe": ("e4", "E4", "europe_E4_P_", {
        "production": ["barl", "maiz", "whea"],
        "seasonal": ["Spring_barl", "Spring_whea", "Winter_barl", "Winter_whea"]}),
    "Brazil": ("br", "BR", "br_BR_P_", {
        "production": ["soyb", "Total_maiz", "whea"],
        "seasonal": ["FirstSeason_maiz", "SecondSeason_maiz"]}),
    "Argentina": ("ar", "AR", "ssa_AR_P_", {
        "production": ["maiz", "soyb", "sorg", "sunf", "whea"],
        "seasonal": ["FirstSeason_soyb", "SecondSeason_soyb"]}),
    "South Africa": ("sf", "SF", "safrica_SF_P_", {
        "production": ["maiz", "soyb", "sorg", "sunf", "whea"],
        "seasonal": ["Dryland_whea", "irrigated_whea"]}),
}
EXT_UPPER = {("South Africa", "maiz"), ("South Africa", "soyb"), ("South Africa", "sunf"),
             ("South Africa", "whea"), ("Mexico", "State_Summer_maiz"), ("Mexico", "State_Summer_sorg"),
             ("Mexico", "State_Summer_soyb"), ("Mexico", "State_Winter_maiz"), ("Mexico", "State_Winter_sorg"),
             ("Mexico", "State_Winter_rice"), ("Mexico", "State_Winter_whea")}
# app crop key (the view's own selector value) -> map file codes, first = main map
CROPS = {
    "Canada": {"Canola": ["rape"], "Spring wheat": ["Spring_Whea", "whea"], "Durum": ["whea"],
               "Barley": ["barl"], "Corn": ["maiz"], "Soybeans": ["soyb"]},
    "Mexico": {
        "Maíz grano": ["maiz", "State_maiz", "Summer_maiz", "State_Summer_maiz", "Winter_maiz", "State_Winter_maiz",
                       "Fall_maiz", "State_Fall_maiz", "Spring_maiz", "State_Spring_maiz"],
        "Sorgo grano": ["sorg", "State_sorg", "Summer_sorg", "State_Summer_sorg", "Winter_sorg", "State_Winter_sorg",
                        "Fall_sorg", "State_Fall_sorg", "Spring_sorg", "State_Spring_sorg"],
        "Trigo grano": ["whea", "State_whea", "Winter_whea", "State_Winter_whea", "Fall_whea", "State_Fall_whea",
                        "Spring_whea", "State_Spring_whea"],
        "Soya": ["soyb", "State_soyb", "Summer_soyb", "State_Summer_soyb", "Fall_soyb", "State_Fall_soyb",
                 "Spring_soyb"],
        "Cebada grano": ["Total_barl", "State_Total_barl", "Winter_barl", "State_Winter_barl", "Spring_barl",
                         "State_Spring_barl"]},
    "France": {"Soft wheat": ["whea", "Winter_whea", "Spring_whea"], "Winter barley": ["Winter_barl", "barl"],
               "Grain maize": ["maiz"]},
    "Brazil": {"Soybeans": ["soyb"], "Corn 1st crop": ["FirstSeason_maiz", "Total_maiz"],
               "Corn 2nd crop": ["SecondSeason_maiz", "Total_maiz"], "Wheat": ["whea"]},
    "Argentina": {"Soybeans": ["soyb", "FirstSeason_soyb", "SecondSeason_soyb"], "Corn": ["maiz"],
                  "Sunflower": ["sunf"], "Sorghum": ["sorg"], "Wheat": ["whea"]},
    "South Africa": {"Maize": ["maiz"], "Soybeans": ["soyb"], "Sunflower": ["sunf"], "Sorghum": ["sorg"],
                     "Wheat": ["whea", "Dryland_whea", "irrigated_whea"]},
}
SPEC["France"] = SPEC["Europe"]
CROP_WORD = {"maiz": "Corn", "sorg": "Sorghum", "soyb": "Soybeans", "whea": "Wheat", "barl": "Barley",
             "rape": "Rapeseed", "sunf": "Sunflowerseed", "Total_barl": "Barley", "Total_maiz": "Corn (both crops)",
             "Whea": "Wheat"}


def label(code):
    s = code.replace("State_", "")
    parts = s.split("_")
    base = CROP_WORD.get(parts[-1]) or CROP_WORD.get(s) or s
    season = " ".join(parts[:-1]) if len(parts) > 1 and s not in CROP_WORD else ""
    season = {"FirstSeason": "First season", "SecondSeason": "Second season"}.get(season, season.capitalize())
    text = f"{season} {base.lower()}".strip().capitalize() if season else base
    return f"{text} (state level)" if code.startswith("State_") else text


THUMB = "https://www.fas.usda.gov/sites/default/files/styles/max_scale_650x650/public/ipad/"


def main():
    itok = json.loads(Path(__file__).parent.joinpath("data", "usda_itok.json").read_text(encoding="utf-8"))
    out = {"thumb": THUMB, "month": MONTH, "retrieved": date.today().isoformat(), "site": SITE, "pages": {}, "maps": {}}
    for country, (page, folder, prefix, groups) in SPEC.items():
        if country == "Europe":
            continue
        src = "Europe" if country == "France" else country
        page, folder, prefix, groups = SPEC[src]
        out["pages"][country] = PAGE + page
        files = {}
        for kind, codes in groups.items():
            for c in codes:
                ext = "PNG" if (src, c) in EXT_UPPER else "png"
                files[c] = f"{kind}-maps/{MONTH}/{folder}/{prefix}{c}.{ext}"
        out["maps"][country] = {}
        for crop, codes in CROPS[country].items():
            out["maps"][country][crop] = [
                {"label": label(c) + (" (municipality level)" if country == "Mexico" and not c.startswith("State_") else ""),
                 "path": files[c], "token": itok.get(files[c])} for c in codes if c in files]
    spec = json.loads(Path(__file__).parent.joinpath("data", "usda_calendars_spec.json").read_text(encoding="utf-8"))
    out["calendars"] = {c: [{**o, "token": itok.get(o["path"])} for o in v] for c, v in spec.items()}
    Path(__file__).parent.joinpath("data", "usda_maps.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print({c: {k: len(v) for k, v in m.items()} for c, m in out["maps"].items()})


if __name__ == "__main__":
    main()

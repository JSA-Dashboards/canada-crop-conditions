"""One-off: cut Natural Earth admin-1 (public domain) down to the six countries in the app.

    python build_geo.py path/to/ne_10m_admin_1_states_provinces.geojson

Writes data/geo/<ISO3>.geojson with a `key` property (geo.key of the unit's name), shapes simplified
and exterior rings clockwise (Plotly fills the whole frame otherwise). France is dissolved from
departments into the 13 current regions the Agreste series uses.
"""
import json
import sys
from pathlib import Path

from shapely.geometry import mapping, shape
from shapely.geometry.polygon import orient
from shapely.ops import unary_union

import geo

OUT = Path(__file__).parent / "data" / "geo"
COUNTRIES = {"Canada": ("CAN", 0.05), "Mexico": ("MEX", 0.02), "France": ("FRA", 0.01),
             "Brazil": ("BRA", 0.03), "Argentina": ("ARG", 0.03), "South Africa": ("ZAF", 0.02)}
SKIP = {"Guyane française", "Guadeloupe", "Martinique", "Mayotte", "La Réunion"}


def clockwise(g):
    polys = [g] if g.geom_type == "Polygon" else list(g.geoms)
    return [orient(p, -1.0) for p in polys]


def feature(name, geom, tol):
    geom = geom.simplify(tol, preserve_topology=True)
    polys = [p for p in clockwise(geom) if not p.is_empty]
    out = mapping(unary_union(polys) if len(polys) > 1 else polys[0])
    return {"type": "Feature", "properties": {"name": name, "key": geo.key(name)}, "geometry": out}


def main(src):
    data = json.load(open(src, encoding="utf-8"))["features"]
    OUT.mkdir(parents=True, exist_ok=True)
    for admin, (iso, tol) in COUNTRIES.items():
        feats = [f for f in data if f["properties"]["admin"] == admin and f["properties"]["name"]
                 and f["properties"]["name"] not in SKIP]
        out = []
        if admin == "France":
            by = {}
            for f in feats:
                by.setdefault(f["properties"]["region"], []).append(shape(f["geometry"]))
            for region, parts in by.items():
                if region in SKIP:
                    continue
                out.append(feature(region, unary_union(parts), tol))
        else:
            for f in feats:
                out.append(feature(f["properties"]["name"], shape(f["geometry"]), tol))
        (OUT / f"{iso}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": out},
                                                       separators=(",", ":")), encoding="utf-8")
        print(iso, len(out), "units")


if __name__ == "__main__":
    main(sys.argv[1])

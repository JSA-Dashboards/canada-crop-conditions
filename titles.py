"""Title case for every page title, section heading and chart title (AP style).

apply() patches st.title / st.header / st.subheader and Plotly's Figure.update_layout, so headings built
from variables (a crop, a province) come out right without touching each call site.
Words that already carry capitals, digits, slashes or % (NDVI, StatCan, bu/ac, 2025/26) are left alone,
"vs" becomes "vs.", a spaced hyphen becomes an en dash and year ranges get an en dash.
"""
import re

import plotly.graph_objects as go
import streamlit as st

SMALL = {"a", "an", "the", "and", "but", "or", "nor", "for", "so", "yet", "at", "by", "in", "of", "on",
         "to", "up", "as", "per", "via", "vs", "vs.",
         "do", "da", "de", "del", "la", "le", "du"}   # particles in place names (Mato Grosso do Sul)
_BREAK = (":", "–", "—", "?", "!")


def _cap(word):
    return "-".join(p[:1].upper() + p[1:] for p in word.split("-"))


def tc(text):
    if not isinstance(text, str) or not text:
        return text
    text = re.sub(r"(\b\d{4})-(\d{4}\b)", r"\1–\2", text.replace(" - ", " – "))
    out, prev = [], ""
    for i, tok in enumerate(text.split(" ")):
        lead = re.match(r"^[(\"'“]*", tok).group(0)
        core = tok[len(lead):]
        tail = re.search(r"[)\"'”,.;:?!]*$", core).group(0)
        word = core[:len(core) - len(tail)] if tail else core
        new = word
        if word == "vs":
            new = "vs."
        elif "-" in word and word[:1].isupper() and word.replace("-", "").isalpha():
            new = _cap(word)                                 # Autumn-winter -> Autumn-Winter
        elif word and word.islower() and word.replace("-", "").isalpha():
            first = i == 0 or prev.endswith(_BREAK)
            if lead == "(" and len(word) <= 3 and not first:
                new = word                                   # unit in brackets: (ha), (t), (kt)
            elif first or word not in SMALL:
                new = _cap(word)
        out.append(lead + new + tail)
        prev = tok
    return " ".join(out)


def _chart_title(title):
    if isinstance(title, str):
        return tc(title)
    if isinstance(title, dict) and isinstance(title.get("text"), str):
        return {**title, "text": tc(title["text"])}
    return title


def apply():
    if getattr(st, "_jsa_titles", False):
        return
    for name in ("title", "header", "subheader"):
        orig = getattr(st, name)

        def wrapped(body, *a, _orig=orig, **k):
            return _orig(tc(body), *a, **k)
        setattr(st, name, wrapped)
    orig_update = go.Figure.update_layout

    def update_layout(self, *a, **k):
        if "title" in k:
            k["title"] = _chart_title(k["title"])
        return orig_update(self, *a, **k)
    go.Figure.update_layout = update_layout
    st._jsa_titles = True

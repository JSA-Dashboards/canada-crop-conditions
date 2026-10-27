# Canada crop conditions and yield model

Streamlit app: Alberta and Saskatchewan weekly condition ratings, Manitoba harvest progress,
NOAA satellite greenness for AB/SK/MB/ON, and Statistics Canada yields with a trend-plus-condition model.

Run: `streamlit run app.py`

Refresh the bundled data (`data/*.csv`): `python build_data.py yields|ab|sk|mb|vh`
(`ab`/`sk` need `pdfplumber`; `sk` is faster with poppler's `pdftotext` on PATH).

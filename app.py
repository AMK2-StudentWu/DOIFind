import time, re, requests
import pandas as pd
import streamlit as st

st.title("Title → DOI 批量查询（Crossref）")

mailto = st.secrets.get("CROSSREF_MAILTO", "")  # Streamlit Cloud 里配置
if not mailto:
    st.info("建议在 Streamlit Secrets 里设置 CROSSREF_MAILTO，用于 polite pool（更稳）")

def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())

@st.cache_data(show_spinner=False)
def query_one_title(title: str, mailto: str):
    params = {
        "query.title": title,
        "rows": 3,
        "select": "DOI,title,author,issued,container-title"
    }
    if mailto:
        params["mailto"] = mailto

    r = requests.get("https://api.crossref.org/works", params=params, timeout=20)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])

    best = None
    for it in items:
        got_title = (it.get("title") or [""])[0]
        if norm(got_title) == norm(title):
            best = it
            break
    if best is None and items:
        best = items[0]

    doi = best.get("DOI", "") if best else ""
    matched_title = (best.get("title") or [""])[0] if best else ""
    return doi, matched_title

text = st.text_area("每行一条标题（建议用英文原题）", height=200)

delay = st.slider("每次请求间隔（秒）", 0.0, 1.0, 0.2, 0.05)

if st.button("开始查询"):
    titles = [t.strip() for t in text.splitlines() if t.strip()]
    rows = []
    prog = st.progress(0)
    for i, t in enumerate(titles, 1):
        try:
            doi, matched = query_one_title(t, mailto)
            rows.append({"input_title": t, "doi": doi, "matched_title": matched})
        except Exception as e:
            rows.append({"input_title": t, "doi": "", "matched_title": f"ERROR: {e}"})
        prog.progress(i / max(len(titles), 1))
        time.sleep(delay)

    df = pd.DataFrame(rows)
    st.dataframe(df, use_container_width=True)

    tsv = df.to_csv(sep="\t", index=False)
    st.download_button("下载结果 TSV", data=tsv, file_name="doi_results.tsv")

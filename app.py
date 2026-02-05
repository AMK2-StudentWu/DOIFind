import time, re, requests
import pandas as pd
import streamlit as st

st.title("Title → DOI 批量查询（Crossref）")

mailto = st.secrets.get("CROSSREF_MAILTO", "")
if not mailto:
    st.info("建议在 Streamlit Secrets 里设置 CROSSREF_MAILTO，用于 polite pool（更稳）")

def norm_title(s: str) -> str:
    """
    严格匹配用的标题规范化：
    - 小写
    - 去掉标点/特殊符号（全部替换为空格）
    - 合并多空格
    """
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)   # 只保留英文/数字；其余都当作分隔符
    s = re.sub(r"\s+", " ", s).strip()
    return s

@st.cache_data(show_spinner=False)
def query_strict_doi(title: str, mailto: str):
    # rows 给大一点，避免“确实存在但不在前3条”导致误判 NOT FOUND
    params = {
        "query.title": title,
        "rows": 20,
        "select": "DOI,title"
    }
    if mailto:
        params["mailto"] = mailto

    headers = {
        # 建议加 UA，避免被当成匿名爬虫
        "User-Agent": f"streamlit-doi-lookup/1.0 (mailto:{mailto})" if mailto else "streamlit-doi-lookup/1.0"
    }

    r = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])

    target = norm_title(title)
    for it in items:
        got_title = (it.get("title") or [""])[0]
        if norm_title(got_title) == target:
            doi = it.get("DOI", "")
            # 严格命中但没有 DOI 也要如实返回
            if doi:
                return {"status": "FOUND", "doi": doi, "matched_title": got_title}
            else:
                return {"status": "MATCHED_BUT_NO_DOI", "doi": "", "matched_title": got_title}

    # 没有任何严格匹配
    return {"status": "NOT_FOUND", "doi": "", "matched_title": ""}

text = st.text_area("每行一条标题（建议英文原题）", height=200)
delay = st.slider("每次请求间隔（秒）", 0.0, 1.0, 0.2, 0.05)

if st.button("开始查询"):
    titles = [t.strip() for t in text.splitlines() if t.strip()]
    rows = []
    prog = st.progress(0)

    for i, t in enumerate(titles, 1):
        try:
            res = query_strict_doi(t, mailto)
            rows.append({
                "input_title": t,
                "status": res["status"],
                "doi": res["doi"],
                "matched_title": res["matched_title"],
            })
        except Exception as e:
            rows.append({
                "input_title": t,
                "status": "ERROR",
                "doi": "",
                "matched_title": str(e),
            })

        prog.progress(i / max(len(titles), 1))
        time.sleep(delay)

    df = pd.DataFrame(rows)

    # 2) 表格字体调大（你说“下面字体稍微大一些”）
    styler = (
        df.style
        .set_properties(**{"font-size": "16px"})  # 这里调大/调小：16px/18px都行
        .set_table_styles([
            {"selector": "th", "props": [("font-size", "16px")]}
        ])
    )

    st.dataframe(styler, use_container_width=True)

    tsv = df.to_csv(sep="\t", index=False)
    st.download_button("下载结果 TSV", data=tsv, file_name="doi_results.tsv")

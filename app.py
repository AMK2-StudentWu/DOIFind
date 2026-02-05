import time
import re
import html
import requests
import pandas as pd
import streamlit as st

st.title("Title → DOI 批量查询（Crossref + DBLP）")

mailto = st.secrets.get("CROSSREF_MAILTO", "")
if not mailto:
    st.info("建议在 Streamlit Secrets 里设置 CROSSREF_MAILTO，用于 polite pool（更稳）")

# ========== 输入格式 ==========
st.caption("输入格式：每行一条。支持：\n"
           "1) 仅标题：Title\n"
           "2) 标题 + 作者（推荐）：Title<TAB>FirstAuthorSurname 或 Title<TAB>AnyAuthorSurname\n"
           "分隔符支持 Tab / | / || / ;")

text = st.text_area("每行一条标题（建议英文原题）", height=200)
delay = st.slider("每次请求间隔（秒）", 0.0, 1.0, 0.25, 0.05)
use_author_check = st.checkbox("启用作者校验（更严格，误匹配更低）", value=True)
author_mode = st.selectbox("作者校验方式", ["匹配任一作者姓", "仅匹配第一作者姓"])

# ========== 标题/作者规范化 ==========
def norm_title(s: str) -> str:
    s = html.unescape(s or "").strip().lower()
    # 去掉标点/特殊符号（保留字母数字），合并空格
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def norm_surname(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z]+", "", s)
    return s

def extract_surname(full_name: str) -> str:
    # 适配 "Last, First" / "First Last"
    n = (full_name or "").strip()
    if "," in n:
        last = n.split(",")[0].strip()
        return norm_surname(last)
    parts = re.split(r"\s+", n)
    return norm_surname(parts[-1]) if parts else ""

def parse_line(line: str):
    line = line.strip()
    if not line:
        return None
    # 支持多种分隔符
    for sep in ["\t", "||", "|", ";"]:
        if sep in line:
            a, b = line.split(sep, 1)
            title = a.strip()
            author_hint = b.strip()
            return title, author_hint
    return line, ""

def author_matches(author_hint: str, candidate_authors: list[str]) -> bool:
    if not author_hint:
        return True  # 没给作者就不拦
    hint = norm_surname(author_hint)
    if not hint:
        return True

    cand_surnames = [extract_surname(a) for a in candidate_authors if a]
    if not cand_surnames:
        return False

    if author_mode == "仅匹配第一作者姓":
        return cand_surnames[0] == hint
    else:
        return hint in cand_surnames

# ========== Crossref 严格查询 ==========
@st.cache_data(show_spinner=False)
def query_crossref_strict(title: str, author_hint: str, mailto: str):
    params = {
        "query.title": title,
        "rows": 20,
        "select": "DOI,title,author"
    }
    if mailto:
        params["mailto"] = mailto

    headers = {
        "User-Agent": f"streamlit-doi-lookup/1.0 (mailto:{mailto})" if mailto else "streamlit-doi-lookup/1.0"
    }

    r = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])

    target = norm_title(title)
    for it in items:
        got_title = (it.get("title") or [""])[0]
        if norm_title(got_title) != target:
            continue

        # 作者列表
        cr_authors = []
        for a in it.get("author", []) or []:
            # Crossref 通常给 family/given
            fam = a.get("family", "") or ""
            giv = a.get("given", "") or ""
            name = (giv + " " + fam).strip() if (giv or fam) else ""
            if name:
                cr_authors.append(name)

        if use_author_check and not author_matches(author_hint, cr_authors):
            continue

        doi = it.get("DOI", "") or ""
        if doi:
            return {"status": "FOUND", "source": "Crossref", "doi": doi, "matched_title": got_title}
        else:
            return {"status": "MATCHED_BUT_NO_DOI", "source": "Crossref", "doi": "", "matched_title": got_title}

    return {"status": "NOT_FOUND", "source": "Crossref", "doi": "", "matched_title": ""}

# ========== DBLP 严格查询 ==========
@st.cache_data(show_spinner=False)
def query_dblp_strict(title: str, author_hint: str):
    # DBLP publication search API
    # https://dblp.org/search/publ/api?q=...&format=json&h=...
    params = {
        "q": title,
        "format": "json",
        "h": 25
    }
    r = requests.get("https://dblp.org/search/publ/api", params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    hits = (((data.get("result") or {}).get("hits") or {}).get("hit")) or []
    if isinstance(hits, dict):
        hits = [hits]

    target = norm_title(title)

    for h in hits:
        info = h.get("info", {}) or {}
        got_title = info.get("title", "") or ""
        if norm_title(got_title) != target:
            continue

        # DBLP authors: info["authors"]["author"] 可能是 list 或 str 或 dict
        cand_authors = []
        authors_obj = (info.get("authors") or {}).get("author")
        if isinstance(authors_obj, list):
            cand_authors = [a.get("text", a) if isinstance(a, dict) else str(a) for a in authors_obj]
        elif isinstance(authors_obj, dict):
            cand_authors = [authors_obj.get("text", "")]
        elif isinstance(authors_obj, str):
            cand_authors = [authors_obj]

        if use_author_check and not author_matches(author_hint, cand_authors):
            continue

        # 取 DOI：优先 info["doi"]，否则从 ee 里解析 doi.org
        doi = info.get("doi", "") or ""
        if not doi:
            ee = info.get("ee", "")
            ees = ee if isinstance(ee, list) else [ee]
            for u in ees:
                if isinstance(u, str) and "doi.org/" in u:
                    doi = u.split("doi.org/")[-1].strip()
                    break

        if doi:
            return {"status": "FOUND", "source": "DBLP", "doi": doi, "matched_title": got_title}
        else:
            return {"status": "MATCHED_BUT_NO_DOI", "source": "DBLP", "doi": "", "matched_title": got_title}

    return {"status": "NOT_FOUND", "source": "DBLP", "doi": "", "matched_title": ""}

def lookup_one(title: str, author_hint: str, mailto: str):
    # 先 Crossref 再 DBLP
    cr = query_crossref_strict(title, author_hint, mailto)
    if cr["status"] != "NOT_FOUND":
        return cr

    db = query_dblp_strict(title, author_hint)
    if db["status"] != "NOT_FOUND":
        return db

    return {"status": "NOT_FOUND", "source": "-", "doi": "", "matched_title": ""}

# ========== 执行 ==========
if st.button("开始查询"):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tasks = [parse_line(ln) for ln in lines]
    tasks = [t for t in tasks if t is not None]

    rows = []
    prog = st.progress(0)

    for i, (title, author_hint) in enumerate(tasks, 1):
        try:
            res = lookup_one(title, author_hint, mailto)
            status_cn = {
                "FOUND": "命中",
                "MATCHED_BUT_NO_DOI": "命中但无DOI",
                "NOT_FOUND": "搜索不到",
            }.get(res["status"], res["status"])

            rows.append({
                "input_title": title,
                "author_hint": author_hint,
                "status": status_cn,
                "source": res["source"],
                "doi": res["doi"],
                "matched_title": res["matched_title"],
            })
        except Exception as e:
            rows.append({
                "input_title": title,
                "author_hint": author_hint,
                "status": "ERROR",
                "source": "-",
                "doi": "",
                "matched_title": str(e),
            })

        prog.progress(i / max(len(tasks), 1))
        time.sleep(delay)

    df = pd.DataFrame(rows)

    # 表格字体调大
    styler = (
        df.style
        .set_properties(**{"font-size": "16px"})
        .set_table_styles([{"selector": "th", "props": [("font-size", "16px")]}])
    )
    st.dataframe(styler, use_container_width=True)

    tsv = df.to_csv(sep="\t", index=False)
    st.download_button("下载结果 TSV", data=tsv, file_name="doi_results.tsv")

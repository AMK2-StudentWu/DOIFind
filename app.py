import time
import re
import html
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Title → DOI 批量查询", layout="wide")
st.title("Title → DOI 批量查询（Crossref + DBLP，严格匹配）")

# ========= Secrets / 配置 =========
# 建议在 Streamlit Secrets 里配置：CROSSREF_MAILTO = "you@example.com"
mailto = st.secrets.get("CROSSREF_MAILTO", "")

colA, colB = st.columns([3, 2])
with colA:
    st.caption(
        "输入格式（每行一条）：\n"
        "- 仅标题：Title\n"
        "- 标题 + 作者姓（推荐）：Title<TAB>Salehi\n"
        "分隔符支持：Tab / || / | / ;\n\n"
        "匹配规则：标题规范化后**完全一致**才算命中；命中失败则显示候选 Top-3（不自动选）。"
    )
with colB:
    if not mailto:
        st.info("建议在 Streamlit Secrets 里设置 CROSSREF_MAILTO（更稳，减少限流）")

text = st.text_area("每行一条标题（建议英文原题）", height=220, placeholder="A unified survey on ...\tSalehi")

c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    delay = st.slider("每次请求间隔（秒）", 0.0, 1.0, 0.25, 0.05)
with c2:
    show_candidates = st.checkbox("显示候选 Top-3（仅在搜索不到时）", value=True)
with c3:
    st.write("")

use_author_check = st.checkbox("启用作者校验（更严格，误匹配更低）", value=True)
author_mode = st.selectbox("作者校验方式", ["匹配任一作者姓", "仅匹配第一作者姓"], index=0)

# ========= 规范化 / 解析 =========
def norm_title(s: str) -> str:
    """严格匹配：小写、去标点、合并空格，只保留 a-z0-9。"""
    s = html.unescape(s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def norm_surname(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z]+", "", s)
    return s

def extract_surname(full_name: str) -> str:
    """适配 'Last, First' / 'First Last'。"""
    n = (full_name or "").strip()
    if not n:
        return ""
    if "," in n:
        last = n.split(",")[0].strip()
        return norm_surname(last)
    parts = re.split(r"\s+", n)
    return norm_surname(parts[-1]) if parts else ""

def parse_line(line: str):
    line = line.strip()
    if not line:
        return None
    for sep in ["\t", "||", "|", ";"]:
        if sep in line:
            a, b = line.split(sep, 1)
            return a.strip(), b.strip()
    return line, ""

def author_matches(author_hint: str, candidate_authors: list[str], mode: str) -> bool:
    """author_hint 是用户输入的姓（推荐）。"""
    if not author_hint:
        return True
    hint = norm_surname(author_hint)
    if not hint:
        return True

    cand_surnames = [extract_surname(a) for a in (candidate_authors or []) if a]
    cand_surnames = [s for s in cand_surnames if s]
    if not cand_surnames:
        return False

    if mode == "仅匹配第一作者姓":
        return cand_surnames[0] == hint
    return hint in cand_surnames

def uniq_keep_order(seq):
    seen = set()
    out = []
    for x in seq:
        if x and x not in seen:
            out.append(x)
            seen.add(x)
    return out

def format_candidates(cands: list[str], k=3) -> str:
    cands = uniq_keep_order([c.strip() for c in (cands or []) if c and c.strip()])[:k]
    if not cands:
        return ""
    return "\n".join([f"- {c}" for c in cands])

# ========= Crossref（严格） =========
@st.cache_data(show_spinner=False)
def crossref_strict(title: str, author_hint: str, mailto: str, use_auth: bool, auth_mode: str):
    params = {
        "query.title": title,
        "rows": 20,
        "select": "DOI,title,author"
    }
    if mailto:
        params["mailto"] = mailto

    headers = {
        "User-Agent": f"streamlit-doi-lookup/1.2 (mailto:{mailto})" if mailto else "streamlit-doi-lookup/1.2"
    }

    r = requests.get("https://api.crossref.org/works", params=params, headers=headers, timeout=20)
    r.raise_for_status()
    items = r.json().get("message", {}).get("items", [])

    target = norm_title(title)

    for it in items:
        got_title = (it.get("title") or [""])[0]
        if norm_title(got_title) != target:
            continue

        cr_authors = []
        for a in it.get("author", []) or []:
            fam = a.get("family", "") or ""
            giv = a.get("given", "") or ""
            name = (giv + " " + fam).strip() if (giv or fam) else ""
            if name:
                cr_authors.append(name)

        if use_auth and not author_matches(author_hint, cr_authors, auth_mode):
            continue

        doi = it.get("DOI", "") or ""
        if doi:
            return {"status": "FOUND", "source": "Crossref", "doi": doi, "matched_title": got_title, "candidates": []}
        return {"status": "MATCHED_BUT_NO_DOI", "source": "Crossref", "doi": "", "matched_title": got_title, "candidates": []}

    # 严格没命中：返回候选（不自动选）
    candidates = []
    for it in items:
        t = (it.get("title") or [""])[0]
        d = it.get("DOI", "") or ""
        if t:
            candidates.append(f"{t}" + (f" (doi: {d})" if d else ""))

    return {"status": "NOT_FOUND", "source": "Crossref", "doi": "", "matched_title": "", "candidates": candidates}

# ========= DBLP（严格） =========
@st.cache_data(show_spinner=False)
def dblp_strict(title: str, author_hint: str, use_auth: bool, auth_mode: str):
    params = {"q": title, "format": "json", "h": 25}
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

        # authors
        cand_authors = []
        authors_obj = (info.get("authors") or {}).get("author")
        if isinstance(authors_obj, list):
            cand_authors = [a.get("text", a) if isinstance(a, dict) else str(a) for a in authors_obj]
        elif isinstance(authors_obj, dict):
            cand_authors = [authors_obj.get("text", "")]
        elif isinstance(authors_obj, str):
            cand_authors = [authors_obj]

        if use_auth and not author_matches(author_hint, cand_authors, auth_mode):
            continue

        doi = info.get("doi", "") or ""
        if not doi:
            ee = info.get("ee", "")
            ees = ee if isinstance(ee, list) else [ee]
            for u in ees:
                if isinstance(u, str) and "doi.org/" in u:
                    doi = u.split("doi.org/")[-1].strip()
                    break

        if doi:
            return {"status": "FOUND", "source": "DBLP", "doi": doi, "matched_title": got_title, "candidates": []}
        return {"status": "MATCHED_BUT_NO_DOI", "source": "DBLP", "doi": "", "matched_title": got_title, "candidates": []}

    candidates = []
    for h in hits:
        info = h.get("info", {}) or {}
        t = info.get("title", "") or ""
        d = info.get("doi", "") or ""
        if not d:
            ee = info.get("ee", "")
            ees = ee if isinstance(ee, list) else [ee]
            for u in ees:
                if isinstance(u, str) and "doi.org/" in u:
                    d = u.split("doi.org/")[-1].strip()
                    break
        if t:
            candidates.append(f"{t}" + (f" (doi: {d})" if d else ""))

    return {"status": "NOT_FOUND", "source": "DBLP", "doi": "", "matched_title": "", "candidates": candidates}

def lookup(title: str, author_hint: str):
    cr = crossref_strict(title, author_hint, mailto, use_author_check, author_mode)
    if cr["status"] != "NOT_FOUND":
        return cr

    db = dblp_strict(title, author_hint, use_author_check, author_mode)
    if db["status"] != "NOT_FOUND":
        return db

    merged = []
    if show_candidates:
        merged += [f"[Crossref] {c}" for c in (cr.get("candidates") or [])]
        merged += [f"[DBLP] {c}" for c in (db.get("candidates") or [])]

    return {"status": "NOT_FOUND", "source": "-", "doi": "", "matched_title": "", "candidates": merged}

# ========= 执行 =========
if st.button("开始查询"):
    lines = [ln for ln in text.splitlines() if ln.strip()]
    tasks = [parse_line(ln) for ln in lines]
    tasks = [t for t in tasks if t is not None]

    rows = []
    prog = st.progress(0)

    for i, (title, author_hint) in enumerate(tasks, 1):
        try:
            res = lookup(title, author_hint)

            status_cn = {
                "FOUND": "命中",
                "MATCHED_BUT_NO_DOI": "命中但无DOI",
                "NOT_FOUND": "搜索不到",
            }.get(res["status"], res["status"])

            cand_text = ""
            if res["status"] == "NOT_FOUND" and show_candidates:
                cand_text = format_candidates(res.get("candidates", []), k=3)

            rows.append({
                "input_title": title,
                "author_hint": author_hint,
                "status": status_cn,
                "source": res["source"],
                "doi": res["doi"],
                "matched_title": res["matched_title"],
                "candidates_top3": cand_text,
            })
        except Exception as e:
            rows.append({
                "input_title": title,
                "author_hint": author_hint,
                "status": "ERROR",
                "source": "-",
                "doi": "",
                "matched_title": "",
                "candidates_top3": str(e),
            })

        prog.progress(i / max(len(tasks), 1))
        time.sleep(delay)

    df = pd.DataFrame(rows)

    # 表格字体调大
    styler = (
        df.style
        .set_properties(**{"font-size": "16px", "white-space": "pre-wrap"})
        .set_table_styles([{"selector": "th", "props": [("font-size", "16px")]}])
    )
    st.dataframe(styler, use_container_width=True)

    tsv = df.to_csv(sep="\t", index=False)
    st.download_button("下载结果 TSV", data=tsv, file_name="doi_results.tsv")

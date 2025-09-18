# fetch_news.py
# -*- coding: utf-8 -*-

"""
每日抓取 AI×生物医学 / 微流控 / 生物信息学 的新闻/论文，并输出：
  public/data/YYYY-MM-DD.json
  public/data/YYYY-MM-DD.md

主要来源：
- PubMed（核心）
- arXiv（医学/生物/影像相关的预印本，可选开启）

改进要点：
- JST 时区与“近 N 天”过滤（避免 offset-naive 错误）
- PubMed 文章的封面：优先抓期刊原站的 og:image，退化到站点图标
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import logging
import datetime as dt
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from urllib.parse import urlencode, urljoin, urlparse, quote_plus

import requests
import feedparser
from bs4 import BeautifulSoup

# ========== 配置 ==========
JST = dt.timezone(dt.timedelta(hours=9))  # 日本时区
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123 Safari/537.36"}

OUT_DIR = "public/data"

# 控制抓取规模
DAYS_LOOKBACK = 3          # 近 N 天（针对 PubMed / arXiv）
MAX_PER_SECTION = 40       # 每个模块最多条数（避免过长）
TIMEOUT = 12

# 是否启用 arXiv 作为补充
ENABLE_ARXIV = True


# ========== 数据模型 ==========
@dataclass
class Item:
    id: str
    title: str
    summary: str
    url: str
    cover: str
    source: str
    time: str   # YYYY-MM-DD
    tags: List[str]


# ========== 通用工具 ==========
def today_jst_str() -> str:
    return dt.datetime.now(JST).strftime("%Y-%m-%d")


def iso_date(s: str) -> str:
    """把各种日期字符串尽量规范到 YYYY-MM-DD"""
    try:
        return dt.date.fromisoformat(s[:10]).isoformat()
    except Exception:
        # 尝试常见格式
        m = re.search(r"(\d{4})[-/\.](\d{1,2})[-/\.](\d{1,2})", s)
        if m:
            y, mo, d = map(int, m.groups())
            return dt.date(y, mo, d).isoformat()
        return s[:10]


def within_days(date_str: str, days: int) -> bool:
    """判断 date_str 是否在近 N 天（JST）"""
    try:
        d = dt.date.fromisoformat(date_str[:10])
    except Exception:
        return True  # 解析失败就保留
    today = dt.datetime.now(JST).date()
    return (today - d).days <= max(days, 0)


def md5(s: str) -> str:
    return hashlib.md5(s.encode("utf-8", "ignore")).hexdigest()[:16]


def safe_get(url: str, **kwargs) -> Optional[requests.Response]:
    try:
        r = requests.get(url, headers=UA, timeout=kwargs.get("timeout", TIMEOUT), allow_redirects=True)
        r.raise_for_status()
        return r
    except Exception:
        return None


# ========== 封面抓取（期刊原站优先） ==========
def get_og_image(url: str) -> Optional[str]:
    """优先取 og:image / twitter:image；拿不到用站点图标兜底"""
    r = safe_get(url)
    if r is None:
        return None
    soup = BeautifulSoup(r.text, "lxml")
    for selector in ("meta[property='og:image']", "meta[name='twitter:image']"):
        tag = soup.select_one(selector)
        if tag and tag.get("content"):
            return urljoin(r.url, tag["content"].strip())
    # 兜底：站点图标（至少每家期刊不一样）
    try:
        host = urlparse(r.url).netloc
        return f"https://www.google.com/s2/favicons?sz=256&domain={host}"
    except Exception:
        return None


def best_cover_for(url: str) -> Optional[str]:
    """如果是 PubMed，先到 Full text links 找期刊原站；否则直接取当前页 og:image。"""
    host = urlparse(url).netloc.lower()
    if "pubmed.ncbi.nlm.nih.gov" in host:
        # 1) 找 PubMed 页面里的 Full text links
        r = safe_get(url)
        if r is not None:
            soup = BeautifulSoup(r.text, "lxml")
            a = soup.select_one("section.full-text-links a[href]")
            if a and a.get("href"):
                fulltext = urljoin(r.url, a["href"])
                img = get_og_image(fulltext)
                if img:
                    return img
        # 2) 回退：PubMed 页面的 og:image（通常是蓝色 NIH 图）
        img = get_og_image(url)
        if img:
            return img
        return None
    else:
        return get_og_image(url)


def clean_abs(txt: str, limit: int = 800) -> str:
    if not txt:
        return ""
    t = re.sub(r"\s+", " ", txt).strip()
    return t if len(t) <= limit else (t[:limit].rstrip() + "…")


# ========== PubMed 抓取 ==========
def search_pubmed(query: str, retmax: int = 50) -> List[str]:
    """用 E-utilities esearch 抓到 PMID 列表"""
    params = {
        "db": "pubmed",
        "term": query,
        "retmode": "json",
        "retmax": str(retmax),
        "sort": "most+recent",
    }
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?{urlencode(params)}"
    r = safe_get(url)
    if r is None:
        return []
    try:
        js = r.json()
        return js.get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []


def fetch_pubmed_summaries(pmids: List[str]) -> List[Dict[str, Any]]:
    """用 esummary 抓取题目、来源、时间；再配合网页取摘要"""
    if not pmids:
        return []
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }
    url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{urlencode(params)}"
    r = safe_get(url)
    if r is None:
        return []
    try:
        js = r.json()
        res = []
        for k, v in js.get("result", {}).items():
            if k == "uids":
                continue
            title = v.get("title") or ""
            journal = v.get("fulljournalname") or v.get("source") or ""
            date = v.get("pubdate") or v.get("epubdate") or v.get("sortpubdate") or ""
            date_iso = iso_date(date) if date else today_jst_str()
            url_pub = f"https://pubmed.ncbi.nlm.nih.gov/{k}/"
            res.append({
                "pmid": k,
                "title": title.strip(),
                "source": journal.strip(),
                "time": date_iso,
                "url": url_pub
            })
        return res
    except Exception:
        return []


def fetch_pubmed_abstract(url_pubmed: str) -> str:
    """从 PubMed 网页抓 Abstract 文本"""
    r = safe_get(url_pubmed)
    if r is None:
        return ""
    soup = BeautifulSoup(r.text, "lxml")
    abs_div = soup.select_one("div.abstract-content")
    if abs_div:
        return clean_abs(abs_div.get_text(" ", strip=True))
    # 某些条目用不同结构
    abs2 = soup.select_one("div#abstract")
    if abs2:
        return clean_abs(abs2.get_text(" ", strip=True))
    return ""


def build_pubmed_items(query: str, days: int, limit: int, extra_tags: List[str]|None=None) -> List[Item]:
    pmids = search_pubmed(query, retmax=min(100, limit*2))
    summaries = fetch_pubmed_summaries(pmids)
    items: List[Item] = []
    for s in summaries:
        if not within_days(s["time"], days):
            continue
        abstract = fetch_pubmed_abstract(s["url"])  # 逐条抓摘要（最稳）
        cover = best_cover_for(s["url"]) or ""
        tags = ["Peer-reviewed"]
        if extra_tags:
            tags.extend(extra_tags)
        it = Item(
            id=md5(s["url"]),
            title=s["title"],
            summary=abstract,
            url=s["url"],
            cover=cover,
            source=s["source"],
            time=s["time"],
            tags=tags
        )
        items.append(it)
        if len(items) >= limit:
            break
    return items


# ========== arXiv 抓取（可选） ==========
def fetch_arxiv(query: str, days: int, limit: int, extra_tags: List[str]|None=None) -> List[Item]:
    """
    使用 arXiv API。注意 arXiv 时间是 UTC，近 N 天按 JST 也没问题。
    """
    base = "http://export.arxiv.org/api/query"
    params = {
        "search_query": query,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": str(limit*2),
    }
    url = f"{base}?{urlencode(params)}"
    d = feedparser.parse(url)
    items: List[Item] = []
    for e in d.entries:
        # 标题/摘要
        title = re.sub(r"\s+", " ", e.title).strip()
        summary = clean_abs(e.summary)
        # 链接（取外链 pdf/html）
        link = ""
        for l in e.links:
            if l.get("type") in ("text/html", "application/pdf"):
                link = l.get("href")
                break
        link = link or e.link
        # 时间
        published = e.get("published") or e.get("updated") or ""
        date_iso = iso_date(published) if published else today_jst_str()
        if not within_days(date_iso, days):
            continue
        tags = ["Preprint"]
        if extra_tags:
            tags.extend(extra_tags)
        host = urlparse(link).netloc
        cover = f"https://www.google.com/s2/favicons?sz=256&domain={host}"
        items.append(Item(
            id=md5(link),
            title=title,
            summary=summary,
            url=link,
            cover=cover,
            source="arXiv",
            time=date_iso,
            tags=tags
        ))
        if len(items) >= limit:
            break
    return items


# ========== 去重 ==========
def dedupe(items: List[Item]) -> List[Item]:
    seen = set()
    out = []
    for it in items:
        key = (it.title.lower(), it.source.lower())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


# ========== Markdown ==========
def to_markdown(date_str: str, bucket: Dict[str, List[Item]]) -> str:
    def mk(sec_name: str, arr: List[Item]) -> str:
        if not arr:
            return f"### {sec_name}\n\n（今日暂无）\n\n"
        lines = [f"### {sec_name}\n"]
        for it in arr:
            tags = ", ".join(it.tags) if it.tags else ""
            lines.append(f"- **[{it.title}]({it.url})**  \n  来源：{it.source} · 发布：{it.time}  \n  标签：{tags}\n  \n  {it.summary}\n")
        return "\n".join(lines) + "\n"

    total = sum(len(v) for v in bucket.values())
    head = f"# 每日新闻（JST） · {date_str}\n\n共 {total} 条\n\n"
    md = head
    md += mk("AI（生物医学）", bucket["ai_biomed"])
    md += mk("微流控", bucket["microfluidics"])
    md += mk("生物信息学", bucket["bioinfo"])
    return md


# ========== 主流程 ==========
def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    date_str = today_jst_str()

    # --- 三个模块的查询表达式（PubMed 高级语法）
    q_ai = '(("artificial intelligence"[Title/Abstract]) OR "deep learning"[Title/Abstract] OR "machine learning"[Title/Abstract]) AND (medical OR clinical OR radiology OR genomics OR bioinformatics)'
    q_micro = '(microfluidic OR "lab-on-a-chip" OR microdroplet) AND (biomedical OR diagnostic OR assay)'
    q_bioinfo = '(bioinformatics OR "single-cell" OR genomics OR transcriptomics OR proteomics) AND (algorithm OR pipeline OR method OR benchmark)'

    # --- PubMed 主抓
    ai_pub = build_pubmed_items(q_ai, DAYS_LOOKBACK, MAX_PER_SECTION, extra_tags=["Radiology"])
    micro_pub = build_pubmed_items(q_micro, DAYS_LOOKBACK, max(15, MAX_PER_SECTION//2), extra_tags=["AST"])
    bio_pub = build_pubmed_items(q_bioinfo, DAYS_LOOKBACK, max(20, MAX_PER_SECTION//2), extra_tags=["Single-cell"])

    # --- arXiv 补充（可选）
    ai_arxiv = []
    bio_arxiv = []
    if ENABLE_ARXIV:
        ai_arxiv = fetch_arxiv(query='(ti:"medical" OR abs:"medical" OR ti:"radiology" OR abs:"radiology" OR ti:"biomedical" OR abs:"biomedical") AND (cat:cs.CV OR cat:cs.LG OR cat:eess.IV)', days=DAYS_LOOKBACK, limit=15, extra_tags=["Preprint"])
        bio_arxiv = fetch_arxiv(query='(ti:"genomics" OR abs:"genomics" OR ti:"bioinformatics" OR abs:"bioinformatics" OR ti:"single-cell" OR abs:"single-cell") AND (cat:q-bio.GN OR cat:q-bio.QM OR cat:cs.LG)', days=DAYS_LOOKBACK, limit=10, extra_tags=["Preprint"])

    ai_all = dedupe(ai_pub + ai_arxiv)[:MAX_PER_SECTION]
    micro_all = dedupe(micro_pub)[:max(12, MAX_PER_SECTION//2)]
    bio_all = dedupe(bio_pub + bio_arxiv)[:MAX_PER_SECTION]

    # --- 打包 JSON
    payload = {
        "date": date_str,
        "items": {
            "ai_biomed": [asdict(x) for x in ai_all],
            "microfluidics": [asdict(x) for x in micro_all],
            "bioinfo": [asdict(x) for x in bio_all],
        }
    }

    # --- 写文件
    json_path = os.path.join(OUT_DIR, f"{date_str}.json")
    md_path = os.path.join(OUT_DIR, f"{date_str}.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(date_str, {
            "ai_biomed": ai_all,
            "microfluidics": micro_all,
            "bioinfo": bio_all
        }))

    print(f"[OK] wrote: {json_path}  and  {md_path}")
    print(f"Counts -> AI: {len(ai_all)} | Micro: {len(micro_all)} | Bioinfo: {len(bio_all)}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()

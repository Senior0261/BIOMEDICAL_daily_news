# fetch_news.py
import os, re, json, time, hashlib
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from dateutil import tz

JST = tz.gettz("Asia/Tokyo")
OUT_DIR = "public/data"
os.makedirs(OUT_DIR, exist_ok=True)

HEADERS = {"User-Agent": "NewsDailyBot/1.0 (+https://example.org)"}

SOURCES = {
    "ai_biomed": [
        {"type": "arxiv", "q": '(ti:"medical" OR ti:"biomedical" OR abs:"radiology" OR abs:"genomics" OR abs:"cardiac" OR abs:"pathology") AND (cat:cs.AI OR cat:stat.ML OR cat:q-bio.QM OR cat:q-bio.TO)', "max": 30},
        {"type": "rss", "url": "https://www.biorxiv.org/rss/latest.xml"},
        {"type": "rss", "url": "https://www.medrxiv.org/rss/latest.xml"},
        {"type": "pubmed", "q": '(("artificial intelligence"[Title/Abstract]) OR "deep learning"[Title/Abstract]) AND (medical OR clinical OR radiology OR genomics)', "days": 1, "max": 40},
        {"type": "rss", "url": "https://www.nature.com/subjects/medical-ai.rss"},
        {"type": "rss", "url": "https://www.nature.com/subjects/radiology-and-imaging.rss"},
        {"type": "rss", "url": "https://www.science.org/action/showFeed?type=etoc&feed=rss&jc=sci"},
        {"type": "rss", "url": "https://www.nature.com/nm/current_issue.rss"},
        {"type": "rss", "url": "https://www.nature.com/nbt/current_issue.rss"},
        {"type": "rss", "url": "https://www.nih.gov/news-events/news-releases/feed"},
        {"type": "rss", "url": "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"},
    ],
    "microfluidics": [
        {"type": "rss", "url": "https://pubs.rsc.org/en/journals/journalissues/lc?feed=rss"},
        {"type": "rss", "url": "https://www.nature.com/subjects/microfluidics.rss"},
        {"type": "rss", "url": "https://www.nature.com/subjects/organ-on-a-chip.rss"},
        {"type": "rss", "url": "https://www.nature.com/micronano/current_issue.rss"},
    ],
    "bioinfo": [
        {"type": "arxiv", "q": '(ti:"bioinformatics" OR abs:"single-cell" OR abs:"spatial transcriptomics" OR abs:"multi-omics") AND (cat:q-bio.GN OR cat:q-bio.QM OR cat:cs.LG OR cat:stat.ML)', "max": 30},
        {"type": "rss", "url": "https://www.biorxiv.org/collection/bioinformatics/rss.xml"},
        {"type": "rss", "url": "https://academic.oup.com/rss/site_6152/advanceaccess.xml"},
        {"type": "rss", "url": "https://www.cell.com/cell-systems/current.rss"},
        {"type": "pubmed", "q": '("bioinformatics"[Title/Abstract] OR "genomics"[Title/Abstract] OR "single-cell"[Title/Abstract] OR "transcriptomics"[Title/Abstract]) AND ("machine learning"[Title/Abstract] OR "deep learning"[Title/Abstract])', "days": 1, "max": 40},
    ],
}

KEYWORDS = {
    "ai_biomed": {
        "Cardiac MRI":["cardiac","ventricle","lv","rv","mri","cine"],
        "Radiology":["ct","x-ray","radiology","segmentation","detection","lesion"],
        "Genomics":["genome","genomic","variant","gwas","snv","sv","rna-seq"],
        "Clinical AI":["trial","prospective","external validation","auc","auroc","aupr"],
    },
    "microfluidics": {
        "AST":["antibiotic","susceptibility","MIC","AST"],
        "Organ-on-chip":["organ-on-chip","organ on a chip","OoC"],
        "Valves/Flow":["valve","flow","droplet","channel","mixing","PDMS"],
        "Fabrication":["photolithography","soft lithography","3D print"],
    },
    "bioinfo": {
        "Single-cell":["single-cell","scRNA","cell atlas","metacell"],
        "Spatial":["spatial","Slide-seq","Visium","MERFISH"],
        "Multimodal":["multi-omics","ATAC","ChIP","proteomics"],
        "Algorithms":["transformer","gnn","contrastive","foundation model"],
    }
}

def sha(s): return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]
def norm_host(url):
    try: return urlparse(url).netloc
    except: return ""
def to_iso(dt):
    if isinstance(dt, datetime):
        return dt.astimezone(JST).strftime("%Y-%m-%d")
    return dt

def fetch_og_image(url):
    try:
        html = requests.get(url, timeout=12, headers=HEADERS).text
        soup = BeautifulSoup(html, "html.parser")
        for prop in ["og:image","twitter:image","og:image:url"]:
            tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name":prop})
            if tag and tag.get("content"):
                return urljoin(url, tag["content"])
        icon = soup.find("link", rel=lambda v: v and "icon" in v.lower())
        if icon and icon.get("href"): return urljoin(url, icon["href"])
    except Exception:
        pass
    return ""

def fetch_rss(url, cap=80):
    feed = feedparser.parse(url)
    items = []
    for e in feed.entries[:cap]:
        link = e.get("link") or ""
        title = (e.get("title") or "").strip()
        summary_html = e.get("summary", "") or e.get("description", "") or ""
        summary = BeautifulSoup(summary_html, "html.parser").get_text().strip()
        # time
        dt = None
        for k in ("published_parsed","updated_parsed"):
            if e.get(k):
                dt = datetime.fromtimestamp(time.mktime(e[k]), tz=tz.tzutc()).astimezone(JST)
                break
        cover = ""
        if "media_content" in e and e.media_content:
            cover = e.media_content[0].get("url","")
        if not cover:
            cover = fetch_og_image(link)
        items.append({
            "id": sha(link or title),
            "title": title,
            "summary": summary[:600],
            "url": link,
            "cover": cover,
            "source": norm_host(link) or "RSS",
            "time": to_iso(dt or datetime.now(JST)),
            "tags": [],
        })
    return items

def fetch_arxiv(q, max_results=30):
    api = "http://export.arxiv.org/api/query"
    params = {"search_query": q, "start":0, "max_results":max_results, "sortBy":"submittedDate", "sortOrder":"descending"}
    r = requests.get(api, params=params, timeout=15, headers=HEADERS)
    feed = feedparser.parse(r.text)
    out=[]
    for e in feed.entries:
        link = e.get("id") or (e.links[0].href if e.get("links") else "")
        title = e.get("title","").replace("\n"," ").strip()
        summary = e.get("summary","").replace("\n"," ").strip()
        dt = e.get("published_parsed") or e.get("updated_parsed")
        dt = datetime.fromtimestamp(time.mktime(dt), tz=tz.tzutc()).astimezone(JST) if dt else datetime.now(JST)
        cover = fetch_og_image(link)
        out.append({
            "id": sha(link),
            "title": title,
            "summary": summary[:600],
            "url": link,
            "cover": cover,
            "source": "arXiv",
            "time": to_iso(dt),
            "tags": ["Preprint"],
        })
    return out

def fetch_pubmed(q, days=1, max_n=40):
    base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
    today = datetime.now(JST).date()
    mindate = (today - timedelta(days=days)).strftime("%Y/%m/%d")
    maxdate = today.strftime("%Y/%m/%d")
    esearch = requests.get(base+"esearch.fcgi", params={
        "db":"pubmed","term":q,"retmode":"json","datetype":"pdat","mindate":mindate,"maxdate":maxdate,"retmax":max_n
    }, timeout=15, headers=HEADERS).json()
    ids = esearch.get("esearchresult",{}).get("idlist",[])
    if not ids: return []
    efetch = requests.get(base+"efetch.fcgi", params={"db":"pubmed","id":",".join(ids),"retmode":"xml"}, timeout=20, headers=HEADERS).text
    soup = BeautifulSoup(efetch, "xml")
    out=[]
    for art in soup.find_all("PubmedArticle"):
        pmid = art.find("PMID").text if art.find("PMID") else ""
        title = (art.find("ArticleTitle").text or "").strip()
        abstr = " ".join([x.text for x in art.find_all("AbstractText")])[:600]
        y = art.find("PubDate").find("Year")
        m = art.find("PubDate").find("Month")
        d = art.find("PubDate").find("Day")
        try:
            pubdate = datetime(int(y.text), int(m.text) if m else 1, int(d.text) if d else 1, tzinfo=JST)
        except Exception:
            pubdate = datetime.now(JST)
        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        cover = fetch_og_image(url)
        journal = art.find("Title").text if art.find("Title") else "PubMed"
        out.append({
            "id": sha(pmid),
            "title": title,
            "summary": abstr,
            "url": url,
            "cover": cover,
            "source": journal,
            "time": to_iso(pubdate),
            "tags": ["Peer-reviewed"],
        })
    return out

def tag_item(cat, item):
    text = f"{item['title']} {item['summary']}".lower()
    tags = set(item.get("tags",[]))
    for label, kws in KEYWORDS.get(cat,{}).items():
        if any(k.lower() in text for k in kws):
            tags.add(label)
    host = norm_host(item["url"])
    if "arxiv.org" in host: tags.add("Preprint")
    if any(x in host for x in ["nature.com","cell.com","science.org","oup.com"]): tags.add("Journal")
    item["tags"] = sorted(tags) if tags else []
    return item

def within_days(dt, days=3):
    now = datetime.now(JST)
    if isinstance(dt, str):
        try: dt = datetime.fromisoformat(dt)
        except: return True
    return (now - dt) <= timedelta(days=days+1)

def to_markdown(payload):
    lines = [f"## {payload['date']} · 每日新闻（AI×生物医学｜微流控｜生物信息学）",""]
    for label,key in [["AI（生物医学）","ai_biomed"],["微流控","microfluidics"],["生物信息学","bioinfo"]]:
        arr = payload["items"].get(key,[])
        if not arr: continue
        lines.append(f"### {label}")
        for it in arr:
            t = it.get("time","")
            src = it.get("source","")
            lines.append(f"- **{it['title']}**（{t}） · *{src}*\n  {it.get('summary','')}\n  链接：{it['url']}")
        lines.append("")
    return "\n".join(lines)

def main():
    today_jst = datetime.now(JST).strftime("%Y-%m-%d")
    out = {"date": today_jst, "items": {"ai_biomed": [], "microfluidics": [], "bioinfo": []}}
    seen = set()

    for cat, jobs in SOURCES.items():
        bucket = []
        for job in jobs:
            try:
                if job["type"] == "rss":
                    bucket += fetch_rss(job["url"])
                elif job["type"] == "arxiv":
                    bucket += fetch_arxiv(job["q"], job.get("max",30))
                elif job["type"] == "pubmed":
                    bucket += fetch_pubmed(job["q"], job.get("days",1), job.get("max",40))
            except Exception as e:
                print(f"[WARN] {cat} source error: {job} -> {e}")

        deduped = []
        for it in bucket:
            key = it["url"].split("?")[0]
            if key in seen: continue
            seen.add(key)
            deduped.append(tag_item(cat, it))

        def parse_time(s):
            try: return datetime.fromisoformat(s)
            except: return datetime.now(JST)
        deduped = [x for x in deduped if within_days(parse_time(x["time"]), days=3)]
        deduped.sort(key=lambda x: x["time"], reverse=True)
        out["items"][cat] = deduped

    fp = os.path.join(OUT_DIR, f"{today_jst}.json")
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] wrote {fp} with counts:", {k: len(v) for k,v in out["items"].items()})

    md = to_markdown(out)
    with open(os.path.join(OUT_DIR, f"{today_jst}.md"), "w", encoding="utf-8") as f:
        f.write(md)

if __name__ == "__main__":
    main()

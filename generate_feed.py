#!/usr/bin/env python3
"""
Build a filtered San Francisco Chronicle feed: SF / Bay Area / California
coverage, minus sports and national/world news. Standard library only.

Source 1 (preferred): the Chronicle's own sitemaps. These carry real article
URLs, so sections like /sports/ or /nation/ can be dropped precisely.
Source 2 (fallback): a Google News search feed. Its links are Google
redirects, so filtering there is by headline only (less precise).

Output: docs/feed.xml (subscribe to this) and docs/sections.txt (a report of
what was kept and blocked, for tuning config.json).
"""
import gzip
import json
import re
import sys
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus, urlparse
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
OUT_DIR = ROOT / "docs"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
NOW = datetime.now(timezone.utc)

SPORTS_RE = re.compile(CONFIG["sports_title_regex"])
NATIONAL_RE = re.compile(CONFIG["national_title_regex"])
LOCAL_RE = re.compile(CONFIG["local_rescue_regex"])
BLOCKED_SECTIONS = {s.lower() for s in CONFIG["blocked_sections"]}


def log(msg):
    print(msg, flush=True)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return gunzip(resp.read())


def gunzip(data):
    for _ in range(2):  # handle gzip transfer encoding and/or .xml.gz files
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
    return data


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def title_from_slug(link):
    """Fallback headline from a URL like /bayarea/article/Some-Headline-21012345.php"""
    last = urlparse(link).path.rstrip("/").rsplit("/", 1)[-1]
    last = re.sub(r"(-\d+)?\.(php|html?)$", "", last)
    words = last.replace("-", " ").strip()
    return words[:1].upper() + words[1:] if words else link


def is_recent(dt):
    return dt is not None and dt >= NOW - timedelta(hours=CONFIG["max_age_hours"])


# ---------------------------------------------------------------- sources

def discover_sitemaps():
    urls = list(CONFIG.get("sitemap_urls") or [])
    if not urls:
        robots_url = CONFIG["site"].rstrip("/") + "/robots.txt"
        try:
            robots = fetch(robots_url).decode("utf-8", "replace")
            urls = [line.split(":", 1)[1].strip() for line in robots.splitlines()
                    if line.lower().startswith("sitemap:")]
            log(f"robots.txt lists {len(urls)} sitemap(s)")
        except Exception as e:  # noqa: BLE001
            log(f"robots.txt unavailable: {e}")
    news = [u for u in urls if "news" in u.lower()]
    return news or urls


def read_sitemap_items(start_urls):
    items, seen, queue, fetched = [], set(), list(start_urls), 0
    while queue and fetched < CONFIG["max_sitemap_fetches"]:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            root = ET.fromstring(fetch(url))
            fetched += 1
        except Exception as e:  # noqa: BLE001
            log(f"sitemap failed {url}: {e}")
            continue

        kind = local_name(root.tag)
        if kind == "sitemapindex":
            children = []
            for sm in root:
                loc = lastmod = None
                for el in sm:
                    n = local_name(el.tag)
                    if n == "loc":
                        loc = (el.text or "").strip()
                    elif n == "lastmod":
                        lastmod = parse_date(el.text)
                if loc:
                    children.append((loc, lastmod))
            # news sitemaps first, then most recently modified
            children.sort(key=lambda c: ("news" not in c[0].lower(),
                                         -(c[1].timestamp() if c[1] else 0)))
            queue.extend(c[0] for c in children[:CONFIG["max_child_sitemaps"]])
            log(f"sitemap index {url}: queued {min(len(children), CONFIG['max_child_sitemaps'])} child(ren)")
        elif kind == "urlset":
            count = 0
            for u in root:
                link = lastmod = title = pub = None
                for el in u:  # direct children: page loc / lastmod
                    n = local_name(el.tag)
                    if n == "loc":
                        link = (el.text or "").strip()
                    elif n == "lastmod":
                        lastmod = parse_date(el.text)
                for el in u.iter():  # Google News sitemap fields
                    if "news" not in el.tag:
                        continue
                    n = local_name(el.tag)
                    if n == "title" and el.text and not title:
                        title = el.text.strip()
                    elif n == "publication_date" and not pub:
                        pub = parse_date(el.text)
                date = pub or lastmod
                if not link or not is_recent(date):
                    continue
                items.append({"title": title or title_from_slug(link), "link": link, "date": date})
                count += 1
            log(f"sitemap {url}: {count} recent item(s)")
    return items


def read_google_news():
    q = quote_plus(CONFIG["google_news_query"])
    url = f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
    root = ET.fromstring(fetch(url))
    items = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        title = re.sub(r"\s+-\s+(San Francisco Chronicle|SFChronicle\.com)$", "", title)
        link = (it.findtext("link") or "").strip()
        date = parse_date(it.findtext("pubDate"))
        if title and link and is_recent(date):
            items.append({"title": title, "link": link, "date": date})
    log(f"google news: {len(items)} recent item(s)")
    return items


# ---------------------------------------------------------------- filtering

def section_of(link, mode):
    if mode != "sitemap":
        return "(unknown)"
    segs = [s for s in urlparse(link).path.split("/") if s]
    return segs[0].lower() if len(segs) > 1 else "(root)"


def blocked_reason(item, mode):
    if mode == "sitemap":
        segs = [s.lower() for s in urlparse(item["link"]).path.split("/") if s][:-1]
        hit = next((s for s in segs if s in BLOCKED_SECTIONS), None)
        if hit:
            return f"section:{hit}"
    title = item["title"]
    if mode == "google_news" and SPORTS_RE.search(title):
        return "sports headline"
    if NATIONAL_RE.search(title) and not LOCAL_RE.search(title):
        return "national headline"
    return None


# ---------------------------------------------------------------- output

def write_feed(items):
    rss = ET.Element("rss", {"version": "2.0", "xmlns:atom": "http://www.w3.org/2005/Atom"})
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = CONFIG["feed_title"]
    ET.SubElement(ch, "link").text = CONFIG["site"]
    ET.SubElement(ch, "description").text = CONFIG["feed_description"]
    ET.SubElement(ch, "language").text = "en-us"
    if CONFIG.get("feed_url"):
        ET.SubElement(ch, "atom:link", {"href": CONFIG["feed_url"], "rel": "self",
                                        "type": "application/rss+xml"})
    # Newest item date, not wall-clock time, so unchanged runs produce identical files
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(items[0]["date"], usegmt=True)
    for it in items:
        node = ET.SubElement(ch, "item")
        ET.SubElement(node, "title").text = it["title"]
        ET.SubElement(node, "link").text = it["link"]
        ET.SubElement(node, "guid", {"isPermaLink": "true"}).text = it["link"]
        ET.SubElement(node, "pubDate").text = format_datetime(it["date"], usegmt=True)
        if it.get("section") and it["section"] != "(unknown)":
            ET.SubElement(node, "category").text = it["section"]
    ET.indent(rss)
    OUT_DIR.mkdir(exist_ok=True)
    ET.ElementTree(rss).write(OUT_DIR / "feed.xml", encoding="utf-8", xml_declaration=True)
    (OUT_DIR / ".nojekyll").touch()


def write_report(mode, kept, blocked):
    lines = [f"Source used: {mode}", f"Kept: {len(kept)}   Blocked: {len(blocked)}", ""]
    lines.append("Kept, by section:")
    for sec, n in Counter(i["section"] for i in kept).most_common():
        lines.append(f"  {n:4d}  {sec}")
    lines.append("")
    lines.append("Blocked, by reason:")
    for why, n in Counter(r for _, r in blocked).most_common():
        lines.append(f"  {n:4d}  {why}")
    lines.append("")
    lines.append("Blocked headlines (check for false positives):")
    for it, why in blocked[:60]:
        lines.append(f"  [{why}] {it['title']}")
    (OUT_DIR / "sections.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    mode, raw = "sitemap", []
    try:
        maps = discover_sitemaps()
        raw = read_sitemap_items(maps) if maps else []
    except Exception as e:  # noqa: BLE001
        log(f"sitemap source failed: {e}")
    if len(raw) < CONFIG["min_sitemap_items"]:
        log("Falling back to Google News")
        mode = "google_news"
        try:
            raw = read_google_news()
        except Exception as e:  # noqa: BLE001
            log(f"google news failed: {e}")
            raw = []

    unique = {}
    for it in raw:
        unique.setdefault(it["link"], it)
    kept, blocked = [], []
    for it in unique.values():
        it["section"] = section_of(it["link"], mode)
        why = blocked_reason(it, mode)
        (blocked.append((it, why)) if why else kept.append(it))

    kept.sort(key=lambda i: i["date"], reverse=True)
    kept = kept[:CONFIG["max_items"]]
    blocked.sort(key=lambda b: b[0]["date"], reverse=True)

    if not kept:
        print("::warning::No items found; leaving the existing feed unchanged.")
        return 0
    write_feed(kept)
    write_report(mode, kept, blocked)
    log(f"Wrote {len(kept)} items via {mode} (blocked {len(blocked)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

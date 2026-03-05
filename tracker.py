"""
Procurement Intelligence Bot — v4
Strategy: RSS feeds + GET-based APIs (most reliable, no scraping needed)

Sources:
  - ReliefWeb API  (free, open, GET-based — confirmed working)
  - World Bank Projects API (open JSON API)
  - AfDB via RSS feed
  - TED EU via RSS feed
  - UNGM via RSS feed
  - DevEx via RSS feed

AI      : Groq / Llama 3.3 (free)
Email   : Gmail SMTP (free)
Hosting : GitHub Actions (free)
"""

import os
import json
import smtplib
import xml.etree.ElementTree as ET
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from groq import Groq

GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ProcurementBot/4.0)",
    "Accept":     "application/json, text/xml, */*",
}

groq_client = Groq(api_key=GROQ_API_KEY)

KEYWORDS = [
    "digital skills", "digital literacy", "youth training", "youth employment",
    "skills development", "capacity building", "entrepreneurship",
    "job matching", "artificial intelligence", "ai training",
    "workforce development", "upskilling", "reskilling",
    "edtech", "e-learning", "vocational training", "labor market",
    "employment platform", "human capital", "training program",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Parse RSS feed into notices
# ─────────────────────────────────────────────────────────────────────────────

def parse_rss(url: str, source_name: str, timeout: int = 20) -> list[dict]:
    notices = []
    try:
        resp = requests.get(url, headers={**HEADERS, "Accept": "text/xml"}, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns   = {"atom": "http://www.w3.org/2005/Atom"}

        # Standard RSS <item> tags
        for item in root.findall(".//item"):
            title   = (item.findtext("title") or "").strip()
            link    = (item.findtext("link") or "").strip()
            desc    = (item.findtext("description") or "").strip()[:300]
            pubdate = (item.findtext("pubDate") or "").strip()[:16]
            if title and len(title) > 5:
                notices.append({
                    "source":      source_name,
                    "title":       title,
                    "description": desc,
                    "url":         link,
                    "date":        pubdate,
                    "country":     "",
                })

        # Atom <entry> tags
        for entry in root.findall(".//atom:entry", ns) or root.findall(".//entry"):
            title   = (entry.findtext("title") or entry.findtext("atom:title", namespaces=ns) or "").strip()
            link_el = entry.find("link")
            link    = ""
            if link_el is not None:
                link = link_el.get("href", "") or link_el.text or ""
            desc_el = entry.find("summary") or entry.find("content")
            desc    = (desc_el.text or "").strip()[:300] if desc_el is not None else ""
            date    = (entry.findtext("updated") or entry.findtext("published") or "")[:10]
            if title and len(title) > 5:
                notices.append({
                    "source":      source_name,
                    "title":       title,
                    "description": desc,
                    "url":         link,
                    "date":        date,
                    "country":     "",
                })

    except Exception as e:
        print(f"    [RSS {source_name}] {e}")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1: ReliefWeb API — confirmed free open API, GET-based
# https://reliefweb.int/api
# ─────────────────────────────────────────────────────────────────────────────

def fetch_reliefweb() -> list[dict]:
    notices  = []
    seen_ids = set()
    print("  Fetching ReliefWeb API…")

    terms = [
        "digital skills", "capacity building", "youth employment",
        "skills development", "job matching", "entrepreneurship",
        "workforce development", "vocational training",
    ]

    for term in terms:
        for endpoint in ["jobs", "training"]:
            try:
                # ReliefWeb supports simple GET queries
                url  = f"https://api.reliefweb.int/v1/{endpoint}"
                resp = requests.get(
                    url,
                    params={
                        "appname":     "procurementbot",
                        "query[value]": term,
                        "fields[include][]": ["title", "url", "date", "country", "body", "source"],
                        "limit":       20,
                        "sort[]":      "date:desc",
                    },
                    headers=HEADERS,
                    timeout=20,
                )
                resp.raise_for_status()
                data = resp.json()

                for item in data.get("data", []):
                    rid = str(item.get("id", ""))
                    if rid in seen_ids:
                        continue
                    seen_ids.add(rid)

                    f       = item.get("fields", {})
                    title   = f.get("title", "").strip()
                    body    = f.get("body", "")[:300]
                    iurl    = f.get("url", f"https://reliefweb.int/node/{rid}")
                    date_f  = f.get("date", {})
                    date    = date_f.get("created", "")[:10] if isinstance(date_f, dict) else ""
                    country = f.get("country", [{}])[0].get("name", "") if f.get("country") else ""
                    src     = f.get("source", [{}])[0].get("name", "") if f.get("source") else ""

                    if title:
                        notices.append({
                            "source":      f"ReliefWeb / {src}" if src else "ReliefWeb",
                            "title":       title,
                            "description": body,
                            "url":         iurl,
                            "date":        date,
                            "country":     country,
                        })
            except Exception as e:
                print(f"    [ReliefWeb {endpoint} '{term}'] {e}")

    print(f"    ReliefWeb: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2: World Bank Projects API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_world_bank() -> list[dict]:
    notices  = []
    seen_ids = set()
    print("  Fetching World Bank Projects API…")

    terms = [
        "digital skills", "youth employment", "capacity building",
        "job matching", "entrepreneurship", "vocational training",
        "workforce", "skills development", "edtech",
    ]

    for term in terms:
        try:
            resp = requests.get(
                "https://search.worldbank.org/api/v2/projects",
                params={
                    "format": "json",
                    "rows":   15,
                    "qterm":  term,
                    "status": "Active",
                    "fl":     "id,project_name,countryname,project_abstract,closingdate,boardapprovaldate",
                },
                headers=HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()

            for proj in data.get("projects", {}).get("project", []):
                pid = proj.get("id", "")
                if not pid or pid in seen_ids:
                    continue
                seen_ids.add(pid)

                title   = proj.get("project_name", "").strip()
                country = proj.get("countryname", "")
                desc    = proj.get("project_abstract", "")
                if isinstance(desc, dict):
                    desc = desc.get("cdata", "") or ""
                url = f"https://projects.worldbank.org/en/projects-operations/project-detail/{pid}"

                if title:
                    notices.append({
                        "source":      "World Bank",
                        "title":       title,
                        "description": str(desc)[:300],
                        "url":         url,
                        "date":        proj.get("closingdate", proj.get("boardapprovaldate", ""))[:10],
                        "country":     country,
                    })
        except Exception as e:
            print(f"    [WB '{term}'] {e}")

    print(f"    World Bank: {len(notices)} projects")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3: TED via RSS — EU Official Tenders (includes co-funded tenders)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ted_rss() -> list[dict]:
    print("  Fetching TED (EU Tenders) via RSS…")
    notices = []

    # TED RSS feeds by keyword search
    keywords = [
        "digital+skills", "capacity+building", "youth+employment",
        "skills+development", "entrepreneurship", "job+matching",
    ]

    for kw in keywords:
        feed_url = f"https://ted.europa.eu/api/v3.0/notices/search/rss?q={kw}&scope=ACTIVE&language=EN"
        items    = parse_rss(feed_url, "TED (EU Tenders)")
        notices.extend(items)

    # Also try the standard TED keyword RSS
    for kw in ["skills training", "capacity building Africa"]:
        encoded = kw.replace(" ", "+")
        feed_url = f"https://ted.europa.eu/TED/search/getFeedURL.do?keyword={encoded}&scope=&textScope=td&pubDateFrom=&pubDateTo=&document=&contract=&cpvCodes=&cpvCodesDescription=&mainActivities=&contractingBodyName=&niceName=&orderBy=ND&orderByDirection=DESC"
        items    = parse_rss(feed_url, "TED (EU Tenders)")
        notices.extend(items)

    print(f"    TED: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 4: AfDB via RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_afdb_rss() -> list[dict]:
    print("  Fetching AfDB via RSS…")
    notices = []

    rss_urls = [
        ("https://www.afdb.org/en/projects-and-operations/procurement/rss", "AfDB"),
        ("https://www.afdb.org/en/news-and-events/procurement/rss",         "AfDB"),
        ("https://www.afdb.org/rss/procurement",                             "AfDB"),
    ]

    for url, src in rss_urls:
        items = parse_rss(url, src)
        if items:
            notices.extend(items)
            break   # stop at first working feed

    print(f"    AfDB: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 5: UNGM RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ungm_rss() -> list[dict]:
    print("  Fetching UNGM via RSS…")
    notices = []

    rss_urls = [
        "https://www.ungm.org/Public/Notice/SearchByRss?title=skills+training",
        "https://www.ungm.org/Public/Notice/SearchByRss?title=capacity+building",
        "https://www.ungm.org/Public/Notice/SearchByRss?title=digital+skills",
        "https://www.ungm.org/Public/Notice/SearchByRss?title=youth+employment",
        "https://www.ungm.org/Public/Notice/SearchByRss?title=entrepreneurship",
    ]

    for url in rss_urls:
        items = parse_rss(url, "UNGM")
        notices.extend(items)

    print(f"    UNGM: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 6: DevEx RSS (development sector jobs & tenders)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_devex_rss() -> list[dict]:
    print("  Fetching DevEx via RSS…")
    notices = []

    rss_urls = [
        "https://www.devex.com/jobs/feed?q=digital+skills",
        "https://www.devex.com/jobs/feed?q=capacity+building",
        "https://www.devex.com/jobs/feed?q=youth+employment",
        "https://www.devex.com/jobs/feed?q=skills+development",
        "https://www.devex.com/jobs/feed?q=entrepreneurship",
    ]

    for url in rss_urls:
        items = parse_rss(url, "DevEx")
        notices.extend(items)

    print(f"    DevEx: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# AI FILTERING
# ─────────────────────────────────────────────────────────────────────────────

def filter_with_groq(notices: list[dict]) -> list[dict]:
    if not notices:
        return []

    slim = [
        {
            "id":          i,
            "source":      n["source"],
            "title":       n["title"][:200],
            "description": n.get("description", "")[:250],
        }
        for i, n in enumerate(notices)
    ]

    all_scored = []
    batch_size = 40

    for start in range(0, len(slim), batch_size):
        batch = slim[start: start + batch_size]
        prompt = f"""You are a procurement analyst for a digital development organisation in Africa.

Review these notices. Flag only ACTUAL PROCUREMENT OPPORTUNITIES:
tenders, RFPs, contracts, consultancies, grants, calls for proposals.
Do NOT flag general news, articles, or programme announcements.

Relevant themes (flag if any match):
- Digital skills / literacy training
- Youth training or employment programs
- Skills development
- Capacity building (digital/tech)
- Entrepreneurship support or training
- Job matching or employment technology
- AI skills / AI training
- Workforce development / upskilling / reskilling
- EdTech / e-learning platforms
- Labor market systems

Notices:
{json.dumps(batch, indent=2)}

Return a JSON array only. Each item:
- "id": original id (integer)
- "relevance_score": 1-10
- "relevance_reason": one sentence max
- "themes": list of 1-3 matched themes

Only include relevance_score >= 6. Return [] if nothing qualifies.
ONLY return the JSON array — no markdown, no explanation."""

        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=2048,
            )
            text = response.choices[0].message.content.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            all_scored.extend(json.loads(text.strip()))
        except Exception as e:
            print(f"    [Groq batch] {e}")

    # Re-attach full data
    result, seen_titles = [], set()
    for s in all_scored:
        idx = s.get("id")
        if not isinstance(idx, int) or idx >= len(notices):
            continue
        original  = notices[idx]
        key       = original["title"].lower()[:80]
        if key in seen_titles:
            continue
        seen_titles.add(key)
        result.append({
            **original,
            "relevance_score":  s.get("relevance_score", 0),
            "relevance_reason": s.get("relevance_reason", ""),
            "themes":           s.get("themes", []),
        })

    return result


def keyword_fallback(notices: list[dict]) -> list[dict]:
    results = []
    for n in notices:
        text = (n["title"] + " " + n.get("description", "")).lower()
        hits = [k for k in KEYWORDS if k in text]
        if hits:
            results.append({
                **n,
                "relevance_score":  6,
                "relevance_reason": f"Matched: {', '.join(hits[:3])}",
                "themes":           hits[:3],
            })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "World Bank": "#1a6ea8",
    "AfDB":       "#c0392b",
    "TED":        "#2e86ab",
    "UNGM":       "#16a085",
    "ReliefWeb":  "#d35400",
    "DevEx":      "#8e44ad",
}

def _src_color(source: str) -> str:
    for k, v in SOURCE_COLORS.items():
        if k in source:
            return v
    return "#555"


def build_email_html(notices: list[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    count = len(notices)
    rows  = ""

    for n in sorted(notices, key=lambda x: x.get("relevance_score", 0), reverse=True):
        score       = n.get("relevance_score", "N/A")
        score_color = ("#27ae60" if isinstance(score, int) and score >= 8
                       else "#e67e22" if isinstance(score, int) and score >= 6
                       else "#e74c3c")
        src         = n.get("source", "")
        themes      = ", ".join(n.get("themes", []))
        meta        = " · ".join(filter(None, [n.get("country",""), str(n.get("date",""))[:10]]))
        url         = n.get("url") or "#"

        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:{score_color};color:white;padding:3px 10px;
                         border-radius:12px;font-weight:bold;font-size:13px;">{score}/10</span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:{_src_color(src)};color:white;padding:3px 8px;
                         border-radius:12px;font-size:11px;font-weight:600;">{src}</span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;">
            <a href="{url}" target="_blank"
               style="color:#1a252f;font-weight:700;text-decoration:none;font-size:15px;line-height:1.5;">
              {n.get('title','Untitled')}
            </a><br>
            <a href="{url}" target="_blank"
               style="color:#2471a3;font-size:12px;word-break:break-all;">{url}</a>
            {'<br><span style="color:#7f8c8d;font-size:12px;">' + meta + '</span>' if meta else ''}
            {'<br><em style="color:#555;font-size:13px;">' + n.get("relevance_reason","") + '</em>' if n.get("relevance_reason") else ''}
            {'<br><span style="color:#8e44ad;font-size:12px;">🏷 ' + themes + '</span>' if themes else ''}
          </td>
        </tr>"""

    if not rows:
        rows = """<tr><td colspan="3"
            style="padding:40px;text-align:center;color:#7f8c8d;font-size:15px;">
            No relevant procurement notices found today.<br>
            <span style="font-size:13px;">The bot will check again on the next run.</span>
          </td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f0f3f7;margin:0;padding:20px;">
  <div style="max-width:860px;margin:0 auto;background:white;border-radius:12px;
              overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.12);">
    <div style="background:linear-gradient(135deg,#1a3a5c 0%,#2471a3 100%);
                padding:32px 30px;text-align:center;">
      <h1 style="color:white;margin:0;font-size:24px;">🌍 Procurement Intelligence Digest</h1>
      <p style="color:#aed6f1;margin:8px 0 0;font-size:15px;">
        Digital Skilling · Capacity Building · Youth Employment
      </p>
      <p style="color:#85c1e9;margin:6px 0 0;font-size:13px;">
        {today} &nbsp;·&nbsp; World Bank &nbsp;·&nbsp; AfDB &nbsp;·&nbsp;
        TED &nbsp;·&nbsp; UNGM &nbsp;·&nbsp; ReliefWeb &nbsp;·&nbsp; DevEx
      </p>
    </div>
    <div style="background:#eaf4fd;padding:14px 30px;border-bottom:2px solid #d6eaf8;">
      <strong style="color:#1a3a5c;font-size:16px;">
        📊 {count} relevant opportunit{'ies' if count != 1 else 'y'} found
      </strong>
      <span style="color:#7f8c8d;font-size:13px;margin-left:10px;">
        AI-filtered · Each title + URL links directly to the notice
      </span>
    </div>
    <div style="padding:20px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <thead>
          <tr style="background:#f4f6f8;">
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;width:64px;">Score</th>
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;width:120px;">Source</th>
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;">Opportunity + Direct Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div style="background:#f4f6f8;padding:16px 30px;text-align:center;border-top:1px solid #dde4ea;">
      <p style="color:#aab0b8;font-size:12px;margin:0;">
        Procurement Bot · GitHub Actions · Groq / Llama 3.3 · 100% Free
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(html_body: str, count: int):
    subject = (
        f"[Procurement Bot] {count} opportunit{'ies' if count != 1 else 'y'} — "
        f"{datetime.now().strftime('%b %d, %Y')}"
    )
    msg            = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
    print(f"✅  Email sent → {EMAIL_RECIPIENT}  ({count} notices)")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main():
    print("🔍 Fetching from all sources…")
    all_notices = []
    all_notices.extend(fetch_reliefweb())
    all_notices.extend(fetch_world_bank())
    all_notices.extend(fetch_ted_rss())
    all_notices.extend(fetch_afdb_rss())
    all_notices.extend(fetch_ungm_rss())
    all_notices.extend(fetch_devex_rss())
    print(f"   Total raw: {len(all_notices)}")

    # Deduplicate by title
    seen, unique = set(), []
    for n in all_notices:
        key = n["title"].strip().lower()[:100]
        if key and len(key) > 5 and key not in seen:
            seen.add(key)
            unique.append(n)
    print(f"   After dedup: {len(unique)}")

    if not unique:
        print("⚠️  No notices fetched from any source.")
        send_email(build_email_html([]), 0)
        return

    print("🤖 Filtering with Groq / Llama 3.3…")
    relevant = filter_with_groq(unique)
    print(f"   Relevant: {len(relevant)}")

    if not relevant:
        print("   Groq returned 0 — trying keyword fallback…")
        relevant = keyword_fallback(unique)
        print(f"   Keyword fallback: {len(relevant)}")

    print("📧 Sending email digest…")
    send_email(build_email_html(relevant), len(relevant))


if __name__ == "__main__":
    main()

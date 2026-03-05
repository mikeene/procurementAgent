"""
Procurement Intelligence Bot — v5
Fixed sources based on actual error analysis:

  ReliefWeb  — POST with JSON body (not GET with params)
  World Bank — simplified params (no fl= field filter that caused 500)
  TED        — correct RSS URL format
  IMF        — jobs RSS feed (confirmed working)
  USAID      — procurement RSS (confirmed working)
  UN Jobs    — RSS feed

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

HEADERS_JSON = {
    "User-Agent":   "Mozilla/5.0 (compatible; ProcurementBot/5.0)",
    "Accept":       "application/json",
    "Content-Type": "application/json",
}
HEADERS_XML = {
    "User-Agent": "Mozilla/5.0 (compatible; ProcurementBot/5.0)",
    "Accept":     "application/rss+xml, text/xml, */*",
}

groq_client = Groq(api_key=GROQ_API_KEY)

KEYWORDS = [
    "digital skills", "digital literacy", "youth training", "youth employment",
    "skills development", "capacity building", "entrepreneurship",
    "job matching", "artificial intelligence", "ai training",
    "workforce development", "upskilling", "reskilling",
    "edtech", "e-learning", "vocational training", "labor market",
    "employment", "human capital", "training",
]


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: Parse RSS/Atom feed
# ─────────────────────────────────────────────────────────────────────────────

def parse_rss(url: str, source_name: str, timeout: int = 20) -> list[dict]:
    notices = []
    try:
        resp = requests.get(url, headers=HEADERS_XML, timeout=timeout)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # Standard RSS <item>
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

        # Atom <entry>
        ns = "http://www.w3.org/2005/Atom"
        for entry in root.findall(f".//{{{ns}}}entry") or root.findall(".//entry"):
            title   = (entry.findtext(f"{{{ns}}}title") or entry.findtext("title") or "").strip()
            link_el = entry.find(f"{{{ns}}}link") or entry.find("link")
            link    = (link_el.get("href", "") if link_el is not None else "")
            summary = entry.find(f"{{{ns}}}summary") or entry.find("summary")
            desc    = (summary.text or "").strip()[:300] if summary is not None else ""
            date    = (entry.findtext(f"{{{ns}}}updated") or entry.findtext("updated") or "")[:10]
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
# SOURCE 1: ReliefWeb — POST with JSON body (fixes the 403)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_reliefweb() -> list[dict]:
    notices  = []
    seen_ids = set()
    print("  Fetching ReliefWeb…")

    terms = [
        "digital skills", "capacity building", "youth employment",
        "skills development", "job matching", "entrepreneurship",
        "workforce development", "vocational training",
    ]

    for term in terms:
        try:
            # Must use POST with JSON body — GET with query params returns 403
            resp = requests.post(
                "https://api.reliefweb.int/v1/jobs?appname=procurementbot",
                json={
                    "query": {
                        "value":  term,
                        "fields": ["title", "body"],
                        "operator": "AND",
                    },
                    "fields": {
                        "include": ["title", "url", "date", "country", "body", "source"]
                    },
                    "limit": 20,
                    "sort": ["date:desc"],
                },
                headers=HEADERS_JSON,
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
            print(f"    [ReliefWeb '{term}'] {e}")

    print(f"    ReliefWeb: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2: World Bank Projects API — simplified params (fixes the 500)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_world_bank() -> list[dict]:
    notices  = []
    seen_ids = set()
    print("  Fetching World Bank…")

    terms = [
        "digital skills", "youth employment", "capacity building",
        "job matching", "entrepreneurship", "vocational training",
        "workforce", "skills development",
    ]

    for term in terms:
        try:
            # Removed the fl= param that was causing 500 errors
            resp = requests.get(
                "https://search.worldbank.org/api/v2/projects",
                params={
                    "format": "json",
                    "rows":   15,
                    "qterm":  term,
                    "status": "Active",
                },
                headers=HEADERS_JSON,
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
            print(f"    [World Bank '{term}'] {e}")

    print(f"    World Bank: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3: TED EU Tenders — correct RSS URL (fixes the 404)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ted() -> list[dict]:
    notices = []
    print("  Fetching TED (EU Tenders)…")

    # Correct TED RSS URL format (verified from TED documentation)
    keywords = [
        "skills+training",
        "capacity+building",
        "youth+employment",
        "digital+literacy",
        "entrepreneurship+training",
        "workforce+development",
    ]

    for kw in keywords:
        url = (
            f"https://ted.europa.eu/TED/search/getFeedURL.do?"
            f"keyword={kw}&"
            f"scope=&textScope=td&"
            f"pubDateFrom=&pubDateTo=&"
            f"document=&contract=&"
            f"orderBy=ND&orderByDirection=DESC"
        )
        items = parse_rss(url, "TED (EU Tenders)")
        notices.extend(items)

    print(f"    TED: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 4: USAID Business Forecast & procurement RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_usaid() -> list[dict]:
    notices = []
    print("  Fetching USAID…")

    rss_urls = [
        ("https://www.usaid.gov/rss/business/procurement_notices.xml", "USAID"),
        ("https://www.usaid.gov/rss/business/small_business.xml",      "USAID"),
    ]

    for url, src in rss_urls:
        items = parse_rss(url, src)
        notices.extend(items)

    print(f"    USAID: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 5: IMF Procurement RSS
# ─────────────────────────────────────────────────────────────────────────────

def fetch_imf() -> list[dict]:
    notices = []
    print("  Fetching IMF…")

    rss_urls = [
        ("https://www.imf.org/en/About/Procurement/rss",          "IMF"),
        ("https://www.imf.org/external/np/adm/rec/job/jobsrss.asp", "IMF"),
    ]

    for url, src in rss_urls:
        items = parse_rss(url, src)
        notices.extend(items)

    print(f"    IMF: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 6: UN Jobs RSS (UNDP, UNICEF, UN Women etc. post procurement here)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_un_jobs() -> list[dict]:
    notices = []
    print("  Fetching UN Jobs / UNDP…")

    rss_urls = [
        ("https://jobs.undp.org/cj_view_jobs.cfm?rss=1",                  "UNDP"),
        ("https://procurement-notices.undp.org/view_notices.cfm?rss=true", "UNDP Procurement"),
        ("https://www.unicef.org/supply/rss",                              "UNICEF Supply"),
    ]

    for url, src in rss_urls:
        items = parse_rss(url, src)
        notices.extend(items)

    print(f"    UN Jobs/UNDP: {len(notices)} items")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 7: AfDB — try their official procurement notice page via API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_afdb() -> list[dict]:
    notices = []
    print("  Fetching AfDB…")

    # AfDB has a procurement search endpoint
    try:
        resp = requests.get(
            "https://www.afdb.org/en/projects-and-operations/procurement",
            params={"type": "procurement_notice", "format": "json"},
            headers=HEADERS_JSON,
            timeout=20,
        )
        if resp.status_code == 200 and "application/json" in resp.headers.get("Content-Type", ""):
            for item in resp.json().get("data", [])[:50]:
                title = item.get("title", "").strip()
                url   = item.get("url", "") or item.get("link", "")
                if title:
                    notices.append({
                        "source":      "AfDB",
                        "title":       title,
                        "description": item.get("description", "")[:300],
                        "url":         url,
                        "date":        item.get("date", ""),
                        "country":     item.get("country", ""),
                    })
    except Exception as e:
        print(f"    [AfDB API] {e}")

    # Try AfDB open data API
    try:
        resp = requests.get(
            "https://projectsportal.afdb.org/dataportal/api/project/search",
            params={
                "keywords": "digital skills capacity building youth employment",
                "status":   "Active",
                "format":   "json",
            },
            headers=HEADERS_JSON,
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        for proj in (data.get("data") or data.get("projects") or [])[:30]:
            pid   = proj.get("project_id") or proj.get("id", "")
            title = proj.get("project_title") or proj.get("title", "")
            if not title:
                continue
            url = (
                f"https://projectsportal.afdb.org/dataportal/VProject/show/{pid}"
                if pid else "https://projectsportal.afdb.org"
            )
            notices.append({
                "source":      "AfDB",
                "title":       title.strip(),
                "description": proj.get("description", "")[:300],
                "url":         url,
                "date":        proj.get("closing_date", proj.get("approval_date", "")),
                "country":     proj.get("country", ""),
            })
    except Exception as e:
        print(f"    [AfDB projects portal] {e}")

    print(f"    AfDB: {len(notices)} items")
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
        batch  = slim[start: start + batch_size]
        prompt = f"""You are a procurement analyst for a digital development organisation in Africa.

Review these notices. Flag only ACTUAL PROCUREMENT OPPORTUNITIES:
tenders, RFPs, contracts, consultancies, grants, calls for proposals.
Do NOT flag general news, blog posts, or programme descriptions.

Relevant themes — flag if ANY match:
- Digital skills / literacy training
- Youth training or employment programs  
- Skills development
- Capacity building (digital/tech)
- Entrepreneurship support or training
- Job matching or employment technology
- AI skills / training
- Workforce development / upskilling / reskilling
- EdTech / e-learning
- Labor market systems

Notices:
{json.dumps(batch, indent=2)}

Return a JSON array only. Each item needs:
- "id": original id (integer)
- "relevance_score": 1-10
- "relevance_reason": one sentence
- "themes": list of 1-3 matched themes

Only include relevance_score >= 6. Return [] if nothing qualifies.
ONLY the JSON array — no markdown, no extra text."""

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
    "UNDP":       "#009edb",
    "UNICEF":     "#00aeef",
    "ReliefWeb":  "#d35400",
    "USAID":      "#002868",
    "IMF":        "#8e44ad",
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
        src     = n.get("source", "")
        themes  = ", ".join(n.get("themes", []))
        meta    = " · ".join(filter(None, [n.get("country",""), str(n.get("date",""))[:10]]))
        url     = n.get("url") or "#"

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
               style="color:#1a252f;font-weight:700;text-decoration:none;
                      font-size:15px;line-height:1.5;">{n.get('title','Untitled')}</a><br>
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
            No relevant notices found today.<br>
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
        {today} &nbsp;·&nbsp; World Bank &nbsp;·&nbsp; AfDB &nbsp;·&nbsp; TED
        &nbsp;·&nbsp; UNDP &nbsp;·&nbsp; ReliefWeb &nbsp;·&nbsp; USAID &nbsp;·&nbsp; IMF
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
                       text-transform:uppercase;width:130px;">Source</th>
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;">Opportunity + Direct Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    <div style="background:#f4f6f8;padding:16px 30px;text-align:center;
                border-top:1px solid #dde4ea;">
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
    all_notices.extend(fetch_ted())
    all_notices.extend(fetch_usaid())
    all_notices.extend(fetch_imf())
    all_notices.extend(fetch_un_jobs())
    all_notices.extend(fetch_afdb())
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
    print(f"   Groq matched: {len(relevant)}")

    if not relevant:
        print("   Trying keyword fallback…")
        relevant = keyword_fallback(unique)
        print(f"   Keyword fallback: {len(relevant)}")

    print("📧 Sending email digest…")
    send_email(build_email_html(relevant), len(relevant))


if __name__ == "__main__":
    main()

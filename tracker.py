"""
Procurement Intelligence Bot — v2
Sources : AfDB (Projects), World Bank (Projects), EU Funding & Tenders Portal,
          Global Tenders
AI      : Groq / Llama 3.3 (free tier)
Email   : Gmail SMTP (free)
Hosting : GitHub Actions (free)
"""

import os
import json
import smtplib
import requests
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from bs4 import BeautifulSoup
from groq import Groq

# ── Credentials (set as GitHub Secrets) ──────────────────────────────────────
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Target keywords ───────────────────────────────────────────────────────────
KEYWORDS = [
    "digital skills", "digital skill", "digital literacy",
    "youth training", "youth employment", "skills development",
    "capacity building", "entrepreneurship", "job matching",
    "artificial intelligence", "ai training", "ai skills",
    "workforce development", "upskilling", "reskilling",
    "edtech", "e-learning", "vocational training",
    "labor market", "employment platform", "human capital",
    "technical assistance", "training program",
]


# ─────────────────────────────────────────────────────────────────────────────
# SCRAPERS
# ─────────────────────────────────────────────────────────────────────────────

def scrape_world_bank():
    """
    World Bank — procurement notices under Projects.
    https://projects.worldbank.org/en/projects-operations/procurement
    """
    notices = []
    SECTION_URL = "https://projects.worldbank.org/en/projects-operations/procurement"

    # Method 1: open JSON API
    try:
        api_url = "https://search.worldbank.org/api/v2/procurement"
        params  = {"format": "json", "rows": 50, "srt": "pd", "order": "desc"}
        resp    = requests.get(api_url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data  = resp.json()
        items = data.get("procurements", {}).get("procurement", [])
        for item in items:
            nid  = item.get("id", "")
            url  = (
                f"https://projects.worldbank.org/en/projects-operations/procurement/noticedetail/{nid}"
                if nid else SECTION_URL
            )
            notices.append({
                "source":      "World Bank",
                "title":       item.get("title", "").strip(),
                "description": f"{item.get('project_name','')} — {item.get('notice_type','')}".strip(" —"),
                "url":         url,
                "date":        item.get("submission_date", item.get("pd", "")),
                "country":     item.get("country_name", ""),
            })
        print(f"  World Bank API: {len(notices)} notices")
    except Exception as e:
        print(f"  [World Bank API] {e}")

    # Method 2: HTML fallback
    if not notices:
        try:
            resp = requests.get(SECTION_URL, headers=HEADERS, timeout=30)
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("tr")[:50]:
                cols = row.find_all("td")
                if len(cols) >= 2:
                    a     = cols[0].find("a", href=True)
                    title = a.get_text(strip=True) if a else cols[0].get_text(strip=True)
                    href  = a["href"] if a else ""
                    url   = ("https://projects.worldbank.org" + href
                             if href.startswith("/") else href or SECTION_URL)
                    if title and len(title) > 5:
                        notices.append({
                            "source":      "World Bank",
                            "title":       title,
                            "description": cols[1].get_text(strip=True) if len(cols) > 1 else "",
                            "url":         url,
                            "date":        cols[-1].get_text(strip=True),
                            "country":     cols[2].get_text(strip=True) if len(cols) > 2 else "",
                        })
            print(f"  World Bank HTML: {len(notices)} notices")
        except Exception as e:
            print(f"  [World Bank HTML] {e}")

    return notices


def scrape_afdb():
    """
    African Development Bank — procurement under Projects.
    https://www.afdb.org/en/projects-and-operations/procurement
    """
    notices = []
    SECTION_URL = "https://www.afdb.org/en/projects-and-operations/procurement"

    try:
        resp = requests.get(SECTION_URL, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Table rows
        for row in soup.select("table tr")[1:60]:
            cols  = row.find_all("td")
            if len(cols) < 2:
                continue
            a     = cols[0].find("a", href=True) or row.find("a", href=True)
            title = a.get_text(strip=True) if a else cols[0].get_text(strip=True)
            href  = a["href"] if a else ""
            url   = ("https://www.afdb.org" + href if href.startswith("/")
                     else href or SECTION_URL)
            if title and len(title) > 5:
                notices.append({
                    "source":      "AfDB",
                    "title":       title,
                    "description": cols[1].get_text(strip=True) if len(cols) > 1 else "",
                    "url":         url,
                    "date":        cols[-1].get_text(strip=True) if len(cols) > 2 else "",
                    "country":     cols[2].get_text(strip=True) if len(cols) > 3 else "",
                })

        # Card / article layout
        for item in soup.select(".views-row, article.node, .procurement-notice")[:40]:
            a        = item.find("a", href=True)
            title_el = item.find(["h3", "h2", "h4"])
            title    = (title_el.get_text(strip=True) if title_el
                        else (a.get_text(strip=True) if a else ""))
            href     = a["href"] if a else ""
            url      = ("https://www.afdb.org" + href if href.startswith("/")
                        else href or SECTION_URL)
            desc_el  = item.find("p")
            date_el  = item.find(class_=lambda c: c and "date" in str(c).lower())
            if title and len(title) > 5 and url != SECTION_URL:
                notices.append({
                    "source":      "AfDB",
                    "title":       title,
                    "description": desc_el.get_text(strip=True) if desc_el else "",
                    "url":         url,
                    "date":        date_el.get_text(strip=True) if date_el else "",
                    "country":     "",
                })

        print(f"  AfDB: {len(notices)} notices")
    except Exception as e:
        print(f"  [AfDB] {e}")

    return notices


def scrape_eu_tenders():
    """
    EU Funding & Tenders Portal — Procurement & Calls for Tenders tab,
    under Other Organisations.
    https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-tenders
    """
    notices = []
    SECTION_URL = (
        "https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
        "screen/opportunities/calls-for-tenders"
    )

    # EU open search API
    try:
        api_url = "https://api.tech.ec.europa.eu/search-api/prod/rest/search"
        payload = {
            "apiKey":     "SEDIA",
            "text":       "digital skills capacity building youth training entrepreneurship job matching",
            "pageSize":   50,
            "pageNumber": 1,
            "sortBy":     "startDate",
            "sortOrder":  "DESC",
        }
        resp = requests.post(api_url, json=payload, headers=HEADERS, timeout=30)
        data = resp.json()
        for hit in data.get("results", [])[:50]:
            md    = hit.get("metadata", {})
            title = hit.get("title", "")
            if isinstance(title, dict):
                title = title.get("en", "") or next(iter(title.values()), "")
            nid   = hit.get("identifier", "")
            url   = (
                f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
                f"screen/opportunities/calls-for-tenders/{nid}"
                if nid else SECTION_URL
            )
            desc = hit.get("description", "")
            if isinstance(desc, dict):
                desc = desc.get("en", "") or next(iter(desc.values()), "")
            notices.append({
                "source":      "EU Tenders",
                "title":       str(title).strip(),
                "description": str(desc).strip()[:300],
                "url":         url,
                "date":        md.get("deadlineDate", md.get("startDate", "")),
                "country":     ", ".join(md.get("location", [])) if md.get("location") else "",
            })
        print(f"  EU Tenders API: {len(notices)} notices")
    except Exception as e:
        print(f"  [EU Tenders API] {e}")

    # HTML fallback
    if not notices:
        try:
            resp = requests.get(SECTION_URL, headers=HEADERS, timeout=30)
            soup = BeautifulSoup(resp.text, "html.parser")
            for item in soup.select(".opportunity-item, .tender-item, article, .list-item")[:40]:
                a        = item.find("a", href=True)
                title_el = item.find(["h3", "h2", "h4"])
                title    = (title_el.get_text(strip=True) if title_el
                            else (a.get_text(strip=True) if a else ""))
                href     = a["href"] if a else ""
                url      = ("https://ec.europa.eu" + href if href.startswith("/")
                            else href or SECTION_URL)
                if title and len(title) > 5:
                    notices.append({
                        "source":      "EU Tenders",
                        "title":       title,
                        "description": "",
                        "url":         url,
                        "date":        "",
                        "country":     "",
                    })
            print(f"  EU Tenders HTML: {len(notices)} notices")
        except Exception as e:
            print(f"  [EU Tenders HTML] {e}")

    return notices


def scrape_global_tenders():
    """
    Global Tenders — https://www.globaltenders.com
    Searches for each keyword phrase and collects matching notices.
    """
    notices  = []
    BASE_URL = "https://www.globaltenders.com"

    search_terms = [
        "digital skills training",
        "capacity building youth",
        "job matching platform",
        "entrepreneurship development",
        "AI skills training",
        "skills development",
    ]

    for term in search_terms:
        try:
            resp = requests.get(
                f"{BASE_URL}/tenders-search.php",
                params={"keyword": term, "country": "", "category": ""},
                headers=HEADERS,
                timeout=30,
            )
            soup = BeautifulSoup(resp.text, "html.parser")

            for row in soup.select("table tr")[1:20]:
                a = row.find("a", href=True)
                if not a:
                    continue
                title = a.get_text(strip=True)
                href  = a["href"]
                url   = BASE_URL + href if href.startswith("/") else href
                cols  = row.find_all("td")
                date    = cols[-1].get_text(strip=True) if cols else ""
                country = cols[1].get_text(strip=True) if len(cols) > 1 else ""
                if title and len(title) > 8:
                    notices.append({
                        "source":      "Global Tenders",
                        "title":       title,
                        "description": f"Search term: {term}",
                        "url":         url,
                        "date":        date,
                        "country":     country,
                    })
        except Exception as e:
            print(f"  [Global Tenders '{term}'] {e}")

    print(f"  Global Tenders: {len(notices)} notices")
    return notices


# ─────────────────────────────────────────────────────────────────────────────
# AI FILTERING — Groq / Llama 3.3
# ─────────────────────────────────────────────────────────────────────────────

def filter_with_groq(notices: list[dict]) -> list[dict]:
    if not notices:
        return []

    slim = [
        {
            "id":          i,
            "source":      n["source"],
            "title":       n["title"][:200],
            "description": n.get("description", "")[:300],
        }
        for i, n in enumerate(notices)
    ]

    prompt = f"""You are a procurement analyst for an organisation focused on youth employment and digital development in Africa and globally.

Review these procurement notices. Identify only ACTUAL PROCUREMENT OPPORTUNITIES (contracts, tenders, calls for proposals, consultancies, RFPs, RFQs) — NOT news articles, blog posts, or general programme descriptions.

Mark as relevant if the opportunity relates to ANY of:
- Digital skills / digital literacy training
- Youth training or youth employment programs
- Skills development programs
- Capacity building (especially tech/digital)
- Entrepreneurship support or training
- Job matching platforms or employment technology
- AI skills or AI training programs
- Workforce development, upskilling, reskilling
- EdTech or e-learning platforms
- Labor market information systems

Notices (JSON):
{json.dumps(slim, indent=2)}

Return a JSON array. Each element must have:
- "id": original id integer
- "relevance_score": integer 1-10
- "relevance_reason": one sentence
- "themes": array of 1-3 matched themes

Only include actual procurement opportunities with relevance_score >= 6.
If nothing qualifies, return [].
Respond with ONLY the JSON array. No markdown, no extra text."""

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
        scored = json.loads(text.strip())

        result = []
        for s in scored:
            idx = s.get("id")
            if idx is None or not isinstance(idx, int) or idx >= len(notices):
                continue
            result.append({
                **notices[idx],                          # includes the real URL
                "relevance_score":  s.get("relevance_score", 0),
                "relevance_reason": s.get("relevance_reason", ""),
                "themes":           s.get("themes", []),
            })
        return result

    except Exception as e:
        print(f"  [Groq error] {e}")
        return keyword_fallback(notices)


def keyword_fallback(notices: list[dict]) -> list[dict]:
    """Simple keyword filter used only if Groq is unavailable."""
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
    "World Bank":    "#1a6ea8",
    "AfDB":          "#c0392b",
    "EU Tenders":    "#2e86ab",
    "Global Tenders":"#27ae60",
}


def build_email_html(notices: list[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    count = len(notices)
    rows  = ""

    for n in sorted(notices, key=lambda x: x.get("relevance_score", 0), reverse=True):
        score       = n.get("relevance_score", "N/A")
        score_color = ("#27ae60" if isinstance(score, int) and score >= 8
                       else "#e67e22" if isinstance(score, int) and score >= 6
                       else "#e74c3c")
        src_color   = SOURCE_COLORS.get(n.get("source", ""), "#555")
        themes      = ", ".join(n.get("themes", []))
        meta        = " · ".join(filter(None, [n.get("country",""), n.get("date","")]))
        url         = n.get("url", "#") or "#"

        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:{score_color};color:white;padding:3px 10px;
                         border-radius:12px;font-weight:bold;font-size:13px;">{score}/10</span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:{src_color};color:white;padding:3px 9px;
                         border-radius:12px;font-size:11px;font-weight:600;">
              {n.get('source','')}
            </span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;">
            <a href="{url}" target="_blank"
               style="color:#1a252f;font-weight:700;text-decoration:none;font-size:15px;line-height:1.5;">
              {n.get('title','Untitled')}
            </a><br>
            <a href="{url}" target="_blank"
               style="color:#2471a3;font-size:12px;word-break:break-all;">
              {url}
            </a>
            {'<br><span style="color:#7f8c8d;font-size:12px;">' + meta + '</span>' if meta else ''}
            {'<br><em style="color:#555;font-size:13px;">' + n.get("relevance_reason","") + '</em>' if n.get("relevance_reason") else ''}
            {'<br><span style="color:#8e44ad;font-size:12px;">🏷 ' + themes + '</span>' if themes else ''}
          </td>
        </tr>"""

    if not rows:
        rows = """<tr><td colspan="3"
            style="padding:40px;text-align:center;color:#7f8c8d;font-size:15px;">
            No relevant procurement notices found today.<br>
            <span style="font-size:13px;">The bot will check again on the next scheduled run.</span>
          </td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
</head>
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
        {today} &nbsp;·&nbsp; AfDB &nbsp;·&nbsp; World Bank &nbsp;·&nbsp;
        EU Tenders &nbsp;·&nbsp; Global Tenders
      </p>
    </div>

    <div style="background:#eaf4fd;padding:14px 30px;border-bottom:2px solid #d6eaf8;">
      <strong style="color:#1a3a5c;font-size:16px;">
        📊 {count} relevant opportunit{'ies' if count != 1 else 'y'} found
      </strong>
      <span style="color:#7f8c8d;font-size:13px;margin-left:10px;">
        AI-filtered · Each title and URL links directly to the procurement notice
      </span>
    </div>

    <div style="padding:20px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <thead>
          <tr style="background:#f4f6f8;">
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;width:64px;">Score</th>
            <th style="padding:10px 8px;text-align:left;color:#666;font-size:11px;
                       text-transform:uppercase;width:100px;">Source</th>
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
    print("🔍 Scraping procurement sources…")
    all_notices = []
    all_notices.extend(scrape_world_bank())
    all_notices.extend(scrape_afdb())
    all_notices.extend(scrape_eu_tenders())
    all_notices.extend(scrape_global_tenders())
    print(f"   Total raw: {len(all_notices)}")

    # Deduplicate by title
    seen, unique = set(), []
    for n in all_notices:
        key = n["title"].strip().lower()[:100]
        if key and len(key) > 5 and key not in seen:
            seen.add(key)
            unique.append(n)
    print(f"   After dedup: {len(unique)}")

    print("🤖 Filtering with Groq / Llama 3.3…")
    relevant = filter_with_groq(unique)
    print(f"   Relevant: {len(relevant)}")

    print("📧 Sending email digest…")
    html = build_email_html(relevant)
    send_email(html, len(relevant))


if __name__ == "__main__":
    main()

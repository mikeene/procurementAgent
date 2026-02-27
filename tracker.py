"""
Procurement Intelligence Bot
Sources : AfDB, World Bank, IMF
AI      : Groq (Llama 3 — free tier)
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

# ── Groq client (openai-compatible SDK) ───────────────────────────────────────
from groq import Groq

GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]      # your Gmail
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]    # Gmail App Password
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]   # where to send digests

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ProcurementBot/1.0)"}

groq_client = Groq(api_key=GROQ_API_KEY)

# ── Scrapers ──────────────────────────────────────────────────────────────────

def scrape_world_bank():
    notices = []

    # Primary: World Bank open search API
    try:
        api_url = "https://search.worldbank.org/api/v2/procurement"
        params  = {"format": "json", "rows": 50, "srt": "pd", "order": "desc"}
        resp    = requests.get(api_url, params=params, headers=HEADERS, timeout=30)
        data    = resp.json()
        for item in data.get("procurements", {}).get("procurement", []):
            notices.append({
                "source":      "World Bank",
                "title":       item.get("title", ""),
                "description": item.get("project_name", "") + " — " + item.get("notice_type", ""),
                "url":         f"https://projects.worldbank.org/en/projects-operations/procurement/noticedetail/{item.get('id','')}",
                "date":        item.get("submission_date", item.get("pd", "")),
                "country":     item.get("country_name", ""),
            })
    except Exception as e:
        print(f"[World Bank API] {e}")

    # Fallback: HTML scrape
    if not notices:
        try:
            resp = requests.get(
                "https://projects.worldbank.org/en/projects-operations/procurement",
                headers=HEADERS, timeout=30
            )
            soup = BeautifulSoup(resp.text, "html.parser")
            for row in soup.select("tr.odd, tr.even")[:30]:
                cols = row.find_all("td")
                if len(cols) >= 2:
                    a = cols[0].find("a")
                    notices.append({
                        "source":      "World Bank",
                        "title":       a.text.strip() if a else cols[0].text.strip(),
                        "description": cols[1].text.strip(),
                        "url":         "https://projects.worldbank.org" + a["href"] if a and a.get("href") else "",
                        "date":        cols[-1].text.strip(),
                        "country":     cols[2].text.strip() if len(cols) > 2 else "",
                    })
        except Exception as e:
            print(f"[World Bank HTML] {e}")

    print(f"  World Bank: {len(notices)} notices")
    return notices


def scrape_afdb():
    notices = []

    # Primary: AfDB procurement page
    try:
        url  = "https://www.afdb.org/en/projects-and-operations/procurement"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".views-row, .procurement-item, article")[:40]:
            title_el = item.find(["h3", "h2", "h4", "a"])
            link_el  = item.find("a")
            desc_el  = item.find(["p", ".field-content"])
            date_el  = item.find(class_=lambda c: c and "date" in c.lower()) if item else None
            if title_el:
                href = link_el["href"] if link_el and link_el.get("href") else ""
                full_url = ("https://www.afdb.org" + href) if href.startswith("/") else href
                notices.append({
                    "source":      "AfDB",
                    "title":       title_el.get_text(strip=True),
                    "description": desc_el.get_text(strip=True) if desc_el else "",
                    "url":         full_url or url,
                    "date":        date_el.get_text(strip=True) if date_el else "",
                    "country":     "",
                })
    except Exception as e:
        print(f"[AfDB] {e}")

    print(f"  AfDB: {len(notices)} notices")
    return notices


def scrape_imf():
    notices = []

    # Primary: IMF procurement page
    try:
        url  = "https://www.imf.org/en/About/Procurement"
        resp = requests.get(url, headers=HEADERS, timeout=30)
        soup = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select(".news-item, .list-item, article, .views-row, li")[:40]:
            title_el = item.find(["h3", "h2", "h4", "a"])
            link_el  = item.find("a")
            desc_el  = item.find("p")
            date_el  = item.find(class_=lambda c: c and "date" in c.lower()) if item else None
            if title_el and len(title_el.get_text(strip=True)) > 10:
                href     = link_el["href"] if link_el and link_el.get("href") else ""
                full_url = ("https://www.imf.org" + href) if href.startswith("/") else href
                notices.append({
                    "source":      "IMF",
                    "title":       title_el.get_text(strip=True),
                    "description": desc_el.get_text(strip=True) if desc_el else "",
                    "url":         full_url or url,
                    "date":        date_el.get_text(strip=True) if date_el else "",
                    "country":     "",
                })
    except Exception as e:
        print(f"[IMF] {e}")

    # Secondary: IMF technical assistance / consultancy listings
    try:
        ta_url = "https://www.imf.org/en/Capacity-Development"
        resp   = requests.get(ta_url, headers=HEADERS, timeout=30)
        soup   = BeautifulSoup(resp.text, "html.parser")
        for item in soup.select("article, .list-item")[:20]:
            title_el = item.find(["h3", "h2", "a"])
            link_el  = item.find("a")
            if title_el and len(title_el.get_text(strip=True)) > 10:
                href     = link_el["href"] if link_el and link_el.get("href") else ""
                full_url = ("https://www.imf.org" + href) if href.startswith("/") else href
                notices.append({
                    "source":      "IMF",
                    "title":       title_el.get_text(strip=True),
                    "description": "IMF Capacity Development opportunity",
                    "url":         full_url or ta_url,
                    "date":        "",
                    "country":     "",
                })
    except Exception as e:
        print(f"[IMF CD] {e}")

    print(f"  IMF: {len(notices)} notices")
    return notices


# ── AI Filtering with Groq (Llama 3) ─────────────────────────────────────────

def filter_with_groq(notices: list[dict]) -> list[dict]:
    if not notices:
        return []

    # Trim to avoid token limits — send title + description only
    slim = [
        {
            "id":          i,
            "source":      n["source"],
            "title":       n["title"][:200],
            "description": n.get("description", "")[:300],
        }
        for i, n in enumerate(notices)
    ]

    prompt = f"""You are a procurement analyst for a digital development organisation.

Review these procurement notices and identify those relevant to ANY of:
- Digital skilling / digital literacy
- AI skilling or AI training programs  
- Job matching platforms or employment technology
- Capacity building (especially in digital/tech sectors)
- Workforce development, upskilling, reskilling
- EdTech, e-learning platforms
- Labor market information systems
- Human capital development with a digital/tech angle

Notices (JSON):
{json.dumps(slim, indent=2)}

Return a JSON array. Each element must have:
- "id": the original id number
- "relevance_score": integer 1-10
- "relevance_reason": one sentence
- "themes": array of matched themes

Only include notices with relevance_score >= 6.
Respond with ONLY the JSON array, no markdown, no explanation."""

    try:
        response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",   # free, fast, accurate
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=2048,
        )
        text = response.choices[0].message.content.strip()
        # Strip markdown fences if present
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        scored = json.loads(text.strip())

        # Re-attach full notice data
        result = []
        for s in scored:
            original = notices[s["id"]]
            result.append({
                **original,
                "relevance_score":  s.get("relevance_score", 0),
                "relevance_reason": s.get("relevance_reason", ""),
                "themes":           s.get("themes", []),
            })
        return result

    except Exception as e:
        print(f"[Groq filtering error] {e}")
        # Graceful fallback: keyword match
        return keyword_fallback(notices)


def keyword_fallback(notices: list[dict]) -> list[dict]:
    """Simple keyword filter used only if Groq fails."""
    keywords = [
        "digital skill", "digital literac", "ai skill", "ai training",
        "job match", "capacity build", "workforce", "upskill", "reskill",
        "edtech", "e-learning", "elearning", "vocational", "labor market",
        "employment platform", "human capital",
    ]
    results = []
    for n in notices:
        text  = (n["title"] + " " + n.get("description", "")).lower()
        hits  = [k for k in keywords if k in text]
        if hits:
            results.append({
                **n,
                "relevance_score":  6,
                "relevance_reason": f"Matched keywords: {', '.join(hits[:3])}",
                "themes":           hits[:4],
            })
    return results


# ── Email builder ─────────────────────────────────────────────────────────────

def build_email_html(notices: list[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    count = len(notices)

    rows = ""
    for n in sorted(notices, key=lambda x: x.get("relevance_score", 0), reverse=True):
        score       = n.get("relevance_score", "N/A")
        score_color = "#27ae60" if score >= 8 else "#e67e22" if score >= 6 else "#e74c3c"
        themes      = ", ".join(n.get("themes", []))
        country     = n.get("country", "")
        date_str    = n.get("date", "")
        meta        = " · ".join(filter(None, [country, date_str]))

        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:{score_color};color:white;padding:3px 9px;
                         border-radius:12px;font-weight:bold;font-size:13px;">{score}/10</span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;white-space:nowrap;">
            <span style="background:#2471a3;color:white;padding:3px 9px;
                         border-radius:12px;font-size:12px;">{n.get('source','')}</span>
          </td>
          <td style="padding:14px 8px;vertical-align:top;">
            <a href="{n.get('url','#')}" style="color:#1a252f;font-weight:600;
               text-decoration:none;font-size:15px;line-height:1.4;">
              {n.get('title','Untitled')}
            </a>
            {'<br><span style="color:#7f8c8d;font-size:12px;">' + meta + '</span>' if meta else ''}
            {'<br><em style="color:#555;font-size:13px;">' + n.get("relevance_reason","") + '</em>' if n.get("relevance_reason") else ''}
            {'<br><span style="color:#8e44ad;font-size:12px;">🏷 ' + themes + '</span>' if themes else ''}
          </td>
        </tr>"""

    if not rows:
        rows = """<tr><td colspan="3" style="padding:30px;text-align:center;color:#7f8c8d;">
            No relevant procurement notices found today. Check back tomorrow!
        </td></tr>"""

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="font-family:Arial,sans-serif;background:#f0f3f7;margin:0;padding:20px;">
  <div style="max-width:820px;margin:0 auto;background:white;border-radius:12px;
              overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.12);">

    <!-- Header -->
    <div style="background:linear-gradient(135deg,#1a3a5c 0%,#2471a3 100%);
                padding:32px 30px;text-align:center;">
      <h1 style="color:white;margin:0;font-size:24px;letter-spacing:0.5px;">
        🌍 Procurement Intelligence Digest
      </h1>
      <p style="color:#aed6f1;margin:8px 0 0;font-size:15px;">
        Digital Skilling &amp; Capacity Building Opportunities
      </p>
      <p style="color:#85c1e9;margin:6px 0 0;font-size:13px;">
        {today} &nbsp;·&nbsp; AfDB &nbsp;·&nbsp; World Bank &nbsp;·&nbsp; IMF
      </p>
    </div>

    <!-- Summary bar -->
    <div style="background:#eaf4fd;padding:14px 30px;border-bottom:2px solid #d6eaf8;
                display:flex;align-items:center;gap:12px;">
      <strong style="color:#1a3a5c;font-size:16px;">📊 {count} relevant notice{'s' if count != 1 else ''} found</strong>
      <span style="color:#7f8c8d;font-size:13px;">Filtered by Groq / Llama 3 · Sorted by relevance score</span>
    </div>

    <!-- Notices table -->
    <div style="padding:20px 24px;">
      <table width="100%" cellpadding="0" cellspacing="0"
             style="border-collapse:collapse;">
        <thead>
          <tr style="background:#f4f6f8;">
            <th style="padding:10px 8px;text-align:left;color:#666;
                       font-size:11px;text-transform:uppercase;width:64px;">Score</th>
            <th style="padding:10px 8px;text-align:left;color:#666;
                       font-size:11px;text-transform:uppercase;width:90px;">Source</th>
            <th style="padding:10px 8px;text-align:left;color:#666;
                       font-size:11px;text-transform:uppercase;">Opportunity</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </div>

    <!-- Footer -->
    <div style="background:#f4f6f8;padding:16px 30px;text-align:center;
                border-top:1px solid #dde4ea;">
      <p style="color:#aab0b8;font-size:12px;margin:0;">
        Auto-generated by your GitHub Actions Procurement Bot &nbsp;·&nbsp;
        Powered by Groq (Llama 3) &nbsp;·&nbsp; 100% Free
      </p>
    </div>
  </div>
</body>
</html>"""


def send_email(html_body: str, count: int):
    subject = (
        f"[Procurement Bot] {count} Digital Skilling Opportunit{'ies' if count != 1 else 'y'} "
        f"— {datetime.now().strftime('%b %d, %Y')}"
    )
    msg             = MIMEMultipart("alternative")
    msg["Subject"]  = subject
    msg["From"]     = EMAIL_SENDER
    msg["To"]       = EMAIL_RECIPIENT
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())

    print(f"✅  Email sent → {EMAIL_RECIPIENT}  ({count} notices)")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    print("🔍 Scraping procurement sources…")
    all_notices = []
    all_notices.extend(scrape_world_bank())
    all_notices.extend(scrape_afdb())
    all_notices.extend(scrape_imf())
    print(f"   Total raw notices: {len(all_notices)}")

    # Deduplicate by title
    seen, unique = set(), []
    for n in all_notices:
        key = n["title"].strip().lower()[:80]
        if key and key not in seen:
            seen.add(key)
            unique.append(n)
    print(f"   After dedup: {len(unique)}")

    print("🤖 Filtering with Groq / Llama 3…")
    relevant = filter_with_groq(unique)
    print(f"   Relevant notices: {len(relevant)}")

    print("📧 Sending email digest…")
    html = build_email_html(relevant)
    send_email(html, len(relevant))


if __name__ == "__main__":
    main()

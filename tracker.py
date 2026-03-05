"""
Procurement Intelligence Bot — v7

Architecture:
  SEARCH : Tavily API — purpose-built web search for AI agents
           Free tier: 1,000 searches/month, no credit card needed
           Signs up at: https://tavily.com
  FILTER : Groq / Llama 3.3 (free)
  EMAIL  : Gmail SMTP (free)
  HOSTING: GitHub Actions (free)
"""

import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from groq import Groq

TAVILY_API_KEY  = os.environ["TAVILY_API_KEY"]
GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]

groq_client = Groq(api_key=GROQ_API_KEY)

HEADERS = {"Content-Type": "application/json"}

# ─────────────────────────────────────────────────────────────────────────────
# Search queries — targeted at the exact sources and topics you care about
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_QUERIES = [
    'AfDB procurement "digital skills" OR "capacity building" OR "youth employment" tender 2025',
    'AfDB procurement "skills development" OR "entrepreneurship" OR "job matching" 2025',
    'World Bank procurement "digital skills" OR "youth employment" OR "capacity building" tender 2025',
    'World Bank procurement "skills development" OR "entrepreneurship" OR "workforce" 2025',
    'IMF procurement tender "digital skills" OR "capacity building" OR "training" 2025',
    'UNDP procurement tender "digital skills" OR "youth employment" OR "capacity building" 2025',
    'EU tender "digital skills training" OR "capacity building" OR "youth employment" Africa 2025',
    'RFP tender "digital skills" OR "job matching platform" Africa development 2025',
    'procurement tender "AI skills training" OR "entrepreneurship development" Africa 2025',
    'procurement RFP "skills development" OR "vocational training" Africa multilateral 2025',
]


# ─────────────────────────────────────────────────────────────────────────────
# DEADLINE EXTRACTION — fetch each page and pull out closing date
# ─────────────────────────────────────────────────────────────────────────────

import re
from datetime import date

# Patterns that indicate a deadline/closing date in page text
DEADLINE_PATTERNS = [
    r'(?:closing|deadline|submission|due|apply by|closes?|applications? due)[^\d]{0,30}(\d{1,2}[\s/-]\w+[\s/-]\d{2,4})',
    r'(?:closing|deadline|submission|due|apply by|closes?)[^\d]{0,30}(\d{4}-\d{2}-\d{2})',
    r'(?:closing|deadline|submission|due|apply by|closes?)[^\d]{0,30}(\w+ \d{1,2},?\s*\d{4})',
    r'(\d{1,2}[\s/-]\w+[\s/-]\d{4})(?:[^\w]{0,20}(?:closing|deadline|due))',
]

MONTH_MAP = {
    'jan':1,'feb':2,'mar':3,'apr':4,'may':5,'jun':6,
    'jul':7,'aug':8,'sep':9,'oct':10,'nov':11,'dec':12,
    'january':1,'february':2,'march':3,'april':4,'june':6,
    'july':7,'august':8,'september':9,'october':10,'november':11,'december':12,
}

def parse_date_str(s: str):
    """Try to parse a date string into a date object. Returns None if unparseable."""
    s = s.strip().lower().replace(',', '')
    # Try YYYY-MM-DD
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        try: return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except: pass
    # Try DD Month YYYY or Month DD YYYY
    m = re.match(r'(\d{1,2})\s+(\w+)\s+(\d{4})', s)
    if m:
        mon = MONTH_MAP.get(m.group(2)[:3])
        if mon:
            try: return date(int(m.group(3)), mon, int(m.group(1)))
            except: pass
    m = re.match(r'(\w+)\s+(\d{1,2})\s+(\d{4})', s)
    if m:
        mon = MONTH_MAP.get(m.group(1)[:3])
        if mon:
            try: return date(int(m.group(3)), mon, int(m.group(2)))
            except: pass
    # Try DD/MM/YYYY or MM/DD/YYYY
    m = re.match(r'(\d{1,2})[/-](\d{1,2})[/-](\d{4})', s)
    if m:
        try: return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except: pass
    return None


def fetch_deadline(url: str) -> tuple[str, str]:
    """
    Fetch a procurement page and extract the deadline.
    Returns (deadline_str, status) where status is 'open', 'closed', or 'unknown'.
    Uses Tavily Extract API — same key, no extra cost.
    """
    if not url or url == "#":
        return "", "unknown"
    try:
        resp = requests.post(
            "https://api.tavily.com/extract",
            json={"api_key": TAVILY_API_KEY, "urls": [url]},
            headers=HEADERS,
            timeout=20,
        )
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        text    = results[0].get("raw_content", "") if results else ""
        if not text:
            return "", "unknown"

        text_lower = text.lower()
        today      = date.today()

        for pattern in DEADLINE_PATTERNS:
            matches = re.findall(pattern, text_lower, re.IGNORECASE)
            for match in matches:
                d = parse_date_str(match)
                if d:
                    status = "open" if d >= today else "closed"
                    return d.strftime("%B %d, %Y"), status

        return "", "unknown"

    except Exception as e:
        return "", "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Search with Tavily
# ─────────────────────────────────────────────────────────────────────────────

def search_tavily(query: str) -> list[dict]:
    """Run a single Tavily search and return raw results."""
    try:
        resp = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key":        TAVILY_API_KEY,
                "query":          query,
                "search_depth":   "basic",
                "max_results":    8,
                "include_answer": False,
            },
            headers=HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except Exception as e:
        print(f"    [Tavily error] {e}")
        return []


def collect_all_results() -> list[dict]:
    """Run all search queries and deduplicate results."""
    all_results = []
    seen_urls   = set()
    seen_titles = set()

    print(f"  Running {len(SEARCH_QUERIES)} searches via Tavily…")

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"    [{i}/{len(SEARCH_QUERIES)}] {query[:80]}…")
        results = search_tavily(query)

        for r in results:
            url   = (r.get("url") or "").strip()
            title = (r.get("title") or "").strip()

            # Skip duplicates
            url_key   = url.lower()[:120]
            title_key = title.lower()[:80]
            if url_key in seen_urls or title_key in seen_titles:
                continue
            if url_key:
                seen_urls.add(url_key)
            if title_key:
                seen_titles.add(title_key)

            # Determine source from URL
            source = "Web"
            if "afdb.org" in url:               source = "AfDB"
            elif "worldbank.org" in url:         source = "World Bank"
            elif "imf.org" in url:               source = "IMF"
            elif "undp.org" in url:              source = "UNDP"
            elif "ted.europa.eu" in url:         source = "TED (EU Tenders)"
            elif "reliefweb.int" in url:         source = "ReliefWeb"
            elif "usaid.gov" in url:             source = "USAID"
            elif "ungm.org" in url:              source = "UNGM"
            elif "devex.com" in url:             source = "DevEx"
            elif "unicef.org" in url:            source = "UNICEF"

            all_results.append({
                "source":      source,
                "title":       title,
                "description": (r.get("content") or r.get("snippet") or "")[:400],
                "url":         url,
                "date":        r.get("published_date", ""),
                "country":     "",
            })

    print(f"  Total unique results: {len(all_results)}")
    return all_results


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Filter with Groq
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

    today_str  = datetime.now().strftime("%Y-%m-%d")
    all_scored = []
    batch_size = 30

    for start in range(0, len(slim), batch_size):
        batch  = slim[start: start + batch_size]
        prompt = f"""You are a procurement analyst for a digital development organisation in Africa.
Today's date is {today_str}.

Review these search results. Flag ONLY results that are ACTUAL PROCUREMENT OPPORTUNITIES:
tenders, RFPs, contracts, consultancies, grants, calls for proposals.
Do NOT flag news articles, blog posts, reports, or general programme pages.

IMPORTANT — STATUS CHECK:
- Read the description carefully for any closing date, deadline, or submission date
- If a deadline is mentioned and it has already passed (before {today_str}), mark status "closed" and EXCLUDE it
- If the deadline is still in the future, mark status "open"
- If no deadline is mentioned, mark status "unknown" and still include it

Mark relevant if about ANY of these themes:
- Digital skills / digital literacy training
- Youth training or youth employment programs
- Skills development
- Capacity building (digital or tech focus)
- Entrepreneurship support or training
- Job matching or employment technology
- AI skills or AI training programs
- Workforce development / upskilling / reskilling
- EdTech or e-learning platforms
- Labor market information systems

Results to review:
{json.dumps(batch, indent=2)}

Return a JSON array only. Each item must have:
- "id": original id (integer)
- "relevance_score": 1-10 (10 = perfect procurement match)
- "relevance_reason": one sentence explaining why
- "themes": list of 1-3 matched themes from above
- "status": "open", "closed", or "unknown"
- "deadline": the closing date if found in text, else ""

Only include items with relevance_score >= 6.
Do NOT include items where status is "closed".
Return [] if nothing qualifies.
Respond with ONLY the JSON array — no markdown, no explanation."""

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
            print(f"    [Groq batch error] {e}")

    result, seen = [], set()
    for s in all_scored:
        idx = s.get("id")
        if not isinstance(idx, int) or idx >= len(notices):
            continue
        if s.get("status") == "closed":
            continue
        original = notices[idx]
        key = original["title"].lower()[:80]
        if key in seen:
            continue
        seen.add(key)
        result.append({
            **original,
            "relevance_score":  s.get("relevance_score", 0),
            "relevance_reason": s.get("relevance_reason", ""),
            "themes":           s.get("themes", []),
            "status":           s.get("status", "unknown"),
            "deadline":         s.get("deadline", ""),
        })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL
# ─────────────────────────────────────────────────────────────────────────────

SOURCE_COLORS = {
    "World Bank": "#1a6ea8",
    "AfDB":       "#c0392b",
    "TED":        "#2e86ab",
    "UNDP":       "#009edb",
    "IMF":        "#8e44ad",
    "USAID":      "#002868",
    "ReliefWeb":  "#d35400",
    "UNICEF":     "#00aeef",
    "UNGM":       "#16a085",
    "DevEx":      "#7f8c8d",
}

def _src_color(source: str) -> str:
    for k, v in SOURCE_COLORS.items():
        if k in source:
            return v
    return "#2c3e50"


def build_email_html(notices: list[dict]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    count = len(notices)
    rows  = ""

    for n in sorted(notices, key=lambda x: x.get("relevance_score", 0), reverse=True):
        score       = n.get("relevance_score", "N/A")
        score_color = ("#27ae60" if isinstance(score, int) and score >= 8
                       else "#e67e22" if isinstance(score, int) and score >= 6
                       else "#e74c3c")
        src      = n.get("source", "")
        themes   = ", ".join(n.get("themes", []))
        status   = n.get("status", "unknown")
        deadline = n.get("deadline", "")
        meta     = " · ".join(filter(None, [n.get("country",""), str(n.get("date",""))[:10]]))
        url      = n.get("url") or "#"

        # Status badge
        if status == "open":
            status_badge = '<span style="background:#27ae60;color:white;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">✅ OPEN</span>'
        elif status == "closed":
            status_badge = '<span style="background:#e74c3c;color:white;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">❌ CLOSED</span>'
        else:
            status_badge = '<span style="background:#95a5a6;color:white;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">❓ CHECK DEADLINE</span>'

        deadline_str = f' &nbsp;·&nbsp; <strong>Deadline:</strong> {deadline}' if deadline else ""

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
            <br>{status_badge}{deadline_str}
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
        {today} &nbsp;·&nbsp; AfDB &nbsp;·&nbsp; World Bank &nbsp;·&nbsp; IMF
        &nbsp;·&nbsp; UNDP &nbsp;·&nbsp; TED &nbsp;·&nbsp; USAID &amp; more
      </p>
    </div>
    <div style="background:#eaf4fd;padding:14px 30px;border-bottom:2px solid #d6eaf8;">
      <strong style="color:#1a3a5c;font-size:16px;">
        📊 {count} relevant opportunit{'ies' if count != 1 else 'y'} found
      </strong>
      <span style="color:#7f8c8d;font-size:13px;margin-left:10px;">
        Sourced via Tavily · AI-filtered by Groq · Links direct to notices
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
        Procurement Bot · GitHub Actions · Tavily + Groq · 100% Free
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
    print("🔍 Searching for procurement notices via Tavily…")
    notices = collect_all_results()

    if not notices:
        print("⚠️  No results from any search.")
        send_email(build_email_html([]), 0)
        return

    print("🤖 Filtering with Groq / Llama 3.3…")
    relevant = filter_with_groq(notices)
    print(f"   Relevant: {len(relevant)}")

    # Fetch actual deadlines by visiting each page
    print("📅 Fetching deadlines from notice pages…")
    confirmed = []
    for n in relevant:
        # Skip fetching if Groq already found a real deadline
        if n.get("deadline") and n.get("status") in ("open", "closed"):
            if n.get("status") == "closed":
                print(f"    Skipping closed: {n['title'][:60]}")
                continue
            confirmed.append(n)
            continue

        deadline, status = fetch_deadline(n.get("url", ""))
        if status == "closed":
            print(f"    Closed (deadline passed): {n['title'][:60]}")
            continue  # drop it
        n["deadline"] = deadline or n.get("deadline", "")
        n["status"]   = status
        confirmed.append(n)

    print(f"   After deadline check: {len(confirmed)} open/unknown notices")

    print("📧 Sending email digest…")
    send_email(build_email_html(confirmed), len(confirmed))


if __name__ == "__main__":
    main()

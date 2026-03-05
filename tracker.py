"""
Procurement Intelligence Bot — v6

Key insight: Most procurement APIs block GitHub Actions IPs.
Solution: Use Groq's built-in web_search tool — Groq fetches the web
on our behalf from their own servers, bypassing all IP blocks.

Groq searches for procurement notices, returns structured results,
then we filter and email them.

AI      : Groq / Llama 3.3 with web_search tool (free)
Email   : Gmail SMTP (free)
Hosting : GitHub Actions (free)
"""

import os
import json
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from groq import Groq

GROQ_API_KEY    = os.environ["GROQ_API_KEY"]
EMAIL_SENDER    = os.environ["EMAIL_SENDER"]
EMAIL_PASSWORD  = os.environ["EMAIL_PASSWORD"]
EMAIL_RECIPIENT = os.environ["EMAIL_RECIPIENT"]

groq_client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1: Use Groq web search to find procurement notices
# Groq fetches from its own servers — not blocked like GitHub Actions IPs
# ─────────────────────────────────────────────────────────────────────────────

SEARCH_QUERIES = [
    # AfDB specific
    'site:afdb.org procurement "digital skills" OR "capacity building" OR "youth employment" 2024 OR 2025',
    'site:afdb.org procurement "skills development" OR "entrepreneurship" OR "job matching"',
    # World Bank specific
    'site:worldbank.org OR site:projects.worldbank.org procurement "digital skills" OR "youth employment" OR "capacity building"',
    'site:worldbank.org procurement "skills development" OR "entrepreneurship" OR "workforce development"',
    # IMF specific
    'site:imf.org procurement OR tender "digital skills" OR "capacity building" OR "training"',
    # EU TED
    'site:ted.europa.eu "digital skills" OR "capacity building" OR "youth employment" tender 2024 OR 2025',
    # UNDP / UN
    'site:undp.org procurement "digital skills" OR "capacity building" OR "youth employment" tender',
    'procurement tender "digital skills training" Africa 2025',
    'RFP "capacity building" "youth employment" Africa multilateral 2025',
    'tender "job matching platform" OR "skills development" Africa development bank 2025',
]


def search_for_notices() -> list[dict]:
    """Use Groq web search tool to find procurement notices."""
    all_notices = []
    seen_titles = set()

    print(f"  Running {len(SEARCH_QUERIES)} web searches via Groq…")

    for i, query in enumerate(SEARCH_QUERIES, 1):
        print(f"    [{i}/{len(SEARCH_QUERIES)}] {query[:80]}…")
        try:
            response = groq_client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a procurement research assistant. "
                            "When given a search query, search the web and extract procurement notices. "
                            "Return ONLY a JSON array of results. Each item must have: "
                            "title, url, source, description, date, country. "
                            "Only include actual procurement opportunities (tenders, RFPs, contracts, grants). "
                            "If no relevant results found, return []."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Search for: {query}\n\n"
                            "Return results as a JSON array with fields: "
                            "title, url, source, description, date, country. "
                            "Only actual procurement opportunities. Return [] if none found."
                        ),
                    },
                ],
                tools=[{"type": "web_search"}],
                tool_choice="auto",
                max_tokens=2048,
            )

            # Extract text from response (may include tool use blocks)
            full_text = ""
            for block in response.choices[0].message.content if isinstance(response.choices[0].message.content, list) else []:
                if hasattr(block, "text"):
                    full_text += block.text
            if not full_text:
                full_text = response.choices[0].message.content or ""

            # Parse JSON from response
            if "[" in full_text and "]" in full_text:
                start = full_text.index("[")
                end   = full_text.rindex("]") + 1
                json_str = full_text[start:end]
                results  = json.loads(json_str)

                for item in results:
                    title = (item.get("title") or "").strip()
                    if not title or len(title) < 6:
                        continue
                    key = title.lower()[:80]
                    if key in seen_titles:
                        continue
                    seen_titles.add(key)
                    all_notices.append({
                        "source":      item.get("source", "Web Search"),
                        "title":       title,
                        "description": (item.get("description") or "")[:300],
                        "url":         item.get("url", ""),
                        "date":        item.get("date", ""),
                        "country":     item.get("country", ""),
                    })

        except json.JSONDecodeError:
            pass  # Model returned text instead of JSON — skip
        except Exception as e:
            print(f"      [Search error] {e}")

    print(f"  Found {len(all_notices)} unique notices from web search")
    return all_notices


# ─────────────────────────────────────────────────────────────────────────────
# STEP 2: Score and filter with Groq
# ─────────────────────────────────────────────────────────────────────────────

def score_notices(notices: list[dict]) -> list[dict]:
    """Score already-filtered notices for relevance and quality."""
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
    batch_size = 30

    for start in range(0, len(slim), batch_size):
        batch  = slim[start: start + batch_size]
        prompt = f"""You are a procurement analyst for a digital development organisation in Africa.

Score these procurement notices for relevance. Only flag ACTUAL procurement opportunities
(tenders, RFPs, contracts, consultancies, grants, calls for proposals).

Relevant if about ANY of:
- Digital skills / literacy training
- Youth training or employment programs
- Skills development / capacity building (digital/tech)
- Entrepreneurship support or training
- Job matching or employment technology
- AI skills / training programs
- Workforce development / upskilling / reskilling
- EdTech / e-learning platforms
- Labor market systems

Notices:
{json.dumps(batch, indent=2)}

Return a JSON array. Each item:
- "id": original id (integer)
- "relevance_score": 1-10
- "relevance_reason": one sentence
- "themes": list of 1-3 themes

Only include relevance_score >= 6. Return [] if nothing qualifies.
ONLY the JSON array — no markdown."""

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
            print(f"    [Scoring error] {e}")

    result, seen = [], set()
    for s in all_scored:
        idx = s.get("id")
        if not isinstance(idx, int) or idx >= len(notices):
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
        src    = n.get("source", "")
        themes = ", ".join(n.get("themes", []))
        meta   = " · ".join(filter(None, [n.get("country",""), str(n.get("date",""))[:10]]))
        url    = n.get("url") or "#"

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
        {today} &nbsp;·&nbsp; AfDB &nbsp;·&nbsp; World Bank &nbsp;·&nbsp; IMF
        &nbsp;·&nbsp; UNDP &nbsp;·&nbsp; TED &nbsp;·&nbsp; USAID
      </p>
    </div>
    <div style="background:#eaf4fd;padding:14px 30px;border-bottom:2px solid #d6eaf8;">
      <strong style="color:#1a3a5c;font-size:16px;">
        📊 {count} relevant opportunit{'ies' if count != 1 else 'y'} found
      </strong>
      <span style="color:#7f8c8d;font-size:13px;margin-left:10px;">
        Sourced via Groq web search · AI-filtered · Links direct to notices
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
    print("🔍 Searching for procurement notices via Groq web search…")
    notices = search_for_notices()

    if not notices:
        print("⚠️  No notices found from any search.")
        send_email(build_email_html([]), 0)
        return

    print("🤖 Scoring and filtering results…")
    relevant = score_notices(notices)
    print(f"   Relevant: {len(relevant)}")

    print("📧 Sending email digest…")
    send_email(build_email_html(relevant), len(relevant))


if __name__ == "__main__":
    main()

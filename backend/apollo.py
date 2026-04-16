import os
import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
BASE_URL = "https://api.apollo.io/api/v1"
HEADERS = {
    "Content-Type": "application/json",
    "X-Api-Key": APOLLO_API_KEY,
}



def _normalize_js_contact(raw: dict) -> dict:
    """
    Normalize contact fields from JS module output to backend format.
    Handles both contact_discovery.js and contact_discovery_linkedin.js outputs.
    """
    return {
        "id": raw.get("id", ""),
        "name": raw.get("full_name") or raw.get("name", ""),
        "title": raw.get("title", ""),
        "company": raw.get("organization_name") or raw.get("company", ""),
        "email": raw.get("email", ""),
        "linkedin_url": raw.get("linkedin_url", ""),
        "city": raw.get("city") or raw.get("location", ""),
        "seniority": raw.get("seniority", ""),
    }


async def enrich_contact(contact: dict) -> dict:
    """
    Enrich a contact via Apollo people/match.
    Works with raw JS module output or normalized contact dicts.
    Returns full profile: email, LinkedIn headline/bio, company insights.
    """
    if not APOLLO_API_KEY:
        print("[Apollo] ERROR: APOLLO_API_KEY not set.")
        return contact

    # Normalize JS module fields if needed
    if "full_name" in contact or "organization_name" in contact:
        contact = _normalize_js_contact(contact)

    try:
        name_parts = (contact.get("name") or "").split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{BASE_URL}/people/match",
                headers=HEADERS,
                json={
                    "first_name": first_name,
                    "last_name": last_name,
                    "organization_name": contact.get("company", ""),
                    "linkedin_url": contact.get("linkedin_url", ""),
                    "reveal_personal_emails": True,
                    "reveal_phone_number": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        person = data.get("person") or {}
        org = person.get("organization") or {}

        enriched = dict(contact)
        enriched.update({
            "email": person.get("email") or contact.get("email", ""),
            "title": person.get("title") or contact.get("title", ""),
            "seniority": person.get("seniority", ""),
            "city": person.get("city", contact.get("city", "")),
            "headline": person.get("headline", ""),        # LinkedIn headline
            "bio": person.get("summary", ""),              # LinkedIn about/summary
            "funding_stage": org.get("latest_funding_stage", ""),
            "headcount": str(org.get("estimated_num_employees", "")),
            "technologies": org.get("technology_names", []),
            "industry": org.get("industry", ""),
            "company_description": org.get("short_description", ""),
        })
        print(f"[Apollo] Enriched: {enriched.get('name')} @ {enriched.get('company')} — email: {bool(enriched.get('email'))}")
        return enriched

    except Exception as e:
        print(f"[Apollo] enrich_contact error: {e}")
        return contact


SYSTEM_PROMPT = """You are an expert assistant that writes short, highly personalized cold outreach emails for job seekers.

Your goal is to help the user get a reply — not to sound impressive.

You optimize for: relevance, clarity, credibility, human tone, brevity.
You do NOT optimize for: sounding formal, sounding corporate, excessive enthusiasm, generic networking language, flattery.

Core writing principles:
- Write like a real person, not a template
- Keep emails concise (70–120 words)
- Use simple, natural language
- Avoid buzzwords and filler
- Prefer specific details over vague statements
- Make the email easy to reply to

Personalization rules:
- Only use information explicitly provided in the input
- Do NOT invent details about the contact or the candidate
- If limited information is available, use a light and natural tone instead of forcing deep personalization
- Use the contact's role and company as the primary anchor for relevance

Structure:
1. Opening line: natural, role-based or context-based (no generic phrases)
2. One-line introduction of the candidate
3. One relevant skill, project, or area of interest
4. A light connection to the contact's role (e.g., recruiting, engineering, hiring)
5. A soft, low-pressure closing

Strict rules:
- Do NOT say "I hope you're doing well"
- Do NOT say "I came across your profile"
- Do NOT say "I am passionate about"
- Do NOT directly ask for a job
- Do NOT overpraise the recipient
- Do NOT use generic phrases like "excited to connect"

Tone: calm and confident, slightly informal but respectful, concise and thoughtful, written like it took under 2 minutes to write.

Output: Return ONLY the email body text. No subject line. No explanations. No bullet points."""


async def generate_personalized_email(candidate: dict, contact: dict) -> dict:
    """
    Generate a personalized cold email using the contact's LinkedIn + Apollo data
    and the candidate's extracted profile. Uses Groq llama-3.3-70b-versatile.
    """
    client = AsyncOpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

    # Candidate fields — works with both raw profile and extracted profile
    c_name = candidate.get("name") or candidate.get("full_name", "")
    c_title = candidate.get("current_title") or candidate.get("background_summary", "")
    c_goal_raw = candidate.get("goal") or ""
    if not c_goal_raw and isinstance(candidate.get("job_preferences"), dict):
        roles = candidate["job_preferences"].get("target_roles", [])
        c_goal_raw = roles[0] if roles else ""
    skills = candidate.get("key_skills") or candidate.get("skills", [])
    skills_str = ", ".join(skills[:5]) if skills else ""
    past_cos = ", ".join((candidate.get("past_companies") or [])[:3])
    notable = ""
    projects = candidate.get("notable_projects") or []
    if projects:
        p = projects[0]
        notable = f"{p.get('title', '')}: {p.get('impact') or p.get('description', '')}"

    # Contact fields — from both contact_discovery and contact_discovery_linkedin
    co_name = contact.get("name") or contact.get("full_name", "")
    co_title = contact.get("title", "")
    co_company = contact.get("company") or contact.get("organization_name", "")
    co_headline = contact.get("headline", "")
    co_bio = contact.get("bio", "")
    co_company_desc = contact.get("company_description", "")
    co_industry = contact.get("industry", "")
    co_tech = ", ".join((contact.get("technologies") or [])[:4])
    co_funding = contact.get("funding_stage", "")
    co_headcount = contact.get("headcount", "")

    contact_context = "\n".join(filter(None, [
        f"LinkedIn headline: {co_headline}" if co_headline else "",
        f"LinkedIn summary: {co_bio}" if co_bio else "",
        f"Company description: {co_company_desc}" if co_company_desc else "",
        f"Industry: {co_industry}" if co_industry else "",
        f"Tech stack: {co_tech}" if co_tech else "",
        f"Funding stage: {co_funding}" if co_funding else "",
        f"Company size: ~{co_headcount} employees" if co_headcount else "",
    ])) or "No additional context available."

    user_prompt = f"""Write a cold outreach email from this job seeker to this contact.

--- CANDIDATE ---
Name: {c_name}
Current role / background: {c_title}
Target role: {c_goal_raw}
Skills: {skills_str}
Past companies: {past_cos}
Notable achievement: {notable}

--- CONTACT ---
Name: {co_name}
Title: {co_title}
Company: {co_company}
{contact_context}

Generate the subject line separately on the first line as:
Subject: [subject]

Then the email body (70–120 words, no subject line in body):"""

    try:
        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=500,
            temperature=0.85,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"[Apollo] generate_personalized_email error: {e}")
        return {"subject": f"Quick intro — {c_name}", "body": ""}

    subject, body = "", ""
    lines = raw.strip().split("\n")
    for i, line in enumerate(lines):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
            body = "\n".join(lines[i + 1:]).strip()
            break
    if not subject:
        body = raw.strip()

    return {
        "subject": subject or f"Quick intro — {c_name}",
        "body": body or raw.strip(),
    }


async def process_js_contact(raw_contact: dict, candidate: dict) -> dict:
    """
    Full pipeline for a single JS module contact:
    raw JS output → Apollo enrich (LinkedIn + company data) → personalized email
    Returns enriched contact merged with generated email.
    """
    enriched = await enrich_contact(raw_contact)
    email = await generate_personalized_email(candidate, enriched)
    return {**enriched, **email}


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email via Apollo API."""
    if not APOLLO_API_KEY:
        print(f"[Apollo] Email stored (no API key): {to}")
        return {"success": True, "message_id": f"local_{to.split('@')[0] if '@' in to else 'unknown'}"}

    try:
        html_body = f"<html><body>{body.replace(chr(10), '<br/>')}</body></html>"
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{BASE_URL}/email_accounts/send_email",
                headers=HEADERS,
                json={"to": to, "subject": subject, "body": html_body},
            )
            resp.raise_for_status()
            data = resp.json()

        message_id = data.get("id", "")
        print(f"[Apollo] Email sent to {to} (id: {message_id})")
        return {"success": True, "message_id": message_id}

    except Exception as e:
        print(f"[Apollo] send_email error: {e}")
        return {"success": False, "message_id": "", "error": str(e)}

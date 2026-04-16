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


async def generate_personalized_email(candidate: dict, contact: dict) -> dict:
    """
    Generate a personalized cold email using:
    - candidate: profile from candidate_profile_extractor (name, goal, skills, background)
    - contact: enriched Apollo contact (LinkedIn headline, bio, company insights)
    Uses Groq llama-3.3-70b-versatile via OpenAI-compatible API.
    """
    client = AsyncOpenAI(
        api_key=GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

    # Build context from LinkedIn + Apollo enrichment data
    context_lines = []
    if contact.get("headline"):
        context_lines.append(f"LinkedIn headline: {contact['headline']}")
    if contact.get("bio"):
        context_lines.append(f"LinkedIn summary: {contact['bio']}")
    if contact.get("company_description"):
        context_lines.append(f"Company: {contact['company_description']}")
    if contact.get("industry"):
        context_lines.append(f"Industry: {contact['industry']}")
    if contact.get("funding_stage"):
        context_lines.append(f"Funding stage: {contact['funding_stage']}")
    if contact.get("headcount"):
        context_lines.append(f"Company size: ~{contact['headcount']} employees")
    if contact.get("technologies"):
        context_lines.append(f"Tech stack: {', '.join(contact['technologies'][:5])}")

    # Build candidate context
    skills = candidate.get("key_skills") or candidate.get("skills", [])
    skills_str = ", ".join(skills[:6]) if skills else ""
    past_companies = candidate.get("past_companies", [])
    companies_str = ", ".join(past_companies[:3]) if past_companies else ""

    prompt = f"""Write a personalized cold outreach email from a job seeker to a recruiter/hiring contact.

SENDER (job seeker):
Name: {candidate.get('name') or candidate.get('full_name', '')}
Goal: {candidate.get('goal') or candidate.get('job_preferences', {}).get('target_roles', [''])[0] if isinstance(candidate.get('job_preferences'), dict) else ''}
Skills: {skills_str}
Background: {candidate.get('background_summary') or candidate.get('current_title', '')}
Past companies: {companies_str}

RECIPIENT (contact at {contact.get('company', '')}):
Name: {contact.get('name', '')}
Title: {contact.get('title', '')}
Company: {contact.get('company', '')}
{chr(10).join(context_lines) if context_lines else 'No additional LinkedIn/company context available.'}

Rules:
- Max 5 sentences
- Reference something specific from their LinkedIn or company (if available)
- Do NOT say "I hope this email finds you well"
- End with a specific ask: 15-minute call or coffee chat
- Warm, professional, not desperate

Format exactly:
Subject: [subject line]
Body:
[email body]"""

    try:
        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"[Apollo] generate_personalized_email error: {e}")
        return {
            "subject": f"Quick intro — {candidate.get('name', '')}",
            "body": "",
        }

    subject, body, in_body = "", "", False
    for line in raw.strip().split("\n"):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        elif line.startswith("Body:"):
            in_body = True
        elif in_body:
            body += line + "\n"

    return {
        "subject": subject or f"Quick intro — {candidate.get('name', '')}",
        "body": body.strip() or raw.strip(),
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

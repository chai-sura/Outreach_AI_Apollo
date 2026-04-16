import os
import json
import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

MODEL = "gpt-4o-mini"
_client: AsyncOpenAI | None = None

# ── Module imports ────────────────────────────────────────────────────────────
# These are implemented by the algorithm team in the modules/ folder.
# After a `git pull` + server restart they are picked up automatically.
# If not yet available, built-in fallbacks keep the pipeline running.

try:
    from modules.candidate_profile_extractor import extract_profile as _extract_profile  # type: ignore
    print("[Agent] ✅ Using modules.candidate_profile_extractor")
except ImportError:
    _extract_profile = None
    print("[Agent] ⚠️  modules.candidate_profile_extractor not found — using fallback")

try:
    from modules.contact_search import search_and_enrich as _search_and_enrich  # type: ignore
    print("[Agent] ✅ modules.contact_search")
except ImportError:
    _search_and_enrich = None
    print("[Agent] ⚠️  modules.contact_search not found — using apollo fallback")

try:
    from modules.email_generator import generate as _generate_email
    print("[Agent] ✅ modules.email_generator")
except ImportError:
    _generate_email = None
    print("[Agent] ⚠️  modules.email_generator not found — using fallback")


# ── OpenAI client ─────────────────────────────────────────────────────────────

def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY", ""))
    return _client


def parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except Exception:
        return {}


async def call_openai(prompt: str, system: str = "", max_tokens: int = 500) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        print("[Agent] No OPENAI_API_KEY set")
        return "{}"
    client = get_client()
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        response = await client.chat.completions.create(
            model=MODEL,
            max_tokens=max_tokens,
            messages=messages,
        )
        return response.choices[0].message.content or "{}"
    except Exception as e:
        print(f"[Agent] OpenAI call failed: {e}")
        return "{}"


# ── Step 1: Contact search ────────────────────────────────────────────────────

async def search_contacts(query: str, limit: int = 5) -> list[dict]:
    if _search_and_enrich is not None:
        return await _search_and_enrich(query, limit=limit)
    import apollo
    contacts = await apollo.search_contacts(query, limit=limit)
    enriched = await asyncio.gather(*[apollo.enrich_contact(c) for c in contacts])
    return list(enriched)


# ── Step 2: Candidate profile extraction ─────────────────────────────────────

def extract_candidate_profile(user_profile: dict) -> dict:
    """
    Uses modules.candidate_profile_extractor.extract_profile() if available.
    Falls back to raw profile fields until the module is merged.
    """
    if _extract_profile is not None:
        return _extract_profile(
            resume_text=user_profile.get("resume_text", ""),
            name=user_profile.get("name", ""),
            goal=user_profile.get("goal", ""),
        )

    # Fallback — passes raw fields directly into email generation
    return {
        "name": user_profile.get("name", ""),
        "goal": user_profile.get("goal", ""),
        "key_skills": [],
        "years_experience": 0,
        "background_summary": user_profile.get("resume_text", "")[:300].strip(),
        "unique_value": user_profile.get("goal", ""),
        "tone_preference": "casual",
        "industries": [],
        "past_companies": [],
    }


# ── Step 2: Email generation ──────────────────────────────────────────────────

async def generate_email(candidate: dict, contact: dict) -> dict:
    """
    Uses modules.email_generator.generate() if available.
    Falls back to built-in OpenAI generation using LinkedIn/Apollo contact data.
    """
    if _generate_email is not None:
        return await _generate_email(candidate, contact)

    # Fallback — built-in generation using enriched Apollo data
    name = candidate.get("name", "")
    goal = candidate.get("goal", "")
    background = candidate.get("background_summary", "") or candidate.get("resume_text", "")[:400]
    skills = ", ".join(candidate.get("key_skills", [])[:4])

    contact_name = contact.get("name", "")
    contact_title = contact.get("title", "")
    company = contact.get("company", "")
    headline = contact.get("headline", "")          # LinkedIn headline from Apollo
    bio = contact.get("bio", "")                    # LinkedIn summary from Apollo
    industry = contact.get("industry", "")
    funding = contact.get("funding_stage", "")
    technologies = ", ".join(contact.get("technologies", [])[:5])
    company_desc = contact.get("company_description", "")

    # Build contact context from what Apollo returned
    contact_context_lines = []
    if headline:
        contact_context_lines.append(f"LinkedIn headline: {headline}")
    if bio:
        contact_context_lines.append(f"LinkedIn summary: {bio}")
    if company_desc:
        contact_context_lines.append(f"About company: {company_desc}")
    if funding:
        contact_context_lines.append(f"Funding stage: {funding}")
    if technologies:
        contact_context_lines.append(f"Tech stack: {technologies}")
    if industry:
        contact_context_lines.append(f"Industry: {industry}")
    contact_context = "\n".join(contact_context_lines) or "No additional context available."

    system = """You are an expert cold email writer. Rules:
- Max 5 sentences total
- First sentence: reference something specific about their company or role
- Never open with: "I hope this finds you well", "I came across your profile", "I wanted to reach out"
- End with a soft ask for a 15-minute call
- Be direct, human, confident
- Output ONLY the email in this exact format (no markdown):
Subject: [subject line]
Body:
[email body]"""

    prompt = f"""Write a personalized cold outreach email.

SENDER:
Name: {name}
Goal: {goal}
Background: {background}
Key skills: {skills or 'N/A'}

RECIPIENT:
Name: {contact_name}
Title: {contact_title}
Company: {company}

CONTACT CONTEXT (LinkedIn + Apollo data):
{contact_context}

Write the email now."""

    raw = await call_openai(prompt, system=system, max_tokens=300)

    subject, body, in_body = "", "", False
    for line in raw.strip().split("\n"):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        elif line.startswith("Body:"):
            in_body = True
        elif in_body:
            body += line + "\n"

    body = body.strip()
    if not subject:
        subject = f"Quick intro — {name}"
    if not body:
        body = raw.strip()

    return {"subject": subject, "body": body}


# ── Orchestrator ──────────────────────────────────────────────────────────────

async def run_agent(user_query: str, user_profile: dict) -> list[dict]:
    """
    Full pipeline — all three steps come from modules/ if available:
      1. modules.contact_search       → search + enrich contacts
      2. modules.candidate_profile_extractor → parse resume into structured profile
      3. modules.email_generator      → generate personalized emails
    """
    print(f"[Agent] Query: {user_query}")

    print("[Agent] Step 1: Searching and enriching contacts...")
    contacts = await search_contacts(user_query)
    if not contacts:
        print("[Agent] No contacts found")
        return []

    print("[Agent] Step 2: Extracting candidate profile...")
    candidate = extract_candidate_profile(user_profile)

    print(f"[Agent] Step 3: Generating emails for {len(contacts)} contacts...")
    results = []
    for i, contact in enumerate(contacts):
        name = contact.get("name", f"Contact {i+1}")
        print(f"[Agent]   {i+1}/{len(contacts)} → {name} at {contact.get('company', '')}")
        email = await generate_email(candidate, contact)
        results.append({
            "contact": contact,
            "company": contact.get("company", ""),
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
            "status": "pending",
        })

    print(f"[Agent] Done — {len(results)} emails generated")
    return results

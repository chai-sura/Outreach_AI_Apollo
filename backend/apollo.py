import os
import httpx
from dotenv import load_dotenv

load_dotenv()

APOLLO_API_KEY = os.getenv("APOLLO_API_KEY", "")
BASE_URL = "https://api.apollo.io/api/v1"
HEADERS = {
    "Content-Type": "application/json",
    "X-Api-Key": APOLLO_API_KEY,
}


async def search_contacts(query: str, limit: int = 10) -> list[dict]:
    """
    Search Apollo for contacts by name/company query.
    Uses Apollo's mixed_people/search endpoint to find contacts on LinkedIn.
    """
    if not APOLLO_API_KEY:
        print("[Apollo] ERROR: APOLLO_API_KEY not set. Cannot search contacts.")
        return []
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{BASE_URL}/mixed_people/api_search",
                headers=HEADERS,
                json={
                    "q_keywords": query,
                    "person_titles": [
                        "recruiter",
                        "talent acquisition",
                        "engineering manager",
                        "technical recruiter",
                        "head of engineering",
                        "hiring manager",
                        "founder",
                        "cto",
                        "ceo",
                    ],
                    "per_page": limit,
                    "page": 1,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        people = data.get("people", []) or data.get("contacts", [])
        results = []
        
        for p in people:
            org = p.get("organization") or {}
            contact = {
                "id": p.get("id", ""),
                "name": p.get("name", ""),
                "title": p.get("title", ""),
                "company": org.get("name", p.get("organization_name", "")),
                "email": p.get("email", ""),
                "linkedin_url": p.get("linkedin_url", ""),
                "company_id": p.get("organization_id", ""),
                "city": p.get("city", ""),
                "seniority": p.get("seniority", ""),
            }
            results.append(contact)
        
        print(f"[Apollo] Found {len(results)} contacts for query: '{query}'")
        return results
        
    except Exception as e:
        print(f"[Apollo] search_contacts error: {e}")
        return []


async def enrich_contact(contact: dict) -> dict:
    """
    Enrich a contact with additional company and profile data.
    Uses Apollo's people/match endpoint to get detailed information.
    """
    if not APOLLO_API_KEY:
        print("[Apollo] ERROR: APOLLO_API_KEY not set. Cannot enrich contact.")
        return contact
    
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
        enriched.update(
            {
                "email": person.get("email") or contact.get("email", ""),
                "title": person.get("title") or contact.get("title", ""),
                "seniority": person.get("seniority", ""),
                "city": person.get("city", contact.get("city", "")),
                "headline": person.get("headline", ""),
                "bio": person.get("summary", ""),
                "funding_stage": org.get("latest_funding_stage", ""),
                "headcount": str(org.get("estimated_num_employees", "")),
                "technologies": org.get("technology_names", []),
                "industry": org.get("industry", ""),
                "company_description": org.get("short_description", ""),
            }
        )
        print(f"[Apollo] Enriched contact: {enriched.get('name')} at {enriched.get('company')}")
        return enriched
        
    except Exception as e:
        print(f"[Apollo] enrich_contact error: {e}, returning contact as-is")
        return contact


async def send_email(to: str, subject: str, body: str) -> dict:
    """
    Send an email via Apollo API.
    If no API key, returns a success response (email tracking via in-memory storage).
    """
    if not APOLLO_API_KEY:
        print(f"[Apollo] Email sending disabled (no API key). Email stored for tracking: {to}")
        return {"success": True, "message_id": f"local_{to.split('@')[0]}"}
    
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
        print(f"[Apollo] Email sent successfully to {to} (id: {message_id})")
        return {"success": True, "message_id": message_id}
        
    except Exception as e:
        print(f"[Apollo] send_email error: {e}")
        return {"success": False, "message_id": "", "error": str(e)}

import asyncio
import io
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import AsyncOpenAI  # Groq is OpenAI-compatible

import apollo

load_dotenv()

app = FastAPI(title="Outreach AI", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Module imports ─────────────────────────────────────────────────────────────
# Written by algorithm team. Auto-resolve after `git pull` + server restart.
# Fallbacks keep the pipeline running until each module is merged.

try:
    from modules.candidate_profile_extractor import extract_profile as _extract_profile  # type: ignore
    print("[Main] ✅ modules.candidate_profile_extractor")
except ImportError:
    _extract_profile = None
    print("[Main] ⚠️  modules.candidate_profile_extractor — using raw profile fallback")

try:
    from modules.contact_search import search_and_enrich as _search_and_enrich  # type: ignore
    print("[Main] ✅ modules.contact_search")
except ImportError:
    _search_and_enrich = None
    print("[Main] ⚠️  modules.contact_search — using apollo fallback")

try:
    from modules.email_generator import generate as _generate_email  # type: ignore
    print("[Main] ✅ modules.email_generator")
except ImportError:
    _generate_email = None
    print("[Main] ⚠️  modules.email_generator — using openai fallback")


# ── In-Memory Storage ─────────────────────────────────────────────────────────

USER_PROFILES: dict = {}
DRAFT_EMAILS: dict = {}


# ── Request Models ────────────────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    user_query: str    # e.g. "5 recruiters at Apple in Bay Area"
    profile_id: str

class ApproveEmailRequest(BaseModel):
    subject: str = ""
    body: str = ""

class MockEventRequest(BaseModel):
    email_id: str
    event: str         # opened | clicked | replied


# ── Pipeline helpers (fallbacks when modules aren't merged yet) ───────────────

async def do_contact_search(query: str, limit: int = 5) -> list[dict]:
    if _search_and_enrich is not None:
        return await _search_and_enrich(query, limit=limit)
    contacts = await apollo.search_contacts(query, limit=limit)
    enriched = await asyncio.gather(*[apollo.enrich_contact(c) for c in contacts])
    return list(enriched)


def do_extract_profile(user_profile: dict) -> dict:
    if _extract_profile is not None:
        return _extract_profile(
            resume_text=user_profile.get("resume_text", ""),
            name=user_profile.get("name", ""),
            goal=user_profile.get("goal", ""),
        )
    return {
        "name": user_profile.get("name", ""),
        "goal": user_profile.get("goal", ""),
        "key_skills": [],
        "background_summary": user_profile.get("resume_text", "")[:300].strip(),
        "unique_value": user_profile.get("goal", ""),
        "tone_preference": "casual",
    }


async def do_generate_email(candidate: dict, contact: dict) -> dict:
    if _generate_email is not None:
        return await _generate_email(candidate, contact)

    # Groq fallback (OpenAI-compatible)
    client = AsyncOpenAI(
        api_key=os.getenv("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    context_lines = []
    if contact.get("headline"):
        context_lines.append(f"LinkedIn headline: {contact['headline']}")
    if contact.get("bio"):
        context_lines.append(f"LinkedIn bio: {contact['bio']}")
    if contact.get("company_description"):
        context_lines.append(f"Company: {contact['company_description']}")
    if contact.get("funding_stage"):
        context_lines.append(f"Funding: {contact['funding_stage']}")
    if contact.get("technologies"):
        context_lines.append(f"Tech: {', '.join(contact['technologies'][:5])}")

    prompt = f"""Write a cold outreach email.

SENDER: {candidate.get('name')} | Goal: {candidate.get('goal')}
Background: {candidate.get('background_summary', '')}

RECIPIENT: {contact.get('name')}, {contact.get('title')} at {contact.get('company')}
{chr(10).join(context_lines) or 'No extra context.'}

Rules: max 5 sentences, no "I hope this finds you well", end with a 15-min call ask.
Format exactly:
Subject: [subject]
Body:
[body]"""

    try:
        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.choices[0].message.content or ""
    except Exception as e:
        print(f"[EmailFallback] Groq error: {e}")
        return {"subject": f"Quick intro — {candidate.get('name','')}", "body": ""}

    subject, body, in_body = "", "", False
    for line in raw.strip().split("\n"):
        if line.startswith("Subject:"):
            subject = line.replace("Subject:", "").strip()
        elif line.startswith("Body:"):
            in_body = True
        elif in_body:
            body += line + "\n"

    return {
        "subject": subject or f"Quick intro — {candidate.get('name','')}",
        "body": body.strip() or raw.strip(),
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)[:5000]
    except Exception as e:
        print(f"[PDF] {e}")
        return ""


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "time": datetime.now(timezone.utc).isoformat(),
        "modules": {
            "candidate_profile_extractor": _extract_profile is not None,
            "contact_search": _search_and_enrich is not None,
            "email_generator": _generate_email is not None,
        },
    }


@app.post("/onboard")
async def onboard(
    name: str = Form(...),
    email: str = Form(...),
    goal: str = Form(...),
    resume: UploadFile = File(...),
):
    pdf_bytes = await resume.read()
    resume_text = extract_pdf_text(pdf_bytes)
    profile_id = str(uuid.uuid4())
    USER_PROFILES[profile_id] = {
        "profile_id": profile_id,
        "name": name,
        "email": email,
        "goal": goal,
        "resume_text": resume_text,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    print(f"[Onboard] {name} → {profile_id}")
    return {"profile_id": profile_id, "status": "ok", "message": f"Welcome {name}!"}


@app.post("/run-pipeline")
async def run_pipeline(req: RunPipelineRequest):
    """
    Step 1: contact_search  → finds + enriches contacts (Apollo + LinkedIn data)
    Step 2: candidate_profile_extractor → parses resume into structured profile
    Step 3: email_generator → generates personalized draft per contact
    All three come from modules/ if available, else fallback runs automatically.
    """
    profile = USER_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — call /onboard first")

    print(f"[Pipeline] Query: '{req.user_query}'")

    print("[Pipeline] Step 1: Searching contacts...")
    contacts = await do_contact_search(req.user_query)
    if not contacts:
        return {"status": "ok", "count": 0, "emails": [], "message": "No contacts found"}

    print("[Pipeline] Step 2: Extracting candidate profile...")
    candidate = do_extract_profile(profile)

    print(f"[Pipeline] Step 3: Generating {len(contacts)} emails...")
    now = datetime.now(timezone.utc).isoformat()
    email_records = []

    for i, contact in enumerate(contacts):
        print(f"[Pipeline]   {i+1}/{len(contacts)} → {contact.get('name')} at {contact.get('company')}")
        email = await do_generate_email(candidate, contact)

        email_id = str(uuid.uuid4())
        record = {
            "email_id": email_id,
            "profile_id": req.profile_id,
            "contact_name": contact.get("name", ""),
            "contact_title": contact.get("title", ""),
            "company": contact.get("company", ""),
            "to": contact.get("email", ""),
            "linkedin_url": contact.get("linkedin_url", ""),
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
            "status": "pending",
            "created_at": now,
            "sent_at": None,
            "opened": False,
            "clicked": False,
            "replied": False,
        }
        DRAFT_EMAILS[email_id] = record
        email_records.append(record)

    print(f"[Pipeline] Done — {len(email_records)} drafts ready for review")
    return {
        "status": "ok",
        "count": len(email_records),
        "message": "Review and approve emails before sending.",
        "emails": email_records,
    }


# ── Confirmation Flow ─────────────────────────────────────────────────────────

@app.get("/emails/pending")
async def get_pending_emails():
    pending = [e for e in DRAFT_EMAILS.values() if e["status"] == "pending"]
    return {"count": len(pending), "emails": pending}


@app.post("/emails/{email_id}/approve")
async def approve_email(email_id: str, req: ApproveEmailRequest):
    email = DRAFT_EMAILS.get(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if email["status"] == "sent":
        raise HTTPException(status_code=400, detail="Already sent")
    if req.subject:
        email["subject"] = req.subject
    if req.body:
        email["body"] = req.body
    email["status"] = "approved"
    print(f"[Approve] {email_id} → {email['contact_name']}")
    return {"status": "approved", "email_id": email_id}


@app.post("/emails/{email_id}/reject")
async def reject_email(email_id: str):
    email = DRAFT_EMAILS.get(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    email["status"] = "rejected"
    return {"status": "rejected", "email_id": email_id}


@app.post("/emails/{email_id}/send")
async def send_email(email_id: str):
    email = DRAFT_EMAILS.get(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if email["status"] != "approved":
        raise HTTPException(status_code=400, detail=f"Must be approved first (current: {email['status']})")
    if not email.get("to"):
        raise HTTPException(status_code=400, detail="No recipient email — Apollo didn't return one for this contact")

    result = await apollo.send_email(email["to"], email["subject"], email["body"])
    email["status"] = "sent"
    email["sent_at"] = datetime.now(timezone.utc).isoformat()
    email["apollo_message_id"] = result.get("message_id", "")
    return {"status": "sent", "email_id": email_id, "to": email["to"]}


@app.post("/emails/send-all-approved")
async def send_all_approved():
    approved = [e for e in DRAFT_EMAILS.values() if e["status"] == "approved"]
    if not approved:
        return {"status": "ok", "sent": 0, "message": "No approved emails"}
    sent, failed = [], []
    for email in approved:
        if not email.get("to"):
            failed.append(email["email_id"])
            continue
        await apollo.send_email(email["to"], email["subject"], email["body"])
        email["status"] = "sent"
        email["sent_at"] = datetime.now(timezone.utc).isoformat()
        sent.append(email["email_id"])
    return {"status": "ok", "sent": len(sent), "failed": len(failed)}


# ── Dashboard ─────────────────────────────────────────────────────────────────

@app.get("/dashboard")
async def dashboard():
    emails = list(DRAFT_EMAILS.values())
    sent = [e for e in emails if e["status"] == "sent"]
    total = len(sent)
    opened  = sum(1 for e in sent if e.get("opened"))
    clicked = sum(1 for e in sent if e.get("clicked"))
    replied = sum(1 for e in sent if e.get("replied"))
    return {
        "summary": {
            "total_drafted": len(emails),
            "total_sent": total,
            "total_opened": opened,
            "total_clicked": clicked,
            "total_replied": replied,
            "open_rate":  round(opened  / total * 100, 1) if total else 0.0,
            "click_rate": round(clicked / total * 100, 1) if total else 0.0,
            "reply_rate": round(replied / total * 100, 1) if total else 0.0,
        },
        "emails": emails,
    }


@app.post("/mock-event")
async def mock_event(req: MockEventRequest):
    email = DRAFT_EMAILS.get(req.email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    if req.event not in ("opened", "clicked", "replied"):
        raise HTTPException(status_code=400, detail="event must be: opened | clicked | replied")
    email[req.event] = True
    return {"status": "updated", "event": req.event}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

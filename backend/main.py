import asyncio
import io
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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

# ── In-Memory Storage ─────────────────────────────────────────────────────────

USER_PROFILES: dict = {}
DRAFT_EMAILS: dict = {}


# ── Request Models ────────────────────────────────────────────────────────────

class RunPipelineRequest(BaseModel):
    user_query: str
    profile_id: str

class GenerateFromContactsRequest(BaseModel):
    profile_id: str
    contacts: list[dict]  # raw output from JS contact_discovery / contact_discovery_linkedin modules

class ApproveEmailRequest(BaseModel):
    subject: str = ""
    body: str = ""

class MockEventRequest(BaseModel):
    email_id: str
    event: str  # opened | clicked | replied


# ── Helpers ───────────────────────────────────────────────────────────────────

def extract_pdf_text(pdf_bytes: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(pdf_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)[:5000]
    except Exception as e:
        print(f"[PDF] {e}")
        return ""


def build_candidate(user_profile: dict) -> dict:
    return {
        "name": user_profile.get("name", ""),
        "goal": user_profile.get("goal", ""),
        "key_skills": [],
        "background_summary": user_profile.get("resume_text", "")[:300].strip(),
    }


def normalize_contact(c: dict) -> dict:
    """Normalize raw JS module contact fields to backend format."""
    return {
        "id": c.get("id", ""),
        "name": c.get("full_name") or c.get("name", ""),
        "title": c.get("title", ""),
        "company": c.get("organization_name") or c.get("company", ""),
        "email": c.get("email", ""),
        "linkedin_url": c.get("linkedin_url", ""),
        "city": c.get("city", ""),
        "seniority": c.get("seniority", ""),
    }


def make_email_record(email_id: str, profile_id: str, contact: dict, email: dict) -> dict:
    return {
        "email_id": email_id,
        "profile_id": profile_id,
        "contact_name": contact.get("name", ""),
        "contact_title": contact.get("title", ""),
        "company": contact.get("company", ""),
        "to": contact.get("email", ""),
        "linkedin_url": contact.get("linkedin_url", ""),
        "subject": email.get("subject", ""),
        "body": email.get("body", ""),
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "sent_at": None,
        "opened": False,
        "clicked": False,
        "replied": False,
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


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
    Accepts a natural-language query and profile_id.
    Contact discovery is done via the JS modules (contact_discovery / contact_discovery_linkedin).
    Use /generate-from-contacts to pass their output directly into the email pipeline.
    """
    profile = USER_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — call /onboard first")

    return {
        "status": "ok",
        "count": 0,
        "emails": [],
        "message": (
            "Contact discovery runs via the JS modules. "
            "Run: node --env-file=.env tests/contact_discovery_linkedin.mjs "
            "then POST the contacts to /generate-from-contacts."
        ),
    }


@app.post("/generate-from-contacts")
async def generate_from_contacts(req: GenerateFromContactsRequest):
    """
    Accepts contacts from JS contact_discovery or contact_discovery_linkedin module output.
    Enriches each contact via Apollo (LinkedIn headline, bio, company info),
    then generates a personalized email using AI (starts with Hello, ends with Thanks).
    """
    profile = USER_PROFILES.get(req.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found — call /onboard first")
    if not req.contacts:
        raise HTTPException(status_code=400, detail="contacts list is empty")

    print(f"[GenerateFromContacts] {len(req.contacts)} contacts received")

    normalized = [normalize_contact(c) for c in req.contacts]

    print("[GenerateFromContacts] Enriching via Apollo...")
    enriched = await asyncio.gather(*[apollo.enrich_contact(c) for c in normalized])

    candidate = build_candidate(profile)
    email_records = []

    print(f"[GenerateFromContacts] Generating {len(enriched)} personalized emails...")
    for i, contact in enumerate(enriched):
        print(f"[GenerateFromContacts]   {i+1}/{len(enriched)} → {contact.get('name')} at {contact.get('company')}")
        email = await apollo.generate_personalized_email(candidate, contact)
        email_id = str(uuid.uuid4())
        record = make_email_record(email_id, req.profile_id, contact, email)
        DRAFT_EMAILS[email_id] = record
        email_records.append(record)

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

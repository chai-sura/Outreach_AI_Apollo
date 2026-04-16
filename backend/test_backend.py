"""
Pipeline test: JS LinkedIn contacts → Apollo enrich → Groq email gen → approve → send
Run: apollo_env/bin/python3 test_backend.py
Requires: uvicorn main:app --port 8000
"""

import asyncio
import io
import json
import subprocess
import os
import httpx

BASE = "http://localhost:8000"

MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
    b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
    b"4 0 obj<</Length 100>>stream\nBT /F1 12 Tf 72 720 Td "
    b"(Jane Doe Software Engineer React Node.js Python) Tj ET\nendstream\nendobj\n"
    b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
    b"xref\n0 6\n0000000000 65535 f \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n500\n%%EOF"
)


def get_linkedin_contacts(per_page=3):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mod_path = f"file://{root}/modules/contact_discovery_linkedin.js"
    script = (
        f"import('{mod_path}')"
        ".then(m => m.runContactDiscoveryLinkedin({"
        "intent_text:'machine learning engineer at NVIDIA recruiters',"
        f"page:1,per_page:{per_page}" + "}))"
        ".then(r => process.stdout.write(JSON.stringify(r.prospects_with_linkedin || r.contacts || [])))"
        ".catch(e => { process.stderr.write(e.message); process.exit(1); })"
    )
    result = subprocess.run(
        ["node", f"--env-file={root}/.env", "--input-type=module"],
        input=script, capture_output=True, text=True, timeout=30, cwd=root,
    )
    if result.returncode != 0:
        print(f"[JS Error] {result.stderr.strip()[:300]}")
        return []
    return json.loads(result.stdout)


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as c:

        # Onboard candidate
        r = await c.post("/onboard",
            files={"resume": ("resume.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            data={"name": "Jane Doe", "email": "jane@example.com",
                  "goal": "Get a machine learning engineering role at NVIDIA"})
        profile_id = r.json()["profile_id"]

        # Get real contacts from JS linkedin module
        print("Fetching contacts from JS linkedin module...")
        contacts = get_linkedin_contacts(per_page=3)
        if not contacts:
            print("No contacts returned from JS module. Exiting.")
            return

        # Generate personalized emails via backend (Apollo enrich + Groq)
        r = await c.post("/generate-from-contacts", json={"profile_id": profile_id, "contacts": contacts})
        emails = r.json().get("emails", [])

        print(f"\n{'═'*60}")
        print(f"  {len(emails)} Personalized Email(s) — Review Before Sending")
        print(f"{'═'*60}")
        for i, e in enumerate(emails):
            print(f"\n  ── Email {i+1} ───────────────────────────────────────")
            print(f"  To:      {e.get('contact_name')} @ {e.get('company')}")
            print(f"  Email:   {e.get('to') or '(not revealed on Apollo free plan)'}")
            print(f"  Subject: {e.get('subject')}")
            print(f"  Body:\n")
            for line in (e.get('body') or '').splitlines():
                print(f"    {line}")
            print(f"\n  Status:  {e.get('status')}")

        print(f"\n{'═'*60}")
        answer = input("  Approve and send all? (yes / no): ").strip().lower()

        if answer != "yes":
            print("  Emails kept as pending. Run again to send.")
            return

        sent, failed = 0, 0
        for e in emails:
            email_id = e["email_id"]
            await c.post(f"/emails/{email_id}/approve", json={})
            r = await c.post(f"/emails/{email_id}/send")
            if r.status_code == 200:
                sent += 1
                print(f"  ✅ Sent to {e.get('to')}")
            else:
                failed += 1
                print(f"  ❌ Failed: {r.json().get('detail', '')}")

        print(f"\n  Done — {sent} sent, {failed} failed\n")


asyncio.run(run())

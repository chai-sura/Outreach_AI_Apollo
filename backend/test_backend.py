"""
Pipeline test: JS contact discovery → Apollo enrich → AI personalized email → approve → send
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
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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


def run_js_module(module_file: str, return_field: str, intent: str, per_page: int = 3) -> list:
    """Call a JS contact discovery module and return its contacts as a list."""
    mod_path = f"file://{ROOT}/modules/{module_file}"
    fn_name = "runContactDiscovery" if "linkedin" not in module_file else "runContactDiscoveryLinkedin"
    script = (
        f"import('{mod_path}')"
        f".then(m => m.{fn_name}({{"
        f"intent_text:'{intent}',page:1,per_page:{per_page}"
        f"}})).then(r => process.stdout.write(JSON.stringify(r.{return_field} || [])))"
        ".catch(e => { process.stderr.write(e.message); process.exit(1); })"
    )
    result = subprocess.run(
        ["node", f"--env-file={ROOT}/.env", "--input-type=module"],
        input=script, capture_output=True, text=True, timeout=30, cwd=ROOT,
    )
    if result.returncode != 0:
        print(f"  [JS {module_file}] Error: {result.stderr.strip()[:200]}")
        return []
    return json.loads(result.stdout or "[]")


def get_all_contacts(intent: str, per_page: int = 3) -> list:
    """
    Pulls contacts from both JS discovery modules and merges them,
    deduplicating by linkedin_url. LinkedIn module results take priority
    (they include has_email=True contacts with profile URLs).
    """
    print("  → contact_discovery_linkedin.js ...")
    linkedin_contacts = run_js_module(
        "contact_discovery_linkedin.js", "prospects_with_linkedin", intent, per_page
    )
    print(f"    {len(linkedin_contacts)} contacts")

    print("  → contact_discovery.js ...")
    discovery_contacts = run_js_module(
        "contact_discovery.js", "contacts", intent, per_page
    )
    print(f"    {len(discovery_contacts)} contacts")

    # Merge: linkedin contacts first, add discovery contacts not already present
    seen_urls = {c.get("linkedin_url", "") for c in linkedin_contacts if c.get("linkedin_url")}
    merged = list(linkedin_contacts)
    for c in discovery_contacts:
        url = c.get("linkedin_url", "")
        if url and url not in seen_urls:
            merged.append(c)
            seen_urls.add(url)
        elif not url:
            merged.append(c)

    return merged[:per_page]


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as c:

        # Onboard candidate
        r = await c.post("/onboard",
            files={"resume": ("resume.pdf", io.BytesIO(MINIMAL_PDF), "application/pdf")},
            data={"name": "Jane Doe", "email": "jane@example.com",
                  "goal": "Get a machine learning engineering role at NVIDIA"})
        profile_id = r.json()["profile_id"]

        # Pull contacts from both JS modules
        intent = "machine learning engineer at NVIDIA recruiters"
        print(f"\nFetching contacts from JS modules (intent: '{intent}')...")
        contacts = get_all_contacts(intent, per_page=3)

        if not contacts:
            print("No contacts returned. Exiting.")
            return

        # Generate personalized emails via backend (Apollo enrich + AI)
        r = await c.post("/generate-from-contacts", json={"profile_id": profile_id, "contacts": contacts})
        if r.status_code != 200:
            print(f"generate-from-contacts failed: {r.status_code} {r.text}")
            return
        emails = r.json().get("emails", [])

        # Display personalized emails for review
        print(f"\n{'═'*62}")
        print(f"  {len(emails)} AI-Personalized Email(s) — Review Before Sending")
        print(f"{'═'*62}")
        for i, e in enumerate(emails):
            print(f"\n  ── Email {i+1} {'─'*45}")
            print(f"  To:      {e.get('contact_name')} @ {e.get('company')}")
            print(f"  Email:   {e.get('to') or '(not revealed — Apollo free plan)'}")
            print(f"  Subject: {e.get('subject')}")
            print(f"\n  Body:")
            for line in (e.get('body') or '').splitlines():
                print(f"    {line}")
            print(f"\n  Status:  {e.get('status')}")

        print(f"\n{'═'*62}")
        answer = input("  Approve and send all? (yes / no): ").strip().lower()

        if answer != "yes":
            print("  Emails kept as pending. Approve individually at /emails/pending.")
            return

        sent, failed = 0, 0
        for e in emails:
            eid = e["email_id"]
            await c.post(f"/emails/{eid}/approve", json={})
            sr = await c.post(f"/emails/{eid}/send")
            if sr.status_code == 200:
                sent += 1
                print(f"  ✅ Sent → {e.get('to')}")
            else:
                failed += 1
                print(f"  ❌ Failed → {sr.json().get('detail', '')}")

        print(f"\n  Done — {sent} sent, {failed} failed\n")


asyncio.run(run())

"""
Backend integration tests — runs against localhost:8000
Start the server first: uvicorn main:app --port 8000

Run: apollo_env/bin/python3 test_backend.py
"""

import asyncio
import io
import httpx

BASE = "http://localhost:8000"
PASS = "✅"
FAIL = "❌"
results = []


def log(name, passed, detail=""):
    status = PASS if passed else FAIL
    print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))
    results.append(passed)


async def run():
    async with httpx.AsyncClient(base_url=BASE, timeout=60.0) as c:

        print("\n── 1. Health ─────────────────────────────────")
        r = await c.get("/health")
        log("GET /health → 200", r.status_code == 200)
        data = r.json()
        log("status = ok", data.get("status") == "ok")
        log("modules key present", "modules" in data)
        print("     modules:", data.get("modules"))

        print("\n── 2. Onboard ────────────────────────────────")
        # Build a minimal PDF-like bytes (pypdf handles it gracefully)
        minimal_pdf = (
            b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R"
            b"/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
            b"4 0 obj<</Length 100>>stream\nBT /F1 12 Tf 72 720 Td "
            b"(Jane Doe Software Engineer React Node.js Python) Tj ET\nendstream\nendobj\n"
            b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
            b"xref\n0 6\n0000000000 65535 f \ntrailer<</Size 6/Root 1 0 R>>\nstartxref\n500\n%%EOF"
        )
        r = await c.post(
            "/onboard",
            files={"resume": ("resume.pdf", io.BytesIO(minimal_pdf), "application/pdf")},
            data={"name": "Jane Doe", "email": "jane@example.com",
                  "goal": "Get a backend engineering role at a top tech company"},
        )
        log("POST /onboard → 200", r.status_code == 200)
        onboard = r.json()
        profile_id = onboard.get("profile_id", "")
        log("profile_id returned", bool(profile_id), profile_id[:8] + "...")
        log("status = ok", onboard.get("status") == "ok")

        print("\n── 3. Run Pipeline ───────────────────────────")
        r = await c.post("/run-pipeline", json={
            "user_query": "engineering manager at Stripe",
            "profile_id": profile_id,
        })
        log("POST /run-pipeline → 200", r.status_code == 200)
        pipeline = r.json()
        count = pipeline.get("count", 0)
        log("contacts found > 0", count > 0, f"{count} contacts")
        emails = pipeline.get("emails", [])
        log("emails list returned", isinstance(emails, list))
        if emails:
            e = emails[0]
            log("email has subject", bool(e.get("subject")), repr(e.get("subject", ""))[:50])
            log("email has body",    bool(e.get("body")),    repr(e.get("body", ""))[:60])
            log("status = pending",  e.get("status") == "pending")
            email_id = e["email_id"]
        else:
            email_id = None
            log("got email_id", False, "no emails returned")

        print("\n── 4. Profile not found guard ────────────────")
        r = await c.post("/run-pipeline", json={
            "user_query": "test", "profile_id": "bad-id"
        })
        log("POST /run-pipeline bad profile_id → 404", r.status_code == 404)

        print("\n── 5. Pending emails ─────────────────────────")
        r = await c.get("/emails/pending")
        log("GET /emails/pending → 200", r.status_code == 200)
        pending = r.json()
        log("count >= emails from this run", pending.get("count", 0) >= count, str(pending.get("count")))

        if email_id:
            print("\n── 6. Approve email ──────────────────────────")
            r = await c.post(f"/emails/{email_id}/approve", json={})
            log(f"POST /emails/{email_id[:8]}.../approve → 200", r.status_code == 200)
            log("status = approved", r.json().get("status") == "approved")

            # Approve with edit
            r2 = await c.post(f"/emails/{email_id}/approve",
                               json={"subject": "Edited subject", "body": "Edited body"})
            log("approve with subject/body edit → 200", r2.status_code == 200)

            print("\n── 7. Reject another email ───────────────────")
            if len(emails) > 1:
                other_id = emails[1]["email_id"]
                r = await c.post(f"/emails/{other_id}/reject")
                log(f"POST /emails/{other_id[:8]}.../reject → 200", r.status_code == 200)
                log("status = rejected", r.json().get("status") == "rejected")
            else:
                log("reject (skipped — only 1 email)", True, "skip")

            print("\n── 8. Send approved ──────────────────────────")
            r = await c.post(f"/emails/{email_id}/send")
            # Apollo send endpoint doesn't really exist so it'll either send or 400 (no recipient email)
            log("POST /emails/{id}/send → 200 or 400",
                r.status_code in (200, 400),
                f"status={r.status_code} {r.json().get('detail','') or r.json().get('status','')}")

            print("\n── 9. Send unapproved → must fail ───────────")
            if len(emails) > 2:
                pending_id = emails[2]["email_id"]
                r = await c.post(f"/emails/{pending_id}/send")
                log("send pending email → 400", r.status_code == 400, "correctly blocked")
            else:
                log("send unapproved guard (skipped)", True, "skip")

        print("\n── 10. Send all approved ─────────────────────")
        r = await c.post("/emails/send-all-approved")
        log("POST /emails/send-all-approved → 200", r.status_code == 200)

        print("\n── 11. Dashboard ─────────────────────────────")
        r = await c.get("/dashboard")
        log("GET /dashboard → 200", r.status_code == 200)
        dash = r.json()
        log("summary key present", "summary" in dash)
        log("emails key present",  "emails" in dash)
        s = dash.get("summary", {})
        log("open_rate is float",  isinstance(s.get("open_rate"), (int, float)))
        log("total_drafted > 0",   s.get("total_drafted", 0) > 0, str(s.get("total_drafted")))

        print("\n── 12. Mock event ────────────────────────────")
        if email_id:
            r = await c.post("/mock-event",
                              json={"email_id": email_id, "event": "opened"})
            log("POST /mock-event opened → 200", r.status_code == 200)
            r = await c.post("/mock-event",
                              json={"email_id": email_id, "event": "clicked"})
            log("POST /mock-event clicked → 200", r.status_code == 200)
            r = await c.post("/mock-event",
                              json={"email_id": "bad-id", "event": "opened"})
            log("mock-event bad id → 404", r.status_code == 404)
            r = await c.post("/mock-event",
                              json={"email_id": email_id, "event": "invalid"})
            log("mock-event bad event → 400", r.status_code == 400)

        print("\n── Summary ───────────────────────────────────")
        passed = sum(results)
        total  = len(results)
        print(f"  {passed}/{total} passed  {'🟢 ALL GOOD' if passed == total else '🔴 SOME FAILED'}\n")


asyncio.run(run())

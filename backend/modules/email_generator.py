"""
Email Generator
---------------
INPUT : candidate (CandidateProfile dict)
        contact   (enriched contact dict)
OUTPUT: { "subject": str, "body": str }

Email rules:
- Max 5 sentences
- First sentence: hook from company/person context
- No: "I hope this finds you well", "I came across your profile"
- Ends with a soft 15-min call ask
- Tone matches candidate.tone_preference

NOTE: Backend calls generate(). Replace stub with real LLM implementation.
Stub returns a placeholder so the pipeline doesn't break while this is built.
"""


async def generate(candidate: dict, contact: dict) -> dict:
    """Stub — returns placeholder email. Replace with real generation logic."""
    name = candidate.get("name", "")
    contact_name = contact.get("name", "there")
    company = contact.get("company", "your company")
    goal = candidate.get("goal", "connect")

    subject = f"Quick intro — {name}"
    body = (
        f"Hi {contact_name}, I came across {company} and was impressed by what you're building. "
        f"My background in {', '.join(candidate.get('key_skills', ['technology'])[:2])} aligns well with your work. "
        f"I'd love to {goal.lower()} — would a 15-min call this week work for you?"
    )

    return {"subject": subject, "body": body}

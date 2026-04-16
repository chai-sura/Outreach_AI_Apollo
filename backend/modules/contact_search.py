"""
Contact Search
--------------
INPUT : query (str)  — natural language e.g. "recruiters at Apple in Bay Area"
        limit (int)  — max contacts to return
OUTPUT: list[dict]   — list of enriched contact dicts

Contact dict shape (from Apollo enrichment):
{
    "id": str,
    "name": str,
    "title": str,
    "company": str,
    "email": str,
    "linkedin_url": str,
    "headline": str,       # LinkedIn headline
    "bio": str,            # LinkedIn summary / about
    "city": str,
    "seniority": str,
    "industry": str,
    "funding_stage": str,
    "headcount": str,
    "technologies": list[str],
    "company_description": str,
}

NOTE: Backend calls search_and_enrich(). Replace stub with real implementation.
Stub delegates directly to apollo module so the pipeline works out of the box.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import apollo


async def search_and_enrich(query: str, limit: int = 5) -> list[dict]:
    """Stub — delegates to Apollo. Replace with enriched search logic."""
    contacts = await apollo.search_contacts(query, limit=limit)
    enriched = await asyncio.gather(*[apollo.enrich_contact(c) for c in contacts])
    return list(enriched)

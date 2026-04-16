/**
 * Module: contact_discovery
 * Uses an LLM + Apollo People Search to find contacts (e.g. recruiters)
 * based on a natural-language intent like:
 * "I want to work as a machine learning engineer at Nvidia and reach out to recruiters".
 *
 * Env vars:
 * - API_KEY_CONTACT_DISCOVERY (required): Apollo API key for this module
 * - LLM_PROVIDER (optional): 'ollama' (default) or 'openai'
 * - OLLAMA_BASE_URL (optional): defaults to http://localhost:11434
 * - OLLAMA_MODEL (optional): defaults to 'llama3.1:8b'
 * - OPENAI_API_KEY / API_KEY_PROFILE_EXTRACTOR (optional fallback for provider=openai)
 */

import { llmGenerateJson } from './llm_client.js';

const APOLLO_BASE_URL = 'https://api.apollo.io';

function getEnv(name) {
  return typeof process !== 'undefined' ? process.env?.[name] : undefined;
}

async function buildApolloSearchSpecFromIntent(intentText) {
  const prompt = `
You are an expert at mapping job-search and outreach intents to Apollo People Search filters.

User goal:
"""
${intentText}
"""

Infer the best filters to find relevant HUMAN CONTACTS to reach this goal, prioritizing recruiters / talent acquisition / HR when appropriate.

Return ONLY valid JSON (no markdown, no explanations) with this exact shape:
{
  "company_names": ["<string>"],
  "titles": ["<string>"],
  "departments": ["<string>"],
  "seniorities": ["<string>"],
  "locations": ["<string>"],
  "keywords": ["<string>"]
}

Rules:
- Only include company_names if the user clearly mentions or strongly implies target companies.
- Titles should reflect who to CONTACT (e.g. "Recruiter", "Technical Recruiter", "Talent Acquisition", "Hiring Manager") — not the candidate's desired title.
- Departments might include "Human Resources", "Recruiting", "Talent Acquisition", or relevant engineering leadership (for hiring managers).
- Seniorities should be things like "director", "vp", "manager", "head", "lead", when appropriate.
- locations can be city, region, or "remote" if user explicitly prefers remote.
`;

  const raw = await llmGenerateJson({ prompt });

  let spec;
  try {
    const cleaned =
      typeof raw === 'string'
        ? raw.replace(/```json|```/g, '').trim()
        : JSON.stringify(raw);
    spec = JSON.parse(cleaned);
  } catch {
    throw new Error('contact_discovery: LLM returned malformed JSON search spec');
  }

  // Basic normalization / defaults
  const normalizeArray = v => (Array.isArray(v) ? v : v ? [String(v)] : []);

  return {
    company_names: normalizeArray(spec.company_names),
    titles: normalizeArray(spec.titles),
    departments: normalizeArray(spec.departments),
    seniorities: normalizeArray(spec.seniorities),
    locations: normalizeArray(spec.locations),
    keywords: normalizeArray(spec.keywords),
  };
}

async function callApolloPeopleSearch({ spec, page = 1, per_page = 25 }) {
  const apiKey = getEnv('API_KEY_CONTACT_DISCOVERY');
  if (!apiKey) {
    throw new Error(
      'Missing Apollo API key. Set API_KEY_CONTACT_DISCOVERY in your environment.'
    );
  }

  const endpoint = new URL(`${APOLLO_BASE_URL}/api/v1/mixed_people/api_search`);
  endpoint.searchParams.set('page', String(page));
  endpoint.searchParams.set('per_page', String(per_page));

  const keywords = spec.keywords.join(' ').trim();
  if (keywords) endpoint.searchParams.set('q_keywords', keywords);

  for (const title of spec.titles) {
    endpoint.searchParams.append('person_titles[]', title);
  }
  for (const dept of spec.departments) {
    endpoint.searchParams.append('person_departments[]', dept);
  }
  for (const seniority of spec.seniorities) {
    endpoint.searchParams.append('person_seniorities[]', seniority);
  }
  for (const location of spec.locations) {
    endpoint.searchParams.append('person_locations[]', location);
  }
  for (const companyName of spec.company_names) {
    endpoint.searchParams.append('organization_names[]', companyName);
  }

  // Apollo "Find People Using Filters" docs use query params + x-api-key.
  const res = await fetch(endpoint.toString(), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
      accept: 'application/json',
      'x-api-key': apiKey,
    },
  });

  if (!res.ok) {
    const errText = await res.text().catch(() => '');
    let errJson = {};
    try {
      errJson = JSON.parse(errText);
    } catch {
      // ignore
    }
    const msg =
      errJson?.error?.message ||
      errJson?.message ||
      errText ||
      `Apollo People Search error: ${res.status}`;
    throw new Error(`Apollo People Search error (${res.status}): ${msg}`);
  }

  const data = await res.json();
  return data;
}

function cloneSpec(spec) {
  return {
    company_names: [...(spec.company_names || [])],
    titles: [...(spec.titles || [])],
    departments: [...(spec.departments || [])],
    seniorities: [...(spec.seniorities || [])],
    locations: [...(spec.locations || [])],
    keywords: [...(spec.keywords || [])],
  };
}

function buildRelaxedSpecLevels(baseSpec) {
  const s0 = cloneSpec(baseSpec); // strict

  const s1 = cloneSpec(baseSpec); // drop location
  s1.locations = [];

  const s2 = cloneSpec(baseSpec); // drop location + seniority
  s2.locations = [];
  s2.seniorities = [];

  const s3 = cloneSpec(baseSpec); // keep high signal only
  s3.locations = [];
  s3.seniorities = [];
  s3.departments = [];
  s3.keywords = [];

  return [s0, s1, s2, s3];
}

/**
 * High-level entrypoint.
 *
 * @param {object} params
 * @param {string} params.intent_text - natural-language description of your outreach goal
 * @param {number} [params.page]
 * @param {number} [params.per_page]
 * @returns {Promise<{ contacts: object[], apollo_raw: object, search_spec: object, module_status: string }>}
 */
export async function runContactDiscovery(params) {
  const { intent_text, page = 1, per_page = 25 } = params || {};

  if (!intent_text || !intent_text.trim()) {
    throw new Error('contact_discovery: intent_text is required');
  }

  // 1) Use LLM to map intent -> Apollo filters
  const searchSpec = await buildApolloSearchSpecFromIntent(intent_text);
  const specLevels = buildRelaxedSpecLevels(searchSpec);

  let apolloResponse = null;
  let contacts = [];
  let usedSearchSpec = searchSpec;
  let retry_count = 0;

  for (let i = 0; i < specLevels.length; i += 1) {
    const candidateSpec = specLevels[i];
    const result = await callApolloPeopleSearch({
      spec: candidateSpec,
      page,
      per_page,
    });
    const found = result.people || result.contacts || [];
    if (found.length > 0) {
      apolloResponse = result;
      contacts = found;
      usedSearchSpec = candidateSpec;
      retry_count = i;
      break;
    }
    apolloResponse = result;
    retry_count = i;
  }

  return {
    contacts,
    apollo_raw: apolloResponse,
    search_spec: usedSearchSpec,
    retry_count,
    module_status: 'success',
  };
}

